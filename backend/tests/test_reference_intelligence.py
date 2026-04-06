import csv
import json
from pathlib import Path
import sys

import pytest

from flow_helpers import build_test_video_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

import experiments.autoresearch.reference_intelligence as reference_intelligence_module  # noqa: E402
from experiments.autoresearch.ocr import DisabledOcrProvider, StaticOcrProvider  # noqa: E402
from experiments.autoresearch.reference_intelligence import (  # noqa: E402
    BenchmarkComparisonError,
    ReferenceManifestError,
    analyze_reference_collection,
    build_comparison_report,
    load_reference_manifest,
    synthesize_preset_bundle,
    write_reference_outputs,
)


def build_reference_collection(tmp_path: Path) -> Path:
    collection_dir = tmp_path / "references" / "canonical-pack"
    videos_dir = collection_dir / "videos"
    videos_dir.mkdir(parents=True)
    (collection_dir / "captions").mkdir()
    (collection_dir / "transcripts").mkdir()

    video_bytes = build_test_video_bytes()
    (videos_dir / "short-01.mp4").write_bytes(video_bytes)
    (videos_dir / "short-02.mp4").write_bytes(video_bytes)

    (collection_dir / "captions" / "short-01.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,500\nStop doing this.\n\n2\n00:00:01,500 --> 00:00:03,000\nFix your hook fast.\n",
        encoding="utf-8",
    )
    (collection_dir / "transcripts" / "short-01.txt").write_text(
        "Stop doing this if you want better retention. Fix your hook fast and keep the payoff in the first three seconds.",
        encoding="utf-8",
    )
    (collection_dir / "transcripts" / "short-02.txt").write_text(
        "\u041a\u043e\u0440\u043e\u0442\u043a\u0438\u0439 \u0440\u0430\u0437\u0431\u043e\u0440 \u043d\u043e\u0432\u043e\u0441\u0442\u0438 \u0441 \u0431\u044b\u0441\u0442\u0440\u044b\u043c \u0445\u0443\u043a\u043e\u043c \u0438 \u0447\u0435\u0442\u043a\u0438\u043c \u0432\u044b\u0432\u043e\u0434\u043e\u043c.",
        encoding="utf-8",
    )

    manifest = {
        "references": [
            {
                "reference_id": "ref-001",
                "file_name": "short-01.mp4",
                "channel_or_source": "Creator Alpha",
                "theme": "growth",
                "language": "en",
                "subtitle_file": "captions/short-01.srt",
                "transcript_file": "transcripts/short-01.txt",
                "hook_text": "Stop doing this.",
                "cta_text": "Subscribe for more.",
                "notes": "overlay punch zoom b-roll",
            },
            {
                "reference_id": "ref-002",
                "file_name": "short-02.mp4",
                "channel_or_source": "Creator Beta",
                "theme": "news",
                "language": "ru",
                "transcript_file": "transcripts/short-02.txt",
                "style_family": "daily-news",
                "notes": "fast edit overlay animation",
            },
        ]
    }
    (collection_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return collection_dir


def write_csv_manifest(collection_dir: Path, records: list[dict[str, object]]) -> None:
    fieldnames = [
        "reference_id",
        "file_name",
        "channel_or_source",
        "theme",
        "language",
        "platform",
        "notes",
        "style_family",
        "why_reference",
        "subtitle_file",
        "transcript_file",
        "hook_text",
        "cta_text",
    ]
    with (collection_dir / "manifest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def test_reference_manifest_rejects_missing_files(tmp_path: Path) -> None:
    collection_dir = tmp_path / "references" / "broken-pack"
    (collection_dir / "videos").mkdir(parents=True)
    (collection_dir / "manifest.json").write_text(
        json.dumps(
            {
                "references": [
                    {
                        "reference_id": "ref-missing",
                        "file_name": "missing.mp4",
                        "channel_or_source": "Creator",
                        "theme": "growth",
                        "language": "en",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReferenceManifestError):
        load_reference_manifest(collection_dir)


def test_reference_manifest_supports_csv(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    manifest_payload = json.loads((collection_dir / "manifest.json").read_text(encoding="utf-8"))
    write_csv_manifest(collection_dir, manifest_payload["references"])
    (collection_dir / "manifest.json").unlink()

    entries = load_reference_manifest(collection_dir)

    assert [entry.reference_id for entry in entries] == ["ref-001", "ref-002"]


def test_reference_manifest_rejects_unknown_fields(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    manifest_payload = json.loads((collection_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_payload["references"][0]["mystery_field"] = "nope"
    (collection_dir / "manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ReferenceManifestError, match="unsupported fields"):
        load_reference_manifest(collection_dir)


def test_reference_manifest_rejects_duplicate_reference_id(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    manifest_payload = json.loads((collection_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_payload["references"][1]["reference_id"] = "ref-001"
    (collection_dir / "manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ReferenceManifestError, match="Duplicate reference_id"):
        load_reference_manifest(collection_dir)


def test_reference_manifest_rejects_missing_required_values(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    manifest_payload = json.loads((collection_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_payload["references"][0]["language"] = ""
    (collection_dir / "manifest.json").write_text(json.dumps(manifest_payload), encoding="utf-8")

    with pytest.raises(ReferenceManifestError, match="missing required values"):
        load_reference_manifest(collection_dir)


def test_reference_manifest_requires_videos_directory(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    for child in (collection_dir / "videos").iterdir():
        child.unlink()
    (collection_dir / "videos").rmdir()

    with pytest.raises(ReferenceManifestError, match="videos/ directory"):
        load_reference_manifest(collection_dir)


def test_reference_manifest_rejects_missing_sidecars(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    (collection_dir / "transcripts" / "short-02.txt").unlink()

    with pytest.raises(ReferenceManifestError, match="Sidecar file"):
        load_reference_manifest(collection_dir)


def test_analyze_reference_collection_builds_report_and_clusters(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)

    report = analyze_reference_collection(collection_dir)

    assert report["schema_version"] == "refintel.v2"
    assert report["source_collection"] == "canonical-pack"
    assert report["reference_count"] == 2
    assert report["manifest_lock"]["source_collection"] == "canonical-pack"
    assert len(report["manifest_lock"]["references"]) == 2
    assert report["sampling_payload"]["source_collection"] == "canonical-pack"
    assert len(report["sampling_payload"]["references"]) == 2
    assert report["ocr_report"]["provider"] == "disabled"
    assert any(warning["code"] == "vlm_provider_disabled" for warning in report["warnings"])
    languages = {item["reference"]["language"] for item in report["references"]}
    assert languages == {"en", "ru"}

    first_report = report["references"][0]
    assert first_report["technical_probe"]["duration_ms"] > 0
    assert first_report["technical_probe"]["length_bucket"] == "under_15"
    assert first_report["caption_evidence"]["subtitle_presence"] is True
    assert first_report["caption_evidence"]["subtitle_source"] == "sidecar"
    assert first_report["style_evidence"]["overlay_usage"] == "heavy"
    assert first_report["style_evidence"]["face_dominance"] is None
    assert first_report["style_evidence"]["transition_family"] is None
    assert first_report["content_evidence"]["proof_arrival_ms"] is None
    assert first_report["content_evidence"]["payoff_arrival_ms"] is None
    assert first_report["sampling"]["opening_frames"]
    assert first_report["opening_packaging"]["opening_window_ms"] == 4000
    assert first_report["opening_packaging"]["evidence"]["opening_window_ms"]["status"] == "observed"
    assert first_report["opening_packaging"]["burned_caption_present"] is None
    assert first_report["opening_packaging"]["evidence"]["burned_caption_present"]["status"] == "unknown"
    assert first_report["opening_packaging"]["proof_asset_presence"] is None
    assert first_report["opening_packaging"]["evidence"]["proof_asset_presence"]["status"] == "unknown"
    assert first_report["summary"]["format_archetype"] == "single_talking_head"
    assert isinstance(report["clusters"], dict)
    assert "daily-news" in report["clusters"]
    assert report["cluster_payload"]["clusters"]


def test_opening_ocr_contract_uses_only_opening_frames(tmp_path: Path, monkeypatch) -> None:
    collection_dir = build_reference_collection(tmp_path)

    monkeypatch.setattr(
        reference_intelligence_module,
        "build_ocr_provider",
        lambda provider_name, *, tesseract_bin="tesseract": StaticOcrProvider(
            {
                "f0": [{"text": "STOP DOING THIS", "confidence": 0.99, "bbox": [0, 160, 280, 60]}],
                "f6": [{"text": "LATE BODY TEXT", "confidence": 0.85, "bbox": [0, 40, 220, 40]}],
            }
        ),
    )

    report = analyze_reference_collection(
        collection_dir,
        output_dir=collection_dir / "outputs",
        ocr_provider_name="auto",
    )

    first_report = report["references"][0]
    opening_blocks = first_report["ocr"]["opening"]["blocks"]

    assert first_report["opening_packaging"]["burned_caption_present"] is True
    assert first_report["opening_packaging"]["headline_card_presence"] is True
    assert opening_blocks
    assert {block["frame_id"] for block in opening_blocks} == {"f0"}
    assert all(block["frame_id"] in first_report["sampling"]["opening_frames"] for block in opening_blocks)


def test_degraded_probe_and_provider_paths_emit_warnings(tmp_path: Path, monkeypatch) -> None:
    collection_dir = build_reference_collection(tmp_path)

    monkeypatch.setattr(reference_intelligence_module, "run_ffmpeg_silencedetect", lambda **_: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(reference_intelligence_module, "run_ffmpeg_blackdetect", lambda **_: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(reference_intelligence_module, "build_ocr_provider", lambda provider_name, *, tesseract_bin="tesseract": DisabledOcrProvider())

    class ParseFailureClassifier:
        provider = "openai"
        model = "gpt-test"
        available = True

        def classify_reference(self, *, sampling_map, frame_root):
            return {
                "labels": [],
                "warnings": [{"code": "vlm_parse_failed", "message": "mocked parse failure"}],
            }

    monkeypatch.setattr(
        reference_intelligence_module,
        "build_classifier",
        lambda *, provider_name, model, api_key=None: ParseFailureClassifier(),
    )

    report = analyze_reference_collection(
        collection_dir,
        output_dir=collection_dir / "outputs",
        ocr_provider_name="auto",
        vlm_provider_name="openai",
        vlm_model="gpt-test",
    )

    warning_codes = {warning["code"] for warning in report["warnings"]}
    reference_warning_codes = {warning["code"] for warning in report["references"][0]["warnings"]}

    assert "ocr_provider_downgraded" in warning_codes
    assert "vlm_parse_failed" in warning_codes
    assert {"silencedetect_fallback", "blackdetect_fallback"} <= reference_warning_codes


def test_synthesize_preset_bundle_is_deterministic_and_analysis_only(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    report = analyze_reference_collection(collection_dir)

    first_preset = synthesize_preset_bundle(
        reference_report=report,
        preset_name="canonical-news-growth",
        recommended_prompt_version="v1-style",
        recommended_scoring_policy_version="v1-style",
        ranking_weight_overrides={"hook": 0.3, "semantic": 0.25},
    )
    second_preset = synthesize_preset_bundle(
        reference_report=report,
        preset_name="canonical-news-growth",
        recommended_prompt_version="v1-style",
        recommended_scoring_policy_version="v1-style",
        ranking_weight_overrides={"hook": 0.3, "semantic": 0.25},
    )

    assert first_preset.to_dict() == second_preset.to_dict()
    assert first_preset.analysis_only is True
    assert first_preset.schema_version == "refintel.v2"
    assert first_preset.prompt_version_suggestion == "v1-style"
    assert "allowed_policy_fields" in first_preset.to_dict()
    assert "reference_ids" in first_preset.to_dict()
    assert first_preset.preset_rationale


def test_write_reference_outputs_emits_new_artifacts(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    output_dir = collection_dir / "outputs"
    report = analyze_reference_collection(collection_dir)
    preset_bundle = synthesize_preset_bundle(
        reference_report=report,
        preset_name="canonical-news-growth",
        recommended_prompt_version="v1-style",
        recommended_scoring_policy_version="v1-style",
        ranking_weight_overrides={"hook": 0.3},
    )
    comparison_report = build_comparison_report(
        preset_bundle=preset_bundle,
        baseline_benchmark_payload={
            "benchmark_run_id": "run-baseline",
            "eval_set_id": "eval-1",
            "prompt_version": "v1-style",
            "scoring_policy_version": "v1-style",
            "aggregate_metrics": {
                "accepted_coverage_top_5": 0.4,
                "accepted_coverage_top_10": 0.6,
                "rejected_intrusion_top_5": 0.3,
            },
        },
        candidate_benchmark_payload={
            "benchmark_run_id": "run-candidate",
            "eval_set_id": "eval-1",
            "prompt_version": "v1-style",
            "scoring_policy_version": "v1-style",
            "aggregate_metrics": {
                "accepted_coverage_top_5": 0.5,
                "accepted_coverage_top_10": 0.7,
                "rejected_intrusion_top_5": 0.2,
            },
        },
    )

    write_reference_outputs(
        output_dir=output_dir,
        reference_report=report,
        preset_bundle=preset_bundle,
        comparison_report=comparison_report,
    )

    expected_files = {
        "reference_manifest.lock.json",
        "reference_sampling_map.json",
        "reference_ocr_report.json",
        "reference_style_report.json",
        "reference_clusters.json",
        "preset_bundle.json",
        "comparison_report.json",
    }
    assert expected_files == {path.name for path in output_dir.iterdir()}
    style_payload = json.loads((output_dir / "reference_style_report.json").read_text(encoding="utf-8"))
    assert style_payload["schema_version"] == "refintel.v2"
    assert "opening_packaging" in style_payload["references"][0]


def test_build_comparison_report_respects_metric_direction() -> None:
    preset_bundle = synthesize_preset_bundle(
        reference_report={
            "source_collection": "canonical-pack",
            "references": [
                {
                    "reference": {"reference_id": "ref-001"},
                    "caption_evidence": {"subtitle_presence": True, "caption_style_family": "kinetic_phrase_grouped", "lower_third_bias": True},
                    "technical_probe": {"cut_density_per_minute": 10.0},
                    "style_evidence": {"broll_density": "low", "headline_card_presence": True, "silence_tightening_hint": "moderate"},
                    "content_evidence": {"cta_presence": False},
                }
            ],
        },
        preset_name="candidate-a",
        recommended_prompt_version="v1",
        recommended_scoring_policy_version="v2",
        ranking_weight_overrides={"hook": 0.3},
    )
    baseline_payload = {
        "benchmark_run_id": "run-baseline",
        "eval_set_id": "eval-1",
        "prompt_version": "v1",
        "scoring_policy_version": "v1",
        "aggregate_metrics": {
            "accepted_coverage_top_5": 0.4,
            "accepted_coverage_top_10": 0.6,
            "rejected_intrusion_top_5": 0.3,
        },
    }
    candidate_payload = {
        "benchmark_run_id": "run-candidate",
        "eval_set_id": "eval-1",
        "prompt_version": "v1",
        "scoring_policy_version": "v2",
        "aggregate_metrics": {
            "accepted_coverage_top_5": 0.5,
            "accepted_coverage_top_10": 0.7,
            "rejected_intrusion_top_5": 0.2,
        },
    }

    report = build_comparison_report(
        preset_bundle=preset_bundle,
        baseline_benchmark_payload=baseline_payload,
        candidate_benchmark_payload=candidate_payload,
    )

    assert sorted(report["improved_metrics"]) == [
        "accepted_coverage_top_10",
        "accepted_coverage_top_5",
        "rejected_intrusion_top_5",
    ]
    assert report["regressed_metrics"] == []
    assert report["eligible_surface"] == "ranking"
    assert report["promotion_state"] == "ready_for_review"
    assert report["metric_deltas"]["rejected_intrusion_top_5"]["direction"] == "lower_is_better"
    assert report["candidate"]["prompt_version"] == "v1"
    assert report["candidate"]["scoring_policy_version"] == "v2"


def test_build_comparison_report_rejects_mismatched_eval_sets(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    report = analyze_reference_collection(collection_dir)
    preset_bundle = synthesize_preset_bundle(
        reference_report=report,
        preset_name="candidate-a",
        recommended_prompt_version="v1",
        recommended_scoring_policy_version="v2",
    )

    with pytest.raises(BenchmarkComparisonError):
        build_comparison_report(
            preset_bundle=preset_bundle,
            baseline_benchmark_payload={
                "benchmark_run_id": "run-baseline",
                "eval_set_id": "eval-1",
                "aggregate_metrics": {"accepted_coverage_top_5": 0.4},
            },
            candidate_benchmark_payload={
                "benchmark_run_id": "run-candidate",
                "eval_set_id": "eval-2",
                "aggregate_metrics": {"accepted_coverage_top_5": 0.5},
            },
        )


def test_build_comparison_report_rejects_mismatched_prompt_version(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    report = analyze_reference_collection(collection_dir)
    preset_bundle = synthesize_preset_bundle(
        reference_report=report,
        preset_name="candidate-a",
        recommended_prompt_version="v1",
        recommended_scoring_policy_version="v2",
    )

    with pytest.raises(BenchmarkComparisonError, match="prompt_version"):
        build_comparison_report(
            preset_bundle=preset_bundle,
            baseline_benchmark_payload={
                "benchmark_run_id": "run-baseline",
                "eval_set_id": "eval-1",
                "prompt_version": "v0",
                "scoring_policy_version": "v0",
                "aggregate_metrics": {"accepted_coverage_top_5": 0.4},
            },
            candidate_benchmark_payload={
                "benchmark_run_id": "run-candidate",
                "eval_set_id": "eval-1",
                "prompt_version": "v2",
                "scoring_policy_version": "v2",
                "aggregate_metrics": {"accepted_coverage_top_5": 0.5},
            },
        )


def test_build_comparison_report_rejects_mismatched_scoring_policy_version(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    report = analyze_reference_collection(collection_dir)
    preset_bundle = synthesize_preset_bundle(
        reference_report=report,
        preset_name="candidate-a",
        recommended_prompt_version="v1",
        recommended_scoring_policy_version="v2",
    )

    with pytest.raises(BenchmarkComparisonError, match="scoring_policy_version"):
        build_comparison_report(
            preset_bundle=preset_bundle,
            baseline_benchmark_payload={
                "benchmark_run_id": "run-baseline",
                "eval_set_id": "eval-1",
                "prompt_version": "v1",
                "scoring_policy_version": "v0",
                "aggregate_metrics": {"accepted_coverage_top_5": 0.4},
            },
            candidate_benchmark_payload={
                "benchmark_run_id": "run-candidate",
                "eval_set_id": "eval-1",
                "prompt_version": "v1",
                "scoring_policy_version": "v3",
                "aggregate_metrics": {"accepted_coverage_top_5": 0.5},
            },
        )


def test_render_only_preset_stays_blocked_pre_m3(tmp_path: Path) -> None:
    collection_dir = build_reference_collection(tmp_path)
    report = analyze_reference_collection(collection_dir)
    preset_bundle = synthesize_preset_bundle(
        reference_report=report,
        preset_name="render-only",
        recommended_prompt_version="v1",
        recommended_scoring_policy_version="preset-render",
    )

    comparison = build_comparison_report(
        preset_bundle=preset_bundle,
        baseline_benchmark_payload={
            "benchmark_run_id": "run-baseline",
            "eval_set_id": "eval-1",
            "prompt_version": "v1",
            "scoring_policy_version": "v1",
            "aggregate_metrics": {
                "accepted_coverage_top_5": 0.4,
                "accepted_coverage_top_10": 0.6,
                "rejected_intrusion_top_5": 0.3,
            },
        },
        candidate_benchmark_payload={
            "benchmark_run_id": "run-candidate",
            "eval_set_id": "eval-1",
            "prompt_version": "v1",
            "scoring_policy_version": "preset-render",
            "aggregate_metrics": {
                "accepted_coverage_top_5": 0.45,
                "accepted_coverage_top_10": 0.62,
                "rejected_intrusion_top_5": 0.28,
            },
        },
    )

    assert comparison["eligible_surface"] == "render"
    assert comparison["promotion_state"] == "blocked_pre_m3"
