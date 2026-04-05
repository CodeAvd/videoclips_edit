from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.services.transcript_provider import TranscriptSegmentItem, TranscriptWordItem

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "we",
    "what",
    "when",
    "why",
    "you",
}
HOOK_TERMS = {"how", "why", "stop", "mistake", "secret", "problem", "fix", "never", "best", "fast"}


@dataclass(slots=True)
class RankedCandidate:
    start_ms: int
    end_ms: int
    hook_score: float
    semantic_score: float
    audio_score: float
    visual_score: float
    llm_score: float
    final_score: float
    duplicate_group: str
    topic_cluster: str
    length_bucket: str
    rationale_jsonb: dict


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def length_bucket_for(duration_ms: int) -> str:
    if duration_ms <= 25_000:
        return "15_25"
    if duration_ms <= 40_000:
        return "25_40"
    return "40_60"


def duration_targets(total_duration_ms: int) -> list[int]:
    if total_duration_ms < 15_000:
        return [5_000, 8_000, 12_000]
    return [15_000, 22_000, 35_000, 50_000]


def text_keywords(text: str, *, limit: int = 2) -> list[str]:
    tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9']+", text)]
    unique_tokens: list[str] = []
    for token in tokens:
        if token in STOPWORDS or len(token) < 3:
            continue
        if token in unique_tokens:
            continue
        unique_tokens.append(token)
        if len(unique_tokens) >= limit:
            break
    return unique_tokens or ["general"]


def duplicate_group_for(text: str) -> str:
    signature = " ".join(text_keywords(text, limit=4))
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:10]
    return f"dup_{digest}"


def topic_cluster_for(text: str) -> str:
    return "_".join(text_keywords(text, limit=2))


def average_range_score(track: list[dict], *, start_ms: int, end_ms: int, key: str, default: float) -> float:
    matches = [
        item[key]
        for item in track
        if item.get("start_ms", 0) < end_ms and item.get("end_ms", end_ms) > start_ms and key in item
    ]
    if not matches:
        return default
    return clamp_score(sum(float(value) for value in matches) / len(matches))


def build_candidate_windows(words: list[TranscriptWordItem], segments: list[TranscriptSegmentItem]) -> list[tuple[int, int, str]]:
    if not words:
        return []
    total_duration_ms = words[-1].end_ms
    targets = duration_targets(total_duration_ms)
    start_indices = sorted({0, *range(0, len(words), 2), *[max(0, segment.seq_no - 1) * 4 for segment in segments]})
    windows: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for start_index in start_indices:
        if start_index >= len(words):
            continue
        for duration_ms in targets:
            start_ms = words[start_index].start_ms
            end_ms = min(total_duration_ms, start_ms + duration_ms)
            window_words = [word for word in words if word.start_ms >= start_ms and word.end_ms <= end_ms]
            if len(window_words) < 8:
                continue
            actual_end_ms = window_words[-1].end_ms
            key = (start_ms, actual_end_ms)
            if key in seen:
                continue
            seen.add(key)
            text = " ".join(word.token for word in window_words).strip()
            windows.append((start_ms, actual_end_ms, text))
            if len(windows) >= 80:
                return windows
    return windows


