from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from experiments.autoresearch.taxonomy import (
    END_SAMPLE_OFFSETS_MS,
    HIGH_CHANGE_WINDOW_RADIUS_MS,
    MAX_BODY_SCENES,
    MAX_HIGH_CHANGE_WINDOWS,
    OPENING_SAMPLE_MS,
    SCHEMA_VERSION,
    clamp_ms,
    length_bucket_for_duration,
    ratio,
    unique_sorted_timestamps,
)

SCENE_CHANGE_THRESHOLD = 0.35
SCENE_CHANGE_MIN_GAP_MS = 400


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tool_version(command: str, *, version_arg: str = "-version") -> str | None:
    if shutil.which(command) is None:
        return None
    try:
        result = subprocess.run(
            [command, version_arg],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def run_ffprobe_json(*, video_path: Path, ffprobe_bin: str = "ffprobe") -> dict[str, Any]:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,width,height,avg_frame_rate,duration,bit_rate:format=duration,bit_rate",
        "-show_entries",
        "frame=best_effort_timestamp_time,key_frame",
        "-of",
        "json",
        str(video_path),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def run_ffmpeg_scene_changes(
    *,
    video_path: Path,
    ffmpeg_bin: str = "ffmpeg",
    threshold: float = SCENE_CHANGE_THRESHOLD,
    min_gap_ms: int = SCENE_CHANGE_MIN_GAP_MS,
) -> list[int]:
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-i",
        str(video_path),
        "-vf",
        f"select='gt(scene,{threshold})',showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"scenechange probe failed with exit code {result.returncode}")
    return _parse_scene_change_timestamps_ms(result.stderr, min_gap_ms=min_gap_ms)


def resolve_reference_video_path(*, collection_dir: Path, file_name: str) -> Path:
    for candidate in (collection_dir / "videos" / file_name, collection_dir / file_name):
        if candidate.exists():
            return candidate
    return collection_dir / "videos" / file_name


def build_manifest_lock(
    *,
    collection_dir: Path,
    entries: list[Any],
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    ocr_provider: str = "disabled",
    vlm_provider: str = "disabled",
    vlm_model: str | None = None,
) -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    for entry in entries:
        video_path = resolve_reference_video_path(collection_dir=collection_dir, file_name=entry.file_name)
        reference_payload = {
            "reference_id": entry.reference_id,
            "file_name": entry.file_name,
            "video_sha256": file_sha256(video_path),
            "video_size_bytes": video_path.stat().st_size,
        }
        if entry.subtitle_file:
            subtitle_path = collection_dir / entry.subtitle_file
            reference_payload["subtitle_file"] = entry.subtitle_file
            reference_payload["subtitle_sha256"] = file_sha256(subtitle_path)
        if entry.transcript_file:
            transcript_path = collection_dir / entry.transcript_file
            reference_payload["transcript_file"] = entry.transcript_file
            reference_payload["transcript_sha256"] = file_sha256(transcript_path)
        references.append(reference_payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_collection": collection_dir.name,
        "toolchain": {
            "ffmpeg": read_tool_version(ffmpeg_bin),
            "ffprobe": read_tool_version(ffprobe_bin),
            "ocr": ocr_provider,
            "vlm": f"{vlm_provider}:{vlm_model}" if vlm_model else vlm_provider,
        },
        "references": references,
    }


def build_technical_probe(
    ffprobe_payload: dict[str, Any],
    *,
    scene_change_timestamps_ms: list[int] | None = None,
) -> dict[str, Any]:
    streams = ffprobe_payload.get("streams", [])
    format_payload = ffprobe_payload.get("format", {})
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_stream_count = sum(1 for stream in streams if stream.get("codec_type") == "audio")
    subtitle_stream_count = sum(1 for stream in streams if stream.get("codec_type") == "subtitle")
    fps = _parse_avg_frame_rate(video_stream.get("avg_frame_rate"))
    duration_ms = int(round((_coerce_float(video_stream.get("duration")) or _coerce_float(format_payload.get("duration")) or 0.0) * 1000))
    width = _coerce_int(video_stream.get("width"))
    height = _coerce_int(video_stream.get("height"))
    aspect_ratio = f"{width}:{height}" if width and height else None
    bitrate_kbps = _coerce_float(video_stream.get("bit_rate")) or _coerce_float(format_payload.get("bit_rate"))
    if bitrate_kbps is not None:
        bitrate_kbps = round(bitrate_kbps / 1000.0, 2)
    keyframe_timestamps = _collect_keyframe_timestamps_ms(ffprobe_payload)
    scene_change_timestamps = (
        sorted({int(timestamp) for timestamp in scene_change_timestamps_ms if int(timestamp) > 0})
        if scene_change_timestamps_ms is not None
        else keyframe_timestamps
    )
    scene_count = max(1, len(scene_change_timestamps) + 1)
    cut_density = round(len(scene_change_timestamps) / max(duration_ms / 60_000.0, 1e-6), 4) if duration_ms > 0 else 0.0
    opening_cut_count = sum(1 for timestamp in scene_change_timestamps if 0 < timestamp <= 3000)
    return {
        "duration_ms": duration_ms,
        "length_bucket": length_bucket_for_duration(duration_ms),
        "fps": fps,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else None,
        "aspect_ratio": aspect_ratio,
        "bitrate_kbps": bitrate_kbps,
        "audio_stream_count": audio_stream_count,
        "subtitle_stream_count": subtitle_stream_count,
        "keyframe_count": len(keyframe_timestamps),
        "scene_count": scene_count,
        "scene_count_estimate": scene_count,
        "cut_density_per_min": cut_density,
        "cut_density_per_minute": cut_density,
        "opening_cut_count": opening_cut_count,
        "scene_boundaries_ms": [0, *scene_change_timestamps],
    }


def run_ffmpeg_silencedetect(*, video_path: Path, ffmpeg_bin: str = "ffmpeg") -> list[dict[str, float]]:
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-i",
        str(video_path),
        "-af",
        "silencedetect=n=-35dB:d=0.18",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    return _parse_ffmpeg_ranges(result.stderr, start_pattern=r"silence_start:\s*([0-9.]+)", end_pattern=r"silence_end:\s*([0-9.]+)")


def run_ffmpeg_blackdetect(*, video_path: Path, ffmpeg_bin: str = "ffmpeg") -> list[dict[str, float]]:
    command = [
        ffmpeg_bin,
        "-hide_banner",
        "-i",
        str(video_path),
        "-vf",
        "blackdetect=d=0.15:pic_th=0.98",
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    return _parse_ffmpeg_ranges(result.stderr, start_pattern=r"black_start:\s*([0-9.]+)", end_pattern=r"black_end:\s*([0-9.]+)")


def build_sampling_map(
    *,
    reference_id: str,
    video_path: Path,
    technical_probe: dict[str, Any],
    silence_ranges: list[dict[str, float]] | None = None,
    black_ranges: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    duration_ms = technical_probe["duration_ms"]
    scene_boundaries_ms = unique_sorted_timestamps(
        technical_probe.get("scene_boundaries_ms", [0]),
        duration_ms=duration_ms,
    )
    opening_timestamps = unique_sorted_timestamps(OPENING_SAMPLE_MS, duration_ms=duration_ms)
    body_timestamps = _build_body_scene_timestamps(scene_boundaries_ms=scene_boundaries_ms, duration_ms=duration_ms)
    window_specs = _build_high_change_windows(
        scene_boundaries_ms=scene_boundaries_ms,
        silence_ranges=silence_ranges or [],
        black_ranges=black_ranges or [],
        duration_ms=duration_ms,
    )
    window_timestamps = [timestamp for window in window_specs for timestamp in window["timestamps_ms"]]
    end_timestamps = unique_sorted_timestamps(
        [max(0, duration_ms - offset) for offset in END_SAMPLE_OFFSETS_MS],
        duration_ms=duration_ms,
    )
    all_timestamps = unique_sorted_timestamps(
        [*opening_timestamps, *body_timestamps, *window_timestamps, *end_timestamps],
        duration_ms=duration_ms,
    )
    frame_index_map = {timestamp: f"f{index}" for index, timestamp in enumerate(all_timestamps)}
    frames = [
        {
            "frame_id": frame_index_map[timestamp],
            "timestamp_ms": timestamp,
            "timestamp_s": round(timestamp / 1000.0, 3),
            "relative_path": None,
        }
        for timestamp in all_timestamps
    ]
    return {
        "reference_id": reference_id,
        "video_path": str(video_path),
        "zones": {
            "opening_frames": [frame_index_map[timestamp] for timestamp in opening_timestamps],
            "scene_frames": [frame_index_map[timestamp] for timestamp in body_timestamps],
            "high_change_windows": [
                {
                    "window_id": window["window_id"],
                    "center_ms": window["center_ms"],
                    "score": window["score"],
                    "frame_ids": [frame_index_map[timestamp] for timestamp in window["timestamps_ms"]],
                }
                for window in window_specs
            ],
            "end_frames": [frame_index_map[timestamp] for timestamp in end_timestamps],
        },
        "frames": frames,
        "scene_boundaries_ms": scene_boundaries_ms,
        "silence_ranges": silence_ranges or [],
        "black_ranges": black_ranges or [],
    }


def materialize_sampling_frames(
    *,
    video_path: Path,
    sampling_map: dict[str, Any],
    frame_root: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> dict[str, Any]:
    target_dir = frame_root / sampling_map["reference_id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    for frame in sampling_map["frames"]:
        file_name = f"{frame['frame_id']}.jpg"
        output_path = target_dir / file_name
        command = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{frame['timestamp_ms'] / 1000.0:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        frame["relative_path"] = str(Path("frames") / sampling_map["reference_id"] / file_name)
    return sampling_map


def summarize_timing_stats(
    *,
    technical_probe: dict[str, Any],
    silence_ranges: list[dict[str, float]],
) -> dict[str, Any]:
    duration_ms = technical_probe["duration_ms"]
    total_silence_ms = int(round(sum(item["duration_s"] for item in silence_ranges) * 1000))
    silence_ratio = ratio(total_silence_ms, duration_ms) if duration_ms > 0 else 0.0
    pause_stats = {
        "count": len(silence_ranges),
        "total_silence_ms": total_silence_ms,
        "max_silence_ms": int(round(max((item["duration_s"] for item in silence_ranges), default=0.0) * 1000)),
    }
    return {
        "silence_ratio": silence_ratio,
        "pause_stats": pause_stats,
    }


def summarize_opening_window(
    *,
    technical_probe: dict[str, Any],
    silence_ranges: list[dict[str, float]],
    black_ranges: list[dict[str, float]],
    window_end_ms: int = 4000,
) -> dict[str, int]:
    opening_window_ms = min(max(int(window_end_ms), 0), max(int(technical_probe.get("duration_ms", 0) or 0), 0))
    return {
        "opening_window_ms": opening_window_ms,
        "opening_silence_ms": _range_overlap_total_ms(ranges=silence_ranges, window_end_ms=opening_window_ms),
        "opening_black_ms": _range_overlap_total_ms(ranges=black_ranges, window_end_ms=opening_window_ms),
    }


def _build_body_scene_timestamps(*, scene_boundaries_ms: list[int], duration_ms: int) -> list[int]:
    if duration_ms <= 0:
        return [0]
    boundaries = unique_sorted_timestamps([*scene_boundaries_ms, duration_ms], duration_ms=duration_ms)
    timestamps: list[int] = []
    for start_ms, end_ms in zip(boundaries, boundaries[1:]):
        midpoint = clamp_ms(int((start_ms + end_ms) / 2), duration_ms)
        if midpoint <= 4000:
            continue
        timestamps.append(midpoint)
    return timestamps[:MAX_BODY_SCENES]


def _build_high_change_windows(
    *,
    scene_boundaries_ms: list[int],
    silence_ranges: list[dict[str, float]],
    black_ranges: list[dict[str, float]],
    duration_ms: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    boundaries = unique_sorted_timestamps(scene_boundaries_ms, duration_ms=duration_ms)
    for index, boundary_ms in enumerate(boundaries):
        if boundary_ms <= 500 or boundary_ms >= max(duration_ms - 500, 0):
            continue
        scene_delta = boundary_ms - boundaries[index - 1] if index > 0 else boundary_ms
        score = 1.0
        if scene_delta <= 1500:
            score += 1.0
        if _boundary_hits_range(boundary_ms, silence_ranges):
            score += 0.5
        if _boundary_hits_range(boundary_ms, black_ranges):
            score += 0.5
        candidates.append(
            {
                "center_ms": boundary_ms,
                "score": round(score, 4),
                "timestamps_ms": unique_sorted_timestamps(
                    [
                        boundary_ms - HIGH_CHANGE_WINDOW_RADIUS_MS,
                        boundary_ms,
                        boundary_ms + HIGH_CHANGE_WINDOW_RADIUS_MS,
                    ],
                    duration_ms=duration_ms,
                ),
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["center_ms"]))
    selected = candidates[:MAX_HIGH_CHANGE_WINDOWS]
    for index, window in enumerate(selected):
        window["window_id"] = f"w{index}"
    return selected


def _boundary_hits_range(boundary_ms: int, ranges: list[dict[str, float]]) -> bool:
    boundary_s = boundary_ms / 1000.0
    return any(item["start_s"] <= boundary_s <= item["end_s"] for item in ranges)


def _range_overlap_total_ms(*, ranges: list[dict[str, float]], window_end_ms: int) -> int:
    total_ms = 0
    for item in ranges:
        start_ms = max(int(round(float(item.get("start_s", 0.0)) * 1000)), 0)
        end_ms = max(int(round(float(item.get("end_s", 0.0)) * 1000)), start_ms)
        overlap_start = max(start_ms, 0)
        overlap_end = min(end_ms, window_end_ms)
        if overlap_end > overlap_start:
            total_ms += overlap_end - overlap_start
    return total_ms


def _parse_ffmpeg_ranges(stderr: str, *, start_pattern: str, end_pattern: str) -> list[dict[str, float]]:
    starts = [float(match) for match in re.findall(start_pattern, stderr or "")]
    ends = [float(match) for match in re.findall(end_pattern, stderr or "")]
    ranges: list[dict[str, float]] = []
    for start_s, end_s in zip(starts, ends):
        ranges.append(
            {
                "start_s": round(start_s, 4),
                "end_s": round(end_s, 4),
                "duration_s": round(max(end_s - start_s, 0.0), 4),
            }
        )
    return ranges


def _collect_keyframe_timestamps_ms(ffprobe_payload: dict[str, Any]) -> list[int]:
    timestamps: list[int] = []
    for frame in ffprobe_payload.get("frames", []):
        if int(frame.get("key_frame", 0) or 0) != 1:
            continue
        timestamp = _coerce_float(frame.get("best_effort_timestamp_time"))
        if timestamp is None:
            continue
        timestamps.append(int(round(timestamp * 1000)))
    return sorted(set(timestamp for timestamp in timestamps if timestamp > 0))


def _parse_scene_change_timestamps_ms(stderr: str, *, min_gap_ms: int) -> list[int]:
    timestamps = [
        int(round(float(match) * 1000))
        for match in re.findall(r"pts_time:([0-9.]+)", stderr or "")
    ]
    unique_timestamps = sorted({timestamp for timestamp in timestamps if timestamp > 0})
    return _coalesce_timestamps_ms(unique_timestamps, min_gap_ms=min_gap_ms)


def _coalesce_timestamps_ms(timestamps_ms: list[int], *, min_gap_ms: int) -> list[int]:
    coalesced: list[int] = []
    for timestamp in timestamps_ms:
        if not coalesced or timestamp - coalesced[-1] >= min_gap_ms:
            coalesced.append(timestamp)
    return coalesced


def _parse_avg_frame_rate(raw_value: Any) -> float | None:
    if raw_value in (None, "", "0/0"):
        return None
    if isinstance(raw_value, (int, float)):
        return float(raw_value)
    if isinstance(raw_value, str) and "/" in raw_value:
        numerator, denominator = raw_value.split("/", 1)
        numerator_value = _coerce_float(numerator)
        denominator_value = _coerce_float(denominator)
        if not numerator_value or not denominator_value:
            return None
        return round(numerator_value / denominator_value, 4)
    return _coerce_float(raw_value)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
