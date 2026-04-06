from __future__ import annotations

from collections import Counter
from typing import Any

from experiments.autoresearch.taxonomy import (
    SCHEMA_VERSION,
    caption_style_family,
    cta_family,
    cut_density_band,
    format_archetype,
    hook_family,
    narrative_packaging_shape,
    opening_frame_mode,
    overlay_family,
    pattern_interrupt_types,
    ratio,
    silence_trim_level,
    sticky_factors,
)


BENCHMARK_LOWER_IS_BETTER = {"rejected_intrusion_top_5"}


def build_caption_evidence_v2(
    *,
    entry: Any,
    subtitle_lines: list[str],
    technical_probe: dict[str, Any],
    ocr_summary: dict[str, Any],
) -> dict[str, Any]:
    line_count = len(subtitle_lines)
    words_per_line = [len(line.split()) for line in subtitle_lines if line.strip()]
    subtitle_presence = bool(line_count or technical_probe.get("subtitle_stream_count") or ocr_summary.get("burned_caption_present"))
    if entry.subtitle_file:
        subtitle_source = "sidecar"
    elif technical_probe.get("subtitle_stream_count", 0) > 0:
        subtitle_source = "embedded"
    elif ocr_summary.get("burned_caption_present"):
        subtitle_source = "burned"
    else:
        subtitle_source = "none"
    emphasis_patterns = set(ocr_summary.get("emphasis_patterns", []))
    emoji_usage = "emoji" in emphasis_patterns
    all_caps_bias = "all_caps" in emphasis_patterns
    caption_density = round(line_count / max(technical_probe.get("duration_ms", 0) / 1000.0, 1.0), 4)
    phrase_grouping = "phrase_grouped" if line_count and (sum(words_per_line) / max(line_count, 1)) <= 7 else "sentence_grouped"
    highlight_words = bool(all_caps_bias or "punctuation_emphasis" in emphasis_patterns)
    style_family = caption_style_family(
        subtitle_source=subtitle_source,
        emphasis_patterns=emphasis_patterns,
        text_occupancy_band=ocr_summary.get("text_occupancy_band", "none"),
    )
    return {
        "subtitle_presence": subtitle_presence,
        "subtitle_source": subtitle_source,
        "line_count": line_count,
        "average_words_per_line": round(sum(words_per_line) / max(line_count, 1), 4) if line_count else 0.0,
        "avg_words_per_caption": round(sum(words_per_line) / max(line_count, 1), 4) if line_count else 0.0,
        "max_words_per_line": max(words_per_line, default=0),
        "lower_third_bias": ocr_summary.get("safe_zone_bias") == "lower_third",
        "safe_zone_bias": ocr_summary.get("safe_zone_bias", "unknown"),
        "emphasis_patterns": sorted(emphasis_patterns),
        "caption_density": caption_density,
        "phrase_grouping": phrase_grouping,
        "highlight_words": highlight_words,
        "emoji_usage": emoji_usage,
        "all_caps_bias": all_caps_bias,
        "caption_style_family": style_family,
        "burned_caption_present": bool(ocr_summary.get("burned_caption_present")),
    }


