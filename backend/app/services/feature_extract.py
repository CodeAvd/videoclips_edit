from __future__ import annotations

import audioop
import wave
from io import BytesIO

from app.services.transcript_provider import TranscriptSegmentItem, TranscriptWordItem


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def build_pause_track(words: list[TranscriptWordItem], *, gap_threshold_ms: int = 220) -> list[dict]:
    pauses: list[dict] = []
    for previous, current in zip(words, words[1:], strict=False):
        gap_ms = current.start_ms - previous.end_ms
        if gap_ms < gap_threshold_ms:
            continue
        pauses.append(
            {
                "start_ms": previous.end_ms,
                "end_ms": current.start_ms,
                "duration_ms": gap_ms,
            }
        )
    return pauses


def build_audio_energy_track(normalized_audio_bytes: bytes, *, window_ms: int = 500) -> list[dict]:
    with wave.open(BytesIO(normalized_audio_bytes), "rb") as wav_file:
        frame_rate = wav_file.getframerate()
        sample_width = wav_file.getsampwidth()
        frames_per_window = max(1, int(frame_rate * window_ms / 1000))
        window_index = 0
        windows: list[dict] = []
        max_rms = 1
        while True:
            frames = wav_file.readframes(frames_per_window)
            if not frames:
                break
            rms = max(1, audioop.rms(frames, sample_width))
            max_rms = max(max_rms, rms)
            windows.append({"window_index": window_index, "rms": rms})
            window_index += 1

    normalized: list[dict] = []
    for item in windows:
        start_ms = item["window_index"] * window_ms
        end_ms = start_ms + window_ms
        normalized.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "energy_score": clamp_score(item["rms"] / max_rms),
            }
        )
    return normalized


def build_scene_track(segments: list[TranscriptSegmentItem]) -> list[dict]:
    track: list[dict] = []
    for segment in segments:
        if segment.seq_no == 1:
            track.append({"start_ms": segment.start_ms, "reason": "opening_boundary"})
            continue
        if (segment.pause_before_ms or 0) >= 400:
            track.append({"start_ms": segment.start_ms, "reason": "long_pause"})
            continue
        track.append({"start_ms": segment.start_ms, "reason": "segment_boundary"})
    return track


def build_active_speaker_track(segments: list[TranscriptSegmentItem]) -> list[dict]:
    if not segments:
        return []
    merged: list[dict] = []
    for segment in segments:
        speaker = segment.speaker or "unknown"
        if merged and merged[-1]["speaker"] == speaker:
            merged[-1]["end_ms"] = segment.end_ms
            continue
        merged.append({"speaker": speaker, "start_ms": segment.start_ms, "end_ms": segment.end_ms})
    return merged


def build_crop_risk_track(segments: list[TranscriptSegmentItem], *, speaker_count_estimate: int | None) -> list[dict]:
    if not segments:
        return []
    baseline = 0.18 if (speaker_count_estimate or 1) <= 1 else 0.42
    return [
        {
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "crop_risk": clamp_score(baseline + (0.08 if (segment.pause_before_ms or 0) < 120 else 0.0)),
        }
        for segment in segments
    ]


def summarize_features(
    *,
    pauses: list[dict],
    audio_energy: list[dict],
    scene_track: list[dict],
    active_speaker_track: list[dict],
    crop_risk_track: list[dict],
) -> dict:
    avg_energy = sum(item["energy_score"] for item in audio_energy) / max(1, len(audio_energy))
    avg_crop_risk = sum(item["crop_risk"] for item in crop_risk_track) / max(1, len(crop_risk_track))
    return {
        "pause_count": len(pauses),
        "scene_boundary_count": len(scene_track),
        "speaker_turn_count": len(active_speaker_track),
        "avg_energy_score": round(avg_energy, 4),
        "avg_crop_risk": round(avg_crop_risk, 4),
    }