def score_candidate(
    *,
    start_ms: int,
    end_ms: int,
    text: str,
    pause_track: list[dict],
    audio_energy_track: list[dict],
    scene_track: list[dict],
    crop_risk_track: list[dict],
) -> RankedCandidate:
    duration_ms = end_ms - start_ms
    words = re.findall(r"[A-Za-z0-9']+", text)
    first_phrase = " ".join(words[:12]).lower()
    keyword_hits = sum(1 for token in words[:12] if token.lower() in HOOK_TERMS)
    hook_score = clamp_score(
        0.35
        + (0.15 if "?" in text else 0.0)
        + (0.08 if any(char.isdigit() for char in first_phrase) else 0.0)
        + (0.1 if keyword_hits else 0.0)
        + min(0.15, keyword_hits * 0.04)
    )
    semantic_score = clamp_score(
        0.3
        + min(0.2, len(words) / 100)
        + (0.12 if text.rstrip().endswith((".", "!", "?")) else 0.0)
        + (0.1 if duration_ms >= 12_000 else 0.0)
    )
    audio_score = clamp_score(
        0.2
        + average_range_score(audio_energy_track, start_ms=start_ms, end_ms=end_ms, key="energy_score", default=0.4) * 0.6
        + min(0.12, len([pause for pause in pause_track if pause["start_ms"] >= start_ms and pause["end_ms"] <= end_ms]) * 0.03)
    )
    scene_density = len([scene for scene in scene_track if start_ms <= scene["start_ms"] <= end_ms])
    avg_crop_risk = average_range_score(crop_risk_track, start_ms=start_ms, end_ms=end_ms, key="crop_risk", default=0.25)
    visual_score = clamp_score(0.4 + min(0.15, scene_density * 0.04) + (1 - avg_crop_risk) * 0.35)
    llm_score = clamp_score(0.2 + hook_score * 0.35 + semantic_score * 0.35 + audio_score * 0.1 + visual_score * 0.1)
    final_score = clamp_score(
        hook_score * 0.25
        + semantic_score * 0.25
        + audio_score * 0.2
        + visual_score * 0.15
        + llm_score * 0.15
    )
    duplicate_group = duplicate_group_for(text)
    topic_cluster = topic_cluster_for(text)
    return RankedCandidate(
        start_ms=start_ms,
        end_ms=end_ms,
        hook_score=round(hook_score, 4),
        semantic_score=round(semantic_score, 4),
        audio_score=round(audio_score, 4),
        visual_score=round(visual_score, 4),
        llm_score=round(llm_score, 4),
        final_score=round(final_score, 4),
        duplicate_group=duplicate_group,
        topic_cluster=topic_cluster,
        length_bucket=length_bucket_for(duration_ms),
        rationale_jsonb={
            "hook_terms": keyword_hits,
            "scene_density": scene_density,
            "avg_crop_risk": round(avg_crop_risk, 4),
            "length_ms": duration_ms,
            "why_it_works": "baseline transcript-plus-feature score",
        },
    )


def diversify_candidates(candidates: list[RankedCandidate], *, max_items: int = 60) -> list[RankedCandidate]:
    ranked = sorted(candidates, key=lambda item: item.final_score, reverse=True)
    selected: list[RankedCandidate] = []
    duplicate_counts: dict[str, int] = {}
    topic_counts: dict[str, int] = {}
    for candidate in ranked:
        if duplicate_counts.get(candidate.duplicate_group, 0) >= 2:
            continue
        if topic_counts.get(candidate.topic_cluster, 0) >= 4:
            continue
        selected.append(candidate)
        duplicate_counts[candidate.duplicate_group] = duplicate_counts.get(candidate.duplicate_group, 0) + 1
        topic_counts[candidate.topic_cluster] = topic_counts.get(candidate.topic_cluster, 0) + 1
        if len(selected) >= max_items:
            return selected
    for candidate in ranked:
        if candidate in selected:
            continue
        selected.append(candidate)
        if len(selected) >= max_items:
            break
    return selected


def rank_candidates(
    *,
    words: list[TranscriptWordItem],
    segments: list[TranscriptSegmentItem],
    pause_track: list[dict],
    audio_energy_track: list[dict],
    scene_track: list[dict],
    crop_risk_track: list[dict],
) -> list[RankedCandidate]:
    windows = build_candidate_windows(words, segments)
    scored = [
        score_candidate(
            start_ms=start_ms,
            end_ms=end_ms,
            text=text,
            pause_track=pause_track,
            audio_energy_track=audio_energy_track,
            scene_track=scene_track,
            crop_risk_track=crop_risk_track,
        )
        for start_ms, end_ms, text in windows
    ]
    return diversify_candidates(scored)