def build_style_evidence_v2(
    *,
    entry: Any,
    technical_probe: dict[str, Any],
    caption_evidence: dict[str, Any],
    ocr_summary: dict[str, Any],
    transcript_lead: str | None,
    vlm_labels: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    hook_family_value = hook_family(
        hook_text=entry.hook_text,
        transcript_lead=transcript_lead,
        notes=entry.notes,
    )
    overlay_family_value = overlay_family(
        notes=entry.notes,
        subtitle_source=caption_evidence["subtitle_source"],
        headline_card_presence=bool(ocr_summary.get("headline_card_presence")),
        burned_caption_present=bool(ocr_summary.get("burned_caption_present")),
    )
    opening_mode = opening_frame_mode(
        notes=entry.notes,
        burned_caption_present=bool(ocr_summary.get("burned_caption_present")),
        text_occupancy_band=ocr_summary.get("text_occupancy_band", "none"),
        proof_asset_presence=bool(_pick_vlm_value(vlm_labels, "proof_asset_presence")),
    )
    pattern_interrupts = pattern_interrupt_types(
        notes=entry.notes,
        cut_density_per_minute=technical_probe.get("cut_density_per_minute", 0.0),
        headline_card_presence=bool(ocr_summary.get("headline_card_presence")),
    )
    if not pattern_interrupts:
        pattern_interrupts = _pick_vlm_value(vlm_labels, "pattern_interrupt_types") or []
    if isinstance(pattern_interrupts, str):
        pattern_interrupts = [pattern_interrupts]
    effect_density_value = cut_density_band(technical_probe.get("cut_density_per_minute", 0.0))
    proof_asset_presence = _pick_vlm_value(vlm_labels, "proof_asset_presence")
    note_tokens = (entry.notes or "").lower()
    broll_density = "high" if any(token in note_tokens for token in ("b-roll", "broll", "insert", "footage")) else "low"
    punch_in = "high" if "zoom" in note_tokens or technical_probe.get("cut_density_per_minute", 0.0) >= 24 else "medium"
    zoom_crop = "dynamic_reframe" if technical_probe.get("cut_density_per_minute", 0.0) >= 18 else "speaker_lock"
    return {
        "hook_text_present": bool(entry.hook_text or transcript_lead),
        "hook_text": entry.hook_text or transcript_lead,
        "hook_family": hook_family_value,
        "cta_text": entry.cta_text,
        "overlay_usage": "heavy" if overlay_family_value != "minimal" else "light",
        "overlay_family": overlay_family_value,
        "opening_frame_mode": opening_mode,
        "headline_card_presence": bool(ocr_summary.get("headline_card_presence")),
        "proof_asset_presence": proof_asset_presence if isinstance(proof_asset_presence, bool) else None,
        "screen_text_card_presence": bool(ocr_summary.get("headline_card_presence")),
        "face_dominance": None,
        "text_occupancy_band": ocr_summary.get("text_occupancy_band", "none"),
        "punch_in_frequency": punch_in,
        "zoom_crop_behavior": zoom_crop,
        "crop_reframe_behavior": zoom_crop,
        "broll_density": broll_density,
        "insert_density": "medium" if broll_density == "high" else "low",
        "insert_types": _pick_vlm_value(vlm_labels, "insert_types"),
        "insert_trigger": "explanation" if broll_density == "high" else "none",
        "effect_density": effect_density_value,
        "pattern_interrupt_types": pattern_interrupts,
        "shot_change_family": cut_density_band(technical_probe.get("cut_density_per_minute", 0.0)),
        "transition_family": None,
        "edit_aggressiveness": "high" if technical_probe.get("cut_density_per_minute", 0.0) >= 24 else "medium",
        "silence_tightening_hint": silence_trim_level(
            technical_probe.get("silence_ratio", 0.0),
            technical_probe.get("cut_density_per_minute", 0.0),
        ),
    }


def build_content_evidence_v2(
    *,
    entry: Any,
    technical_probe: dict[str, Any],
    transcript_text: str | None,
    style_evidence: dict[str, Any],
    vlm_labels: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    format_archetype_value = _pick_vlm_value(vlm_labels, "format_archetype") or format_archetype(
        notes=entry.notes,
        transcript_text=transcript_text,
        style_family=entry.style_family,
    )
    cta_family_value = cta_family(entry.cta_text)
    narrative_shape = narrative_packaging_shape(
        format_archetype_value=format_archetype_value,
        hook_family_value=style_evidence["hook_family"],
        cta_family_value=cta_family_value,
    )
    return {
        "topic": entry.theme,
        "format_type": entry.style_family or format_archetype_value,
        "format_archetype": format_archetype_value,
        "payoff_pattern": "fast" if technical_probe.get("duration_ms", 0) <= 25_000 else "developing",
        "payoff_shape": "fast_payoff" if technical_probe.get("opening_cut_count", 0) >= 1 else "delayed_payoff",
        "cta_pattern": "explicit" if entry.cta_text else "implicit",
        "cta_family": cta_family_value,
        "cta_presence": bool(entry.cta_text),
        "cta_position": "end" if entry.cta_text else "none",
        "end_card_presence": bool(entry.cta_text),
        "loop_ending": False,
        "narrative_arc": narrative_shape,
        "narrative_packaging_shape": narrative_shape,
        "self_containment": "high",
        "explanation_cadence": "rapid" if technical_probe.get("cut_density_per_minute", 0.0) >= 18 else "steady",
        "promise_clarity": "clear" if style_evidence["hook_family"] != "unknown" else "unclear",
        "proof_arrival_ms": None,
        "payoff_arrival_ms": None,
        "opening_confusion_risk": "low" if style_evidence["hook_family"] != "unknown" else "medium",
    }


def build_opening_packaging_v2(
    *,
    entry: Any,
    technical_probe: dict[str, Any],
    caption_evidence: dict[str, Any],
    opening_timing: dict[str, Any],
    opening_ocr_summary: dict[str, Any],
    transcript_lead: str | None,
    vlm_labels: dict[str, dict[str, Any]],
    sampling_map: dict[str, Any],
) -> dict[str, Any]:
    opening_frames = sampling_map.get("zones", {}).get("opening_frames", [])
    ocr_available = opening_ocr_summary.get("provider") not in {None, "disabled"}
    opening_text = entry.hook_text or transcript_lead
    opening_text_source = "manifest" if entry.hook_text else ("sidecar" if transcript_lead else "local")
    proof_asset_from_vlm = _pick_vlm_value(vlm_labels, "proof_asset_presence")
    proof_asset_value = proof_asset_from_vlm if isinstance(proof_asset_from_vlm, bool) else None

    hook_family_value = hook_family(
        hook_text=entry.hook_text,
        transcript_lead=transcript_lead,
        notes=entry.notes,
    )
    overlay_family_value = overlay_family(
        notes=entry.notes,
        subtitle_source=caption_evidence["subtitle_source"],
        headline_card_presence=bool(opening_ocr_summary.get("headline_card_presence")),
        burned_caption_present=bool(opening_ocr_summary.get("burned_caption_present")),
    )
    opening_frame_mode_value = opening_frame_mode(
        notes=entry.notes,
        burned_caption_present=bool(opening_ocr_summary.get("burned_caption_present")),
        text_occupancy_band=opening_ocr_summary.get("text_occupancy_band", "none"),
        proof_asset_presence=bool(proof_asset_value),
    )
    local_sticky_factors = sticky_factors(
        hook_family_value=hook_family_value,
        headline_card_presence=bool(opening_ocr_summary.get("headline_card_presence")),
        burned_caption_present=bool(opening_ocr_summary.get("burned_caption_present")),
        proof_asset_presence=bool(proof_asset_value),
        cut_density_per_minute=technical_probe.get("cut_density_per_minute", 0.0),
    )
    sticky_from_vlm = _normalize_list(_pick_vlm_value(vlm_labels, "sticky_factors"))

    format_local_value = None
    format_local_source = "local"
    if entry.style_family:
        format_local_value = format_archetype(
            notes=entry.notes,
            transcript_text=entry.style_family,
            style_family=entry.style_family,
        )
        format_local_source = "manifest"

    packaging = {
        "opening_window_ms": opening_timing["opening_window_ms"],
        "opening_cut_count": technical_probe.get("opening_cut_count", 0),
        "opening_silence_ms": opening_timing["opening_silence_ms"],
        "opening_black_ms": opening_timing["opening_black_ms"],
        "burned_caption_present": None,
        "headline_card_presence": None,
        "text_occupancy_band": None,
        "safe_zone_bias": None,
        "hook_family": None,
        "opening_frame_mode": None,
        "overlay_family": None,
        "sticky_factors": None,
        "insert_types": None,
        "proof_asset_presence": None,
        "format_archetype": None,
        "evidence": {},
    }

    packaging["evidence"]["opening_window_ms"] = _evidence_record(
        value=opening_timing["opening_window_ms"],
        status="observed",
        source="local",
        confidence=1.0,
        evidence_refs=opening_frames[:1],
    )
    packaging["evidence"]["opening_cut_count"] = _evidence_record(
        value=technical_probe.get("opening_cut_count", 0),
        status="observed",
        source="local",
        confidence=1.0,
        evidence_refs=opening_frames[:2],
    )
    packaging["evidence"]["opening_silence_ms"] = _evidence_record(
        value=opening_timing["opening_silence_ms"],
        status="observed",
        source="local",
        confidence=1.0,
        evidence_refs=[],
    )
    packaging["evidence"]["opening_black_ms"] = _evidence_record(
        value=opening_timing["opening_black_ms"],
        status="observed",
        source="local",
        confidence=1.0,
        evidence_refs=[],
    )
    packaging["burned_caption_present"], packaging["evidence"]["burned_caption_present"] = _resolve_opening_signal(
        local_value=bool(opening_ocr_summary.get("burned_caption_present")) if ocr_available else None,
        local_status="observed" if ocr_available else "unknown",
        local_source="ocr",
        local_confidence=0.95 if ocr_available else 0.0,
        local_refs=[block["frame_id"] for block in opening_ocr_summary.get("blocks", [])[:3]],
    )
    packaging["headline_card_presence"], packaging["evidence"]["headline_card_presence"] = _resolve_opening_signal(
        local_value=bool(opening_ocr_summary.get("headline_card_presence")) if ocr_available else None,
        local_status="observed" if ocr_available else "unknown",
        local_source="ocr",
        local_confidence=0.9 if ocr_available else 0.0,
        local_refs=[block["frame_id"] for block in opening_ocr_summary.get("blocks", [])[:3]],
    )
    packaging["text_occupancy_band"], packaging["evidence"]["text_occupancy_band"] = _resolve_opening_signal(
        local_value=opening_ocr_summary.get("text_occupancy_band") if ocr_available else None,
        local_status="observed" if ocr_available else "unknown",
        local_source="ocr",
        local_confidence=0.9 if ocr_available else 0.0,
        local_refs=[block["frame_id"] for block in opening_ocr_summary.get("blocks", [])[:3]],
    )
    packaging["safe_zone_bias"], packaging["evidence"]["safe_zone_bias"] = _resolve_opening_signal(
        local_value=opening_ocr_summary.get("safe_zone_bias") if ocr_available else None,
        local_status="observed" if ocr_available else "unknown",
        local_source="ocr",
        local_confidence=0.9 if ocr_available else 0.0,
        local_refs=[block["frame_id"] for block in opening_ocr_summary.get("blocks", [])[:3]],
    )
    packaging["hook_family"], packaging["evidence"]["hook_family"] = _resolve_opening_signal(
        local_value=hook_family_value if opening_text else None,
        local_status="inferred" if opening_text else "unknown",
        local_source=opening_text_source,
        local_confidence=0.85 if entry.hook_text else (0.75 if transcript_lead else 0.0),
        local_refs=opening_frames[:2],
        vlm_value=_pick_vlm_value(vlm_labels, "hook_family"),
        vlm_item=vlm_labels.get("hook_family"),
    )
    packaging["opening_frame_mode"], packaging["evidence"]["opening_frame_mode"] = _resolve_opening_signal(
        local_value=opening_frame_mode_value,
        local_status="inferred",
        local_source="local",
        local_confidence=0.7,
        local_refs=opening_frames[:2],
        vlm_value=_pick_vlm_value(vlm_labels, "opening_frame_mode"),
        vlm_item=vlm_labels.get("opening_frame_mode"),
    )
    packaging["overlay_family"], packaging["evidence"]["overlay_family"] = _resolve_opening_signal(
        local_value=overlay_family_value,
        local_status="inferred",
        local_source="local",
        local_confidence=0.8,
        local_refs=opening_frames[:2],
        vlm_value=_pick_vlm_value(vlm_labels, "overlay_family"),
        vlm_item=vlm_labels.get("overlay_family"),
    )
    packaging["sticky_factors"], packaging["evidence"]["sticky_factors"] = _resolve_opening_signal(
        local_value=local_sticky_factors or None,
        local_status="inferred" if local_sticky_factors else "unknown",
        local_source="local",
        local_confidence=0.65 if local_sticky_factors else 0.0,
        local_refs=opening_frames[:3],
        vlm_value=sticky_from_vlm or None,
        vlm_item=vlm_labels.get("sticky_factors"),
    )
    packaging["insert_types"], packaging["evidence"]["insert_types"] = _resolve_opening_signal(
        local_value=None,
        local_status="unknown",
        local_source="local",
        local_confidence=0.0,
        local_refs=[],
        vlm_value=_normalize_list(_pick_vlm_value(vlm_labels, "insert_types")) or None,
        vlm_item=vlm_labels.get("insert_types"),
    )
    packaging["proof_asset_presence"], packaging["evidence"]["proof_asset_presence"] = _resolve_opening_signal(
        local_value=None,
        local_status="unknown",
        local_source="local",
        local_confidence=0.0,
        local_refs=[],
        vlm_value=proof_asset_value,
        vlm_item=vlm_labels.get("proof_asset_presence"),
    )
    packaging["format_archetype"], packaging["evidence"]["format_archetype"] = _resolve_opening_signal(
        local_value=format_local_value,
        local_status="inferred" if format_local_value else "unknown",
        local_source=format_local_source,
        local_confidence=0.8 if format_local_value else 0.0,
        local_refs=opening_frames[:1],
        vlm_value=_pick_vlm_value(vlm_labels, "format_archetype"),
        vlm_item=vlm_labels.get("format_archetype"),
    )
    return packaging


def build_reference_evidence_items(
    *,
    technical_probe: dict[str, Any],
    caption_evidence: dict[str, Any],
    style_evidence: dict[str, Any],
    content_evidence: dict[str, Any],
    ocr_summary: dict[str, Any],
    vlm_labels: dict[str, dict[str, Any]],
    sampling_map: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    opening_frames = sampling_map.get("zones", {}).get("opening_frames", [])
    if caption_evidence["subtitle_source"] != "none":
        evidence.append(
            {
                "label": "subtitle_source",
                "value": caption_evidence["subtitle_source"],
                "confidence": 1.0,
                "source": "subtitle",
                "why": "Derived from manifest sidecars or embedded subtitle streams.",
                "evidence_refs": opening_frames[:1],
            }
        )
    if ocr_summary.get("burned_caption_present"):
        evidence.append(
            {
                "label": "burned_caption_present",
                "value": True,
                "confidence": 0.9,
                "source": "ocr",
                "why": "OCR found readable text on sampled frames.",
                "evidence_refs": [block["frame_id"] for block in ocr_summary.get("blocks", [])[:3]],
            }
        )
    evidence.extend(
        [
            {
                "label": "hook_family",
                "value": style_evidence["hook_family"],
                "confidence": 0.75,
                "source": "local",
                "why": "Derived from hook text, transcript lead, and packaging heuristics.",
                "evidence_refs": opening_frames[:2],
            },
            {
                "label": "format_archetype",
                "value": content_evidence["format_archetype"],
                "confidence": 0.7,
                "source": "local",
                "why": "Derived from manifest notes, transcript cues, and style family.",
                "evidence_refs": opening_frames[:1],
            },
        ]
    )
    for label_name, item in sorted(vlm_labels.items()):
        evidence.append(
            {
                "label": label_name,
                "value": item.get("value"),
                "confidence": item.get("confidence", 0.0),
                "source": item.get("source", "vlm"),
                "why": item.get("why", ""),
                "evidence_refs": item.get("evidence_frame_ids", []),
            }
        )
    return evidence


def build_cluster_payload(reference_report: dict[str, Any]) -> dict[str, Any]:
    cluster_map: dict[str, list[str]] = {}
    for reference in reference_report.get("references", []):
        cluster_key = reference["reference"].get("style_family") or reference["content_evidence"]["format_type"]
        cluster_map.setdefault(cluster_key, []).append(reference["reference"]["reference_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "source_collection": reference_report["source_collection"],
        "clusters": [
            {
                "cluster_id": cluster_id,
                "reference_ids": sorted(reference_ids),
                "centroid_tags": _centroid_tags(reference_report=reference_report, reference_ids=reference_ids),
            }
            for cluster_id, reference_ids in sorted(cluster_map.items())
        ],
    }


def synthesize_preset_bundle_v2(
    *,
    reference_report: dict[str, Any],
    preset_name: str,
    recommended_prompt_version: str,
    recommended_scoring_policy_version: str,
    ranking_weight_overrides: dict[str, float] | None = None,
) -> dict[str, Any]:
    references = reference_report["references"]
    reference_ids = [item["reference"]["reference_id"] for item in references]
    caption_ratio = ratio(sum(1 for item in references if item["caption_evidence"]["subtitle_presence"]), len(references))
    fast_cut_ratio = ratio(
        sum(1 for item in references if item["technical_probe"]["cut_density_per_minute"] >= 18.0),
        len(references),
    )
    broll_ratio = ratio(
        sum(1 for item in references if item["style_evidence"]["broll_density"] == "high"),
        len(references),
    )
    caption_style = _majority_value(
        [item["caption_evidence"]["caption_style_family"] for item in references],
        default="minimal_phrase_grouped",
    )
    crop_mode = "dynamic_reframe" if fast_cut_ratio >= 0.4 else "speaker_lock"
    silence_level = _majority_value(
        [item["style_evidence"]["silence_tightening_hint"] for item in references],
        default="moderate",
    )
    overlay_policy = {
        "headline_required": caption_ratio >= 0.5 or any(item["style_evidence"]["headline_card_presence"] for item in references),
        "lower_third_bias": any(item["caption_evidence"]["lower_third_bias"] for item in references),
        "allow_cta_card": any(item["content_evidence"]["cta_presence"] for item in references),
    }
    rationale = [
        f"{int(round(caption_ratio * 100))}% of references use visible subtitle packaging.",
        f"{int(round(fast_cut_ratio * 100))}% of references show elevated cut density.",
        f"{int(round(broll_ratio * 100))}% of references use explanatory inserts or B-roll.",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "preset_name": preset_name,
        "source_collection": reference_report["source_collection"],
        "reference_ids": reference_ids,
        "recommended_prompt_version": recommended_prompt_version,
        "recommended_scoring_policy_version": recommended_scoring_policy_version,
        "prompt_version_suggestion": recommended_prompt_version,
        "ranking_weight_overrides": ranking_weight_overrides or {},
        "caption_style": caption_style,
        "crop_mode": crop_mode,
        "silence_trim_level": silence_level,
        "broll_mode": "assist_comprehension_only" if broll_ratio >= 0.25 else "off",
        "overlay_policy": overlay_policy,
        "hook_packaging_rules": {
            "opening_window_ms": 3000,
            "target_hook_caption_words": 8,
            "prefer_immediate_payoff": True,
            "proof_before_ms": 2500,
        },
        "preset_rationale": rationale,
        "analysis_only": True,
        "allowed_policy_fields": sorted(
            [
                "caption_style",
                "crop_mode",
                "silence_trim_level",
                "broll_mode",
                "overlay_policy",
                "hook_packaging_rules",
                "ranking_weight_overrides",
            ]
        ),
    }


def build_comparison_report_v2(
    *,
    preset_bundle: dict[str, Any],
    baseline_benchmark_payload: dict[str, Any],
    candidate_benchmark_payload: dict[str, Any],
) -> dict[str, Any]:
    baseline_metrics = baseline_benchmark_payload["aggregate_metrics"]
    candidate_metrics = candidate_benchmark_payload["aggregate_metrics"]
    metric_deltas: dict[str, Any] = {}
    improved_metrics: list[str] = []
    regressed_metrics: list[str] = []
    for metric_name in sorted(baseline_metrics):
        delta = round(candidate_metrics[metric_name] - baseline_metrics[metric_name], 4)
        direction = "lower_is_better" if metric_name in BENCHMARK_LOWER_IS_BETTER else "higher_is_better"
        metric_deltas[metric_name] = {
            "delta": delta,
            "direction": direction,
            "baseline": baseline_metrics[metric_name],
            "candidate": candidate_metrics[metric_name],
        }
        if direction == "lower_is_better":
            if delta < 0:
                improved_metrics.append(metric_name)
            elif delta > 0:
                regressed_metrics.append(metric_name)
        else:
            if delta > 0:
                improved_metrics.append(metric_name)
            elif delta < 0:
                regressed_metrics.append(metric_name)
    ranking_enabled = bool(preset_bundle.get("ranking_weight_overrides"))
    promotion_state = "blocked_pre_m3"
    if ranking_enabled:
        promotion_state = "ready_for_review" if not regressed_metrics else "rejected"
    return {
        "schema_version": SCHEMA_VERSION,
        "preset_name": preset_bundle["preset_name"],
        "source_collection": preset_bundle["source_collection"],
        "recommended_prompt_version": preset_bundle["recommended_prompt_version"],
        "recommended_scoring_policy_version": preset_bundle["recommended_scoring_policy_version"],
        "reference_ids": preset_bundle["reference_ids"],
        "baseline_benchmark_run_id": baseline_benchmark_payload["benchmark_run_id"],
        "candidate_benchmark_run_id": candidate_benchmark_payload["benchmark_run_id"],
        "eval_set_id": baseline_benchmark_payload["eval_set_id"],
        "eligible_surface": "ranking" if ranking_enabled else "render",
        "promotion_state": promotion_state,
        "baseline_aggregate_metrics": baseline_metrics,
        "candidate_aggregate_metrics": candidate_metrics,
        "baseline": {
            "eval_set_id": baseline_benchmark_payload["eval_set_id"],
            "prompt_version": baseline_benchmark_payload.get("prompt_version"),
            "scoring_policy_version": baseline_benchmark_payload.get("scoring_policy_version"),
        },
        "candidate": {
            "prompt_version": candidate_benchmark_payload.get("prompt_version"),
            "scoring_policy_version": candidate_benchmark_payload.get("scoring_policy_version"),
        },
        "metric_deltas": metric_deltas,
        "improved_metrics": sorted(improved_metrics),
        "regressed_metrics": sorted(regressed_metrics),
        "allowed_policy_fields": preset_bundle["allowed_policy_fields"],
        "analysis_only": True,
        "required_human_actions": ["review_bundle", "approve_enablement"],
    }


def build_summary_payload(
    *,
    style_evidence: dict[str, Any],
    content_evidence: dict[str, Any],
    ocr_summary: dict[str, Any],
    technical_probe: dict[str, Any],
    vlm_labels: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sticky = _pick_vlm_value(vlm_labels, "sticky_factors")
    if isinstance(sticky, str):
        sticky = [sticky]
    if not sticky:
        sticky = sticky_factors(
            hook_family_value=style_evidence["hook_family"],
            headline_card_presence=style_evidence["headline_card_presence"],
            burned_caption_present=ocr_summary.get("burned_caption_present", False),
            proof_asset_presence=bool(style_evidence["proof_asset_presence"]),
            cut_density_per_minute=technical_probe.get("cut_density_per_minute", 0.0),
        )
    return {
        "format_archetype": content_evidence["format_archetype"],
        "sticky_factors": sticky,
    }


def _centroid_tags(*, reference_report: dict[str, Any], reference_ids: list[str]) -> list[str]:
    tags: Counter[str] = Counter()
    for reference in reference_report.get("references", []):
        if reference["reference"]["reference_id"] not in reference_ids:
            continue
        for tag in (
            reference["style_evidence"]["opening_frame_mode"],
            reference["caption_evidence"]["caption_style_family"],
            reference["content_evidence"]["payoff_shape"],
        ):
            if tag:
                tags[tag] += 1
    return [tag for tag, _ in tags.most_common(3)]


def _majority_value(values: list[str], *, default: str) -> str:
    values = [value for value in values if value]
    if not values:
        return default
    return Counter(values).most_common(1)[0][0]


def _pick_vlm_value(vlm_labels: dict[str, dict[str, Any]], label: str) -> Any:
    item = vlm_labels.get(label)
    if not item:
        return None
    return item.get("value")


def _resolve_opening_signal(
    *,
    local_value: Any,
    local_status: str,
    local_source: str,
    local_confidence: float,
    local_refs: list[str],
    vlm_value: Any = None,
    vlm_item: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    normalized_local = _normalized_signal_value(local_value)
    normalized_vlm = _normalized_signal_value(vlm_value)
    if normalized_local is None and normalized_vlm is None:
        return None, _evidence_record(
            value=None,
            status="unknown",
            source=local_source,
            confidence=0.0,
            evidence_refs=list(local_refs),
        )
    if normalized_local is None and normalized_vlm is not None:
        return vlm_value, _evidence_record(
            value=vlm_value,
            status="observed" if (vlm_item or {}).get("confidence", 0.0) >= 0.75 else "inferred",
            source="vlm",
            confidence=float((vlm_item or {}).get("confidence", 0.0) or 0.0),
            evidence_refs=[str(frame_id) for frame_id in (vlm_item or {}).get("evidence_frame_ids", [])],
        )
    status = local_status
    evidence_refs = list(local_refs)
    confidence = local_confidence
    if normalized_vlm is not None:
        evidence_refs.extend(str(frame_id) for frame_id in (vlm_item or {}).get("evidence_frame_ids", []))
        if normalized_vlm != normalized_local:
            status = "conflicted"
        elif status == "unknown":
            status = "observed"
        confidence = max(local_confidence, float((vlm_item or {}).get("confidence", 0.0) or 0.0))
    return local_value, _evidence_record(
        value=local_value,
        status=status,
        source=local_source,
        confidence=confidence,
        evidence_refs=evidence_refs,
    )


def _evidence_record(
    *,
    value: Any,
    status: str,
    source: str,
    confidence: float,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return {
        "value": value,
        "status": status,
        "source": source,
        "confidence": round(float(confidence or 0.0), 4),
        "evidence_refs": _unique_refs(evidence_refs),
    }


def _normalize_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _normalized_signal_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(sorted(str(item) for item in value))
    if isinstance(value, dict):
        return tuple(sorted((str(key), str(item)) for key, item in value.items()))
    return value


def _unique_refs(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
