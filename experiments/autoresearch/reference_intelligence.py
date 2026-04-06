from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from experiments.autoresearch.ocr import build_ocr_provider, run_ocr_pass, summarize_ocr_reference
from experiments.autoresearch.sampling import (
    build_manifest_lock,
    build_sampling_map,
    build_technical_probe,
    materialize_sampling_frames,
    resolve_reference_video_path,
    run_ffmpeg_blackdetect,
    run_ffmpeg_scene_changes,
    run_ffmpeg_silencedetect,
    run_ffprobe_json,
    summarize_opening_window,
    summarize_timing_stats,
)
from experiments.autoresearch.synthesis import (
    build_caption_evidence_v2,
    build_cluster_payload,
    build_comparison_report_v2,
    build_content_evidence_v2,
    build_opening_packaging_v2,
    build_reference_evidence_items,
    build_style_evidence_v2,
    build_summary_payload,
    synthesize_preset_bundle_v2,
)
from experiments.autoresearch.taxonomy import SCHEMA_VERSION
from experiments.autoresearch.vlm_openai import build_classifier, classify_sampling_maps


REQUIRED_MANIFEST_FIELDS = {
    "reference_id",
    "file_name",
    "channel_or_source",
    "theme",
    "language",
}
OPTIONAL_MANIFEST_FIELDS = {
    "platform",
    "notes",
    "style_family",
    "why_reference",
    "subtitle_file",
    "transcript_file",
    "hook_text",
    "cta_text",
}
ALLOWED_PRESET_FIELDS = {
    "caption_style",
    "crop_mode",
    "silence_trim_level",
    "broll_mode",
    "overlay_policy",
    "hook_packaging_rules",
    "ranking_weight_overrides",
}


class ReferenceManifestError(ValueError):
    """Raised when the reference manifest is invalid."""


class BenchmarkComparisonError(ValueError):
    """Raised when benchmark payloads cannot be compared safely."""


@dataclass(slots=True)
class ReferenceManifestEntry:
    reference_id: str
    file_name: str
    channel_or_source: str
    theme: str
    language: str
    platform: str | None = None
    notes: str | None = None
    style_family: str | None = None
    why_reference: str | None = None
    subtitle_file: str | None = None
    transcript_file: str | None = None
    hook_text: str | None = None
    cta_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PresetBundle:
    schema_version: str
    preset_name: str
    source_collection: str
    reference_ids: list[str]
    recommended_prompt_version: str
    recommended_scoring_policy_version: str
    prompt_version_suggestion: str
    ranking_weight_overrides: dict[str, float]
    caption_style: str
    crop_mode: str
    silence_trim_level: str
    broll_mode: str
    overlay_policy: dict[str, Any]
    hook_packaging_rules: dict[str, Any]
    preset_rationale: list[str]
    analysis_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_policy_fields"] = sorted(ALLOWED_PRESET_FIELDS)
        return payload


def _entry_from_mapping(record: dict[str, Any]) -> ReferenceManifestEntry:
    if not isinstance(record, dict):
        raise ReferenceManifestError("Each manifest entry must be an object.")
    unknown_keys = set(record.keys()).difference(REQUIRED_MANIFEST_FIELDS | OPTIONAL_MANIFEST_FIELDS)
    if unknown_keys:
        raise ReferenceManifestError(f"Manifest has unsupported fields: {sorted(unknown_keys)}")
    normalized_record = {key: record.get(key) or None for key in (REQUIRED_MANIFEST_FIELDS | OPTIONAL_MANIFEST_FIELDS)}
    missing = [field for field in REQUIRED_MANIFEST_FIELDS if not normalized_record.get(field)]
    if missing:
        reference_label = normalized_record.get("reference_id") or normalized_record.get("file_name") or "<unknown>"
        raise ReferenceManifestError(
            f"Reference '{reference_label}' is missing required values: {sorted(missing)}"
        )
    return ReferenceManifestEntry(**normalized_record)


