from __future__ import annotations

import re
from statistics import mean
from typing import Iterable


SCHEMA_VERSION = "refintel.v2"

OPENING_SAMPLE_MS = [0, 500, 1000, 2000, 3000, 4000]
END_SAMPLE_OFFSETS_MS = [2000, 1000, 250]
HIGH_CHANGE_WINDOW_RADIUS_MS = 250
MAX_BODY_SCENES = 8
MAX_HIGH_CHANGE_WINDOWS = 3


def length_bucket_for_duration(duration_ms: int) -> str:
    if duration_ms < 15_000:
        return "under_15"
    if duration_ms < 25_000:
        return "15_25"
    if duration_ms < 40_000:
        return "25_40"
    if duration_ms < 60_000:
        return "40_60"
    return "60_plus"


def ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(count / total, 4)


def clamp_ms(timestamp_ms: int, duration_ms: int) -> int:
    if duration_ms <= 0:
        return 0
    return max(0, min(timestamp_ms, max(duration_ms - 1, 0)))


def unique_sorted_timestamps(values: Iterable[int], *, duration_ms: int) -> list[int]:
    normalized = {clamp_ms(int(value), duration_ms) for value in values if value is not None}
    return sorted(normalized)


def density_band(value: float, *, low: float, medium: float, high: float) -> str:
    if value >= high:
        return "high"
    if value >= medium:
        return "medium"
    if value >= low:
        return "light"
    return "none"


def cut_density_band(value: float) -> str:
    return density_band(value, low=8.0, medium=18.0, high=30.0)


def silence_trim_level(silence_ratio: float, cut_density_per_minute: float) -> str:
    if silence_ratio >= 0.18 or cut_density_per_minute <= 8.0:
        return "aggressive"
    if silence_ratio >= 0.08:
        return "moderate"
    return "light"


def caption_style_family(
    *,
    subtitle_source: str,
    emphasis_patterns: Iterable[str],
    text_occupancy_band: str,
) -> str:
    emphasis = set(emphasis_patterns)
    if subtitle_source == "burned" and ("all_caps" in emphasis or "highlight_words" in emphasis):
        return "kinetic_phrase_grouped"
    if subtitle_source in {"sidecar", "embedded"} and text_occupancy_band in {"medium", "high"}:
        return "editorial_phrase_grouped"
    if subtitle_source == "none":
        return "minimal"
    return "minimal_phrase_grouped"


def overlay_family(
    *,
    notes: str | None,
    subtitle_source: str,
    headline_card_presence: bool,
    burned_caption_present: bool,
) -> str:
    note_tokens = normalized_tokens(notes)
    if headline_card_presence or "headline" in note_tokens:
        return "headline_card"
    if burned_caption_present or subtitle_source == "burned":
        return "caption_led"
    if {"overlay", "text", "callout"} & note_tokens:
        return "text_callouts"
    return "minimal"


def opening_frame_mode(
    *,
    notes: str | None,
    burned_caption_present: bool,
    text_occupancy_band: str,
    proof_asset_presence: bool,
) -> str:
    note_tokens = normalized_tokens(notes)
    if proof_asset_presence:
        return "proof_first"
    if burned_caption_present or text_occupancy_band in {"medium", "high"} or "headline" in note_tokens:
        return "text_first"
    if {"split", "layout", "podcast"} & note_tokens:
        return "layout_first"
    return "face_first"


def hook_family(*, hook_text: str | None, transcript_lead: str | None, notes: str | None) -> str:
    text = " ".join(part for part in [hook_text, transcript_lead, notes] if part).lower()
    if not text:
        return "unknown"
    if re.search(r"\b(stop|don't|never|quit|wrong)\b", text):
        return "counterintuitive_claim"
    if re.search(r"\b(how|here's how|tutorial|step)\b", text):
        return "how_to"
    if re.search(r"\b(secret|mistake|mistakes|hack|truth)\b", text):
        return "curiosity_gap"
    if re.search(r"\b(news|update|today|breaking)\b", text):
        return "news_peek"
    if re.search(r"\b(i tried|i spent|i tested|we tested)\b", text):
        return "experiment_result"
    return "direct_claim"


def cta_family(cta_text: str | None) -> str:
    if not cta_text:
        return "none"
    lowered = cta_text.lower()
    if re.search(r"\b(comment|reply|tell me)\b", lowered):
        return "engagement"
    if re.search(r"\b(subscribe|follow)\b", lowered):
        return "follow"
    if re.search(r"\b(link|bio|download|course)\b", lowered):
        return "offplatform"
    return "generic"


def format_archetype(*, notes: str | None, transcript_text: str | None, style_family: str | None) -> str:
    text = " ".join(part for part in [notes, transcript_text, style_family] if part).lower()
    if re.search(r"\b(game|gameplay|stream)\b", text):
        return "gameplay_commentary"
    if re.search(r"\b(screen|ui|demo|recording)\b", text):
        return "screen_recording_demo"
    if re.search(r"\b(podcast|interview|host|guest)\b", text):
        return "dual_podcast_split"
    if re.search(r"\b(news|daily-news|recap)\b", text):
        return "news_recap"
    if re.search(r"\b(tutorial|how to|step)\b", text):
        return "tutorial"
    if re.search(r"\b(case study|testimonial|client)\b", text):
        return "testimonial_case"
    return "single_talking_head"


def narrative_packaging_shape(*, format_archetype_value: str, hook_family_value: str, cta_family_value: str) -> str:
    if format_archetype_value in {"news_recap", "tutorial"}:
        return "hook_then_rapid_explainer"
    if hook_family_value in {"counterintuitive_claim", "curiosity_gap"}:
        return "claim_then_proof"
    if cta_family_value != "none":
        return "claim_then_takeaway_then_cta"
    return "claim_then_takeaway"


def pattern_interrupt_types(*, notes: str | None, cut_density_per_minute: float, headline_card_presence: bool) -> list[str]:
    interrupts: list[str] = []
    note_tokens = normalized_tokens(notes)
    if headline_card_presence or "headline" in note_tokens:
        interrupts.append("text_reset")
    if cut_density_per_minute >= 24.0:
        interrupts.append("rapid_cut_reset")
    if {"zoom", "punch", "punch-in"} & note_tokens:
        interrupts.append("punch_in")
    if {"broll", "insert", "overlay"} & note_tokens:
        interrupts.append("visual_insert")
    return interrupts


def sticky_factors(
    *,
    hook_family_value: str,
    headline_card_presence: bool,
    burned_caption_present: bool,
    proof_asset_presence: bool,
    cut_density_per_minute: float,
) -> list[str]:
    factors: list[str] = []
    if headline_card_presence:
        factors.append("headline_card")
    if burned_caption_present:
        factors.append("keyword_highlight")
    if proof_asset_presence:
        factors.append("proof_asset")
    if cut_density_per_minute >= 18.0:
        factors.append("fast_visual_turnover")
    if hook_family_value != "unknown":
        factors.append(hook_family_value)
    return factors


def text_occupancy_band(occupancy_ratio: float) -> str:
    if occupancy_ratio >= 0.28:
        return "high"
    if occupancy_ratio >= 0.12:
        return "medium"
    if occupancy_ratio > 0:
        return "light"
    return "none"


def average(values: Iterable[float]) -> float:
    collected = [value for value in values]
    if not collected:
        return 0.0
    return round(mean(collected), 4)


def normalized_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {token for token in re.split(r"[^a-z0-9_+-]+", text.lower()) if token}