def _parse_csv_manifest(path: Path) -> list[ReferenceManifestEntry]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ReferenceManifestError("CSV manifest must include a header row.")
        missing = REQUIRED_MANIFEST_FIELDS.difference(reader.fieldnames)
        if missing:
            raise ReferenceManifestError(f"Manifest is missing required fields: {sorted(missing)}")
        entries = [_entry_from_mapping({key: row.get(key) or None for key in reader.fieldnames}) for row in reader]
    return _normalize_manifest_entries(entries)


def _parse_json_manifest(path: Path) -> list[ReferenceManifestEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("references") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ReferenceManifestError("JSON manifest must be a list or include a top-level 'references' list.")
    entries = [_entry_from_mapping(record) for record in records]
    return _normalize_manifest_entries(entries)


def _normalize_manifest_entries(entries: list[ReferenceManifestEntry]) -> list[ReferenceManifestEntry]:
    reference_ids: set[str] = set()
    normalized: list[ReferenceManifestEntry] = []
    for entry in entries:
        if entry.reference_id in reference_ids:
            raise ReferenceManifestError(f"Duplicate reference_id '{entry.reference_id}' in manifest.")
        reference_ids.add(entry.reference_id)
        normalized.append(entry)
    return normalized


def load_reference_manifest(collection_dir: Path) -> list[ReferenceManifestEntry]:
    manifest_candidates = [collection_dir / "manifest.json", collection_dir / "manifest.csv"]
    manifest_path = next((candidate for candidate in manifest_candidates if candidate.exists()), None)
    if manifest_path is None:
        raise ReferenceManifestError(
            f"Collection '{collection_dir}' must contain manifest.json or manifest.csv."
        )
    entries = _parse_json_manifest(manifest_path) if manifest_path.suffix.lower() == ".json" else _parse_csv_manifest(manifest_path)
    _validate_manifest_files(collection_dir=collection_dir, entries=entries)
    return entries


def _validate_manifest_files(*, collection_dir: Path, entries: list[ReferenceManifestEntry]) -> None:
    for entry in entries:
        video_path = resolve_reference_video_path(collection_dir=collection_dir, file_name=entry.file_name)
        if not video_path.exists():
            raise ReferenceManifestError(
                f"Manifest file '{entry.file_name}' does not exist under {collection_dir / 'videos'} or {collection_dir}."
            )
        for sidecar_name in (entry.subtitle_file, entry.transcript_file):
            if sidecar_name and not (collection_dir / sidecar_name).exists():
                raise ReferenceManifestError(f"Sidecar file '{sidecar_name}' was declared but not found.")


def analyze_reference_collection(
    collection_dir: Path,
    *,
    ffprobe_bin: str = "ffprobe",
    ffmpeg_bin: str = "ffmpeg",
    output_dir: Path | None = None,
    ocr_provider_name: str = "disabled",
    tesseract_bin: str = "tesseract",
    vlm_provider_name: str = "disabled",
    vlm_model: str | None = None,
    openai_api_key: str | None = None,
) -> dict[str, Any]:
    entries = load_reference_manifest(collection_dir)
    manifest_lock = build_manifest_lock(
        collection_dir=collection_dir,
        entries=entries,
        ffmpeg_bin=ffmpeg_bin,
        ffprobe_bin=ffprobe_bin,
        ocr_provider=ocr_provider_name,
        vlm_provider=vlm_provider_name,
        vlm_model=vlm_model,
    )
    base_payloads: list[dict[str, Any]] = []
    sampling_maps: list[dict[str, Any]] = []
    for entry in entries:
        video_path = resolve_reference_video_path(collection_dir=collection_dir, file_name=entry.file_name)
        ffprobe_payload = run_ffprobe_json(video_path=video_path, ffprobe_bin=ffprobe_bin)
        scene_change_timestamps_ms, scene_change_warning = _safe_scene_change_probe(
            video_path=video_path,
            ffmpeg_bin=ffmpeg_bin,
            ffprobe_payload=ffprobe_payload,
        )
        technical_probe = build_technical_probe(
            ffprobe_payload,
            scene_change_timestamps_ms=scene_change_timestamps_ms,
        )
        silence_ranges, silence_warning = _safe_ffmpeg_probe(
            lambda: run_ffmpeg_silencedetect(video_path=video_path, ffmpeg_bin=ffmpeg_bin),
            warning_code="silencedetect_fallback",
            warning_message="silencedetect probe failed and was downgraded to an empty range set.",
        )
        black_ranges, black_warning = _safe_ffmpeg_probe(
            lambda: run_ffmpeg_blackdetect(video_path=video_path, ffmpeg_bin=ffmpeg_bin),
            warning_code="blackdetect_fallback",
            warning_message="blackdetect probe failed and was downgraded to an empty range set.",
        )
        technical_probe.update(summarize_timing_stats(technical_probe=technical_probe, silence_ranges=silence_ranges))
        opening_timing = summarize_opening_window(
            technical_probe=technical_probe,
            silence_ranges=silence_ranges,
            black_ranges=black_ranges,
        )
        sampling_map = build_sampling_map(
            reference_id=entry.reference_id,
            video_path=video_path,
            technical_probe=technical_probe,
            silence_ranges=silence_ranges,
            black_ranges=black_ranges,
        )
        sampling_maps.append(sampling_map)
        subtitle_lines = _load_text_lines(collection_dir / entry.subtitle_file) if entry.subtitle_file else []
        transcript_text = _load_text(collection_dir / entry.transcript_file) if entry.transcript_file else None
        transcript_lead = _extract_hook_text(collection_dir=collection_dir, transcript_file=entry.transcript_file)
        opening_text_hint = entry.hook_text or (subtitle_lines[0] if subtitle_lines else transcript_lead)
        base_payloads.append(
            {
                "entry": entry,
                "video_path": video_path,
                "technical_probe": technical_probe,
                "subtitle_lines": subtitle_lines,
                "transcript_text": transcript_text,
                "transcript_lead": opening_text_hint,
                "opening_timing": opening_timing,
                "warnings": [warning for warning in (scene_change_warning, silence_warning, black_warning) if warning],
            }
        )
    with _frame_root_context(output_dir=output_dir, should_materialize=(ocr_provider_name != "disabled" or vlm_provider_name != "disabled")) as frame_root:
        if frame_root is not None:
            for payload, sampling_map in zip(base_payloads, sampling_maps):
                materialize_sampling_frames(
                    video_path=payload["video_path"],
                    sampling_map=sampling_map,
                    frame_root=frame_root,
                    ffmpeg_bin=ffmpeg_bin,
                )
        ocr_provider = build_ocr_provider(ocr_provider_name, tesseract_bin=tesseract_bin)
        ocr_report = run_ocr_pass(
            sampling_maps=sampling_maps,
            frame_root=frame_root or Path(collection_dir / ".refintel_frames"),
            provider=ocr_provider,
        )
        vlm_classifier = build_classifier(
            provider_name=vlm_provider_name,
            model=vlm_model,
            api_key=openai_api_key,
        )
        vlm_report = classify_sampling_maps(
            sampling_maps=sampling_maps,
            frame_root=frame_root or Path(collection_dir / ".refintel_frames"),
            classifier=vlm_classifier,
        )
    report_warnings = _build_report_warnings(
        requested_ocr_provider=ocr_provider_name,
        resolved_ocr_provider=ocr_report.get("provider", "disabled"),
        requested_vlm_provider=vlm_provider_name,
        resolved_vlm_provider=vlm_report.get("provider", "disabled"),
        vlm_model=vlm_model,
        vlm_report=vlm_report,
    )
    reports: list[dict[str, Any]] = []
    for payload, sampling_map in zip(base_payloads, sampling_maps):
        entry = payload["entry"]
        technical_probe = payload["technical_probe"]
        ocr_summary = summarize_ocr_reference(
            reference_id=entry.reference_id,
            ocr_report=ocr_report,
            technical_probe=technical_probe,
        )
        opening_ocr_summary = summarize_ocr_reference(
            reference_id=entry.reference_id,
            ocr_report=ocr_report,
            technical_probe=technical_probe,
            frame_ids=sampling_map["zones"]["opening_frames"],
        )
        vlm_labels = _vlm_label_map(vlm_report, entry.reference_id)
        caption_evidence = build_caption_evidence_v2(
            entry=entry,
            subtitle_lines=payload["subtitle_lines"],
            technical_probe=technical_probe,
            ocr_summary=ocr_summary,
        )
        style_evidence = build_style_evidence_v2(
            entry=entry,
            technical_probe=technical_probe,
            caption_evidence=caption_evidence,
            ocr_summary=opening_ocr_summary,
            transcript_lead=payload["transcript_lead"],
            vlm_labels=vlm_labels,
        )
        content_evidence = build_content_evidence_v2(
            entry=entry,
            technical_probe=technical_probe,
            transcript_text=payload["transcript_text"],
            style_evidence=style_evidence,
            vlm_labels=vlm_labels,
        )
        opening_packaging = build_opening_packaging_v2(
            entry=entry,
            technical_probe=technical_probe,
            caption_evidence=caption_evidence,
            opening_timing=payload["opening_timing"],
            opening_ocr_summary=opening_ocr_summary,
            transcript_lead=payload["transcript_lead"],
            vlm_labels=vlm_labels,
            sampling_map=sampling_map,
        )
        evidence_items = build_reference_evidence_items(
            technical_probe=technical_probe,
            caption_evidence=caption_evidence,
            style_evidence=style_evidence,
            content_evidence=content_evidence,
            ocr_summary=ocr_summary,
            vlm_labels=vlm_labels,
            sampling_map=sampling_map,
        )
        summary_payload = build_summary_payload(
            style_evidence=style_evidence,
            content_evidence=content_evidence,
            ocr_summary=ocr_summary,
            technical_probe=technical_probe,
            vlm_labels=vlm_labels,
        )
        reports.append(
            {
                "reference": entry.to_dict(),
                "technical_probe": technical_probe,
                "caption_evidence": caption_evidence,
                "style_evidence": style_evidence,
                "content_evidence": content_evidence,
                "opening_packaging": opening_packaging,
                "sampling": {
                    "opening_frames": sampling_map["zones"]["opening_frames"],
                    "opening_window_ms": payload["opening_timing"]["opening_window_ms"],
                    "scene_windows": [window["window_id"] for window in sampling_map["zones"]["high_change_windows"]],
                    "end_frames": sampling_map["zones"]["end_frames"],
                },
                "ocr": {
                    "provider": ocr_summary["provider"],
                    "burned_caption_present": ocr_summary["burned_caption_present"],
                    "blocks": ocr_summary["blocks"],
                    "opening": {
                        "burned_caption_present": opening_ocr_summary["burned_caption_present"],
                        "blocks": opening_ocr_summary["blocks"],
                    },
                },
                "warnings": [*payload["warnings"], *_vlm_reference_warnings(vlm_report, entry.reference_id)],
                "evidence": evidence_items,
                "summary": summary_payload,
            }
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "source_collection": collection_dir.name,
        "reference_count": len(reports),
        "toolchain": manifest_lock["toolchain"],
        "manifest_lock": manifest_lock,
        "sampling_payload": {
            "schema_version": SCHEMA_VERSION,
            "source_collection": collection_dir.name,
            "references": sampling_maps,
        },
        "warnings": report_warnings,
        "ocr_report": ocr_report,
        "vlm_report": vlm_report,
        "references": reports,
    }
    cluster_payload = build_cluster_payload(report)
    report["cluster_payload"] = cluster_payload
    report["clusters"] = {
        cluster["cluster_id"]: cluster["reference_ids"]
        for cluster in cluster_payload["clusters"]
    }
    return report


def synthesize_preset_bundle(
    *,
    reference_report: dict[str, Any],
    preset_name: str,
    recommended_prompt_version: str,
    recommended_scoring_policy_version: str,
    ranking_weight_overrides: dict[str, float] | None = None,
) -> PresetBundle:
    payload = synthesize_preset_bundle_v2(
        reference_report=reference_report,
        preset_name=preset_name,
        recommended_prompt_version=recommended_prompt_version,
        recommended_scoring_policy_version=recommended_scoring_policy_version,
        ranking_weight_overrides=ranking_weight_overrides,
    )
    return PresetBundle(
        schema_version=payload["schema_version"],
        preset_name=payload["preset_name"],
        source_collection=payload["source_collection"],
        reference_ids=payload["reference_ids"],
        recommended_prompt_version=payload["recommended_prompt_version"],
        recommended_scoring_policy_version=payload["recommended_scoring_policy_version"],
        prompt_version_suggestion=payload["prompt_version_suggestion"],
        ranking_weight_overrides=payload["ranking_weight_overrides"],
        caption_style=payload["caption_style"],
        crop_mode=payload["crop_mode"],
        silence_trim_level=payload["silence_trim_level"],
        broll_mode=payload["broll_mode"],
        overlay_policy=payload["overlay_policy"],
        hook_packaging_rules=payload["hook_packaging_rules"],
        preset_rationale=payload["preset_rationale"],
        analysis_only=payload["analysis_only"],
    )


def build_comparison_report(
    *,
    preset_bundle: PresetBundle,
    baseline_benchmark_payload: dict[str, Any],
    candidate_benchmark_payload: dict[str, Any],
) -> dict[str, Any]:
    preset_bundle_payload = preset_bundle.to_dict()
    _validate_benchmark_payload_compatibility(
        preset_bundle=preset_bundle_payload,
        baseline_benchmark_payload=baseline_benchmark_payload,
        candidate_benchmark_payload=candidate_benchmark_payload,
    )
    return build_comparison_report_v2(
        preset_bundle=preset_bundle_payload,
        baseline_benchmark_payload=baseline_benchmark_payload,
        candidate_benchmark_payload=candidate_benchmark_payload,
    )


def write_reference_outputs(
    *,
    output_dir: Path,
    reference_report: dict[str, Any],
    preset_bundle: PresetBundle,
    comparison_report: dict[str, Any] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "reference_manifest.lock.json").write_text(
        json.dumps(reference_report["manifest_lock"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "reference_sampling_map.json").write_text(
        json.dumps(reference_report["sampling_payload"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "reference_ocr_report.json").write_text(
        json.dumps(reference_report["ocr_report"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "reference_style_report.json").write_text(
        json.dumps(reference_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "reference_clusters.json").write_text(
        json.dumps(reference_report["cluster_payload"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "preset_bundle.json").write_text(
        json.dumps(preset_bundle.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    if comparison_report is not None:
        (output_dir / "comparison_report.json").write_text(
            json.dumps(comparison_report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline reference-shorts intelligence lane.")
    parser.add_argument("--collection-dir", required=True, help="Path to references/<collection> directory.")
    parser.add_argument("--output-dir", help="Directory for generated artifacts. Defaults to <collection>/outputs.")
    parser.add_argument("--preset-name", required=True, help="Name of the generated preset bundle.")
    parser.add_argument("--prompt-version", required=True, help="Recommended prompt version for the preset.")
    parser.add_argument("--scoring-policy-version", required=True, help="Recommended scoring policy version for the preset.")
    parser.add_argument("--baseline-benchmark", help="Path to the baseline benchmark comparison artifact JSON.")
    parser.add_argument("--candidate-benchmark", help="Path to the candidate benchmark comparison artifact JSON.")
    parser.add_argument("--ffprobe-bin", default="ffprobe", help="ffprobe binary to use for technical analysis.")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg binary to use for local sampling and probes.")
    parser.add_argument("--ocr-provider", default="disabled", choices=["disabled", "auto", "paddleocr", "tesseract"], help="OCR provider for sampled frames.")
    parser.add_argument("--tesseract-bin", default="tesseract", help="Tesseract binary for OCR fallback.")
    parser.add_argument("--vlm-provider", default="disabled", choices=["disabled", "openai"], help="Optional multimodal classifier provider.")
    parser.add_argument("--vlm-model", help="Model name for the optional multimodal classifier.")
    parser.add_argument("--openai-api-key", help="Optional OpenAI API key override for the VLM provider.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    collection_dir = Path(args.collection_dir)
    output_dir = Path(args.output_dir) if args.output_dir else collection_dir / "outputs"
    reference_report = analyze_reference_collection(
        collection_dir,
        ffprobe_bin=args.ffprobe_bin,
        ffmpeg_bin=args.ffmpeg_bin,
        output_dir=output_dir,
        ocr_provider_name=args.ocr_provider,
        tesseract_bin=args.tesseract_bin,
        vlm_provider_name=args.vlm_provider,
        vlm_model=args.vlm_model,
        openai_api_key=args.openai_api_key,
    )
    preset_bundle = synthesize_preset_bundle(
        reference_report=reference_report,
        preset_name=args.preset_name,
        recommended_prompt_version=args.prompt_version,
        recommended_scoring_policy_version=args.scoring_policy_version,
    )
    comparison_report = None
    if args.baseline_benchmark or args.candidate_benchmark:
        if not args.baseline_benchmark or not args.candidate_benchmark:
            raise BenchmarkComparisonError(
                "Both --baseline-benchmark and --candidate-benchmark are required to generate a comparison report."
            )
        comparison_report = build_comparison_report(
            preset_bundle=preset_bundle,
            baseline_benchmark_payload=json.loads(Path(args.baseline_benchmark).read_text(encoding="utf-8")),
            candidate_benchmark_payload=json.loads(Path(args.candidate_benchmark).read_text(encoding="utf-8")),
        )
    write_reference_outputs(
        output_dir=output_dir,
        reference_report=reference_report,
        preset_bundle=preset_bundle,
        comparison_report=comparison_report,
    )


def _load_text_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.isdigit() or "-->" in stripped:
            continue
        lines.append(stripped)
    return lines


def _load_text(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _extract_hook_text(*, collection_dir: Path, transcript_file: str | None) -> str | None:
    if not transcript_file:
        return None
    transcript_path = collection_dir / transcript_file
    if not transcript_path.exists():
        return None
    lines = _load_text_lines(transcript_path)
    return lines[0] if lines else None


def _vlm_label_map(vlm_report: dict[str, Any], reference_id: str) -> dict[str, dict[str, Any]]:
    reference_payload = next(
        (item for item in vlm_report.get("references", []) if item.get("reference_id") == reference_id),
        {"labels": [], "warnings": []},
    )
    labels: dict[str, dict[str, Any]] = {}
    for item in reference_payload.get("labels", []):
        label = item.get("label")
        if not label:
            continue
        existing = labels.get(label)
        if existing is None or item.get("confidence", 0.0) > existing.get("confidence", 0.0):
            labels[label] = item
    return labels


def _validate_benchmark_payload_compatibility(
    *,
    preset_bundle: dict[str, Any],
    baseline_benchmark_payload: dict[str, Any],
    candidate_benchmark_payload: dict[str, Any],
) -> None:
    if baseline_benchmark_payload["eval_set_id"] != candidate_benchmark_payload["eval_set_id"]:
        raise BenchmarkComparisonError("Benchmark payloads must target the same eval_set_id.")
    if set(baseline_benchmark_payload["aggregate_metrics"]) != set(candidate_benchmark_payload["aggregate_metrics"]):
        raise BenchmarkComparisonError("Benchmark payloads must expose the same aggregate metrics.")
    if candidate_benchmark_payload.get("prompt_version") != preset_bundle["recommended_prompt_version"]:
        raise BenchmarkComparisonError("Candidate benchmark prompt_version must match the preset bundle recommendation.")
    if candidate_benchmark_payload.get("scoring_policy_version") != preset_bundle["recommended_scoring_policy_version"]:
        raise BenchmarkComparisonError(
            "Candidate benchmark scoring_policy_version must match the preset bundle recommendation."
        )


def _safe_ffmpeg_probe(
    func: Any,
    *,
    warning_code: str,
    warning_message: str,
) -> tuple[list[dict[str, float]], dict[str, Any] | None]:
    try:
        return func(), None
    except Exception:
        return [], {"code": warning_code, "message": warning_message}


def _safe_scene_change_probe(
    *,
    video_path: Path,
    ffmpeg_bin: str,
    ffprobe_payload: dict[str, Any],
) -> tuple[list[int], dict[str, Any] | None]:
    try:
        return run_ffmpeg_scene_changes(video_path=video_path, ffmpeg_bin=ffmpeg_bin), None
    except Exception:
        fallback_timestamps: list[int] = []
        for frame in ffprobe_payload.get("frames", []):
            if int(frame.get("key_frame", 0) or 0) != 1:
                continue
            raw_timestamp = frame.get("best_effort_timestamp_time")
            if raw_timestamp is None:
                continue
            try:
                fallback_timestamps.append(int(round(float(raw_timestamp) * 1000)))
            except (TypeError, ValueError):
                continue
        fallback_timestamps = sorted({timestamp for timestamp in fallback_timestamps if timestamp > 0})
        return fallback_timestamps, {
            "code": "scenechange_fallback",
            "message": "scenechange probe failed and was downgraded to keyframe-based boundaries.",
        }


def _vlm_reference_warnings(vlm_report: dict[str, Any], reference_id: str) -> list[dict[str, Any]]:
    reference_payload = next(
        (item for item in vlm_report.get("references", []) if item.get("reference_id") == reference_id),
        {"warnings": []},
    )
    return list(reference_payload.get("warnings", []))


def _build_report_warnings(
    *,
    requested_ocr_provider: str,
    resolved_ocr_provider: str,
    requested_vlm_provider: str,
    resolved_vlm_provider: str,
    vlm_model: str | None,
    vlm_report: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if requested_ocr_provider != "disabled" and resolved_ocr_provider == "disabled":
        warnings.append(
            {
                "code": "ocr_provider_downgraded",
                "message": f"OCR provider '{requested_ocr_provider}' was unavailable and the run downgraded to disabled OCR.",
            }
        )
    if resolved_vlm_provider == "disabled":
        if requested_vlm_provider == "disabled":
            warnings.append(
                {
                    "code": "vlm_provider_disabled",
                    "message": "Sampled-frame VLM analysis was disabled for this run.",
                }
            )
        else:
            warnings.append(
                {
                    "code": "vlm_provider_disabled",
                    "message": f"Requested VLM provider '{requested_vlm_provider}:{vlm_model}' could not be activated; the run continued with VLM disabled.",
                }
            )
    for reference in vlm_report.get("references", []):
        for warning in reference.get("warnings", []):
            if warning.get("code") == "vlm_parse_failed":
                warnings.append(dict(warning))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for warning in warnings:
        key = (str(warning.get("code")), str(warning.get("message")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(warning)
    return deduped


class _frame_root_context:
    def __init__(self, *, output_dir: Path | None, should_materialize: bool) -> None:
        self._output_dir = output_dir
        self._should_materialize = should_materialize
        self._tempdir: tempfile.TemporaryDirectory[str] | None = None
        self.path: Path | None = None

    def __enter__(self) -> Path | None:
        if not self._should_materialize:
            return None
        if self._output_dir is not None:
            self.path = self._output_dir / "frames"
            self.path.mkdir(parents=True, exist_ok=True)
            return self.path
        self._tempdir = tempfile.TemporaryDirectory(prefix="refintel-frames-")
        self.path = Path(self._tempdir.name) / "frames"
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._tempdir is not None:
            self._tempdir.cleanup()


if __name__ == "__main__":
    main()
