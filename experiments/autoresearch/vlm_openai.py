from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Protocol

import httpx

from experiments.autoresearch.taxonomy import SCHEMA_VERSION


class FramePackClassifier(Protocol):
    provider: str
    model: str | None
    available: bool

    def classify_reference(self, *, sampling_map: dict[str, Any], frame_root: Path) -> list[dict[str, Any]]:
        ...


class DisabledFramePackClassifier:
    provider = "disabled"
    model = None
    available = True

    def classify_reference(self, *, sampling_map: dict[str, Any], frame_root: Path) -> list[dict[str, Any]]:
        return []


class OpenAiFramePackClassifier:
    provider = "openai"

    def __init__(self, *, api_key: str, model: str, timeout_s: float = 45.0) -> None:
        self._api_key = api_key
        self.model = model
        self.available = bool(api_key and model)
        self._timeout_s = timeout_s

    def classify_reference(self, *, sampling_map: dict[str, Any], frame_root: Path) -> list[dict[str, Any]]:
        if not self.available:
            return []
        content: list[dict[str, Any]] = [{"type": "input_text", "text": _build_instruction_text(sampling_map)}]
        reference_dir = frame_root / sampling_map["reference_id"]
        for frame in sampling_map.get("frames", []):
            relative_path = frame.get("relative_path")
            if not relative_path:
                continue
            image_path = reference_dir / f"{frame['frame_id']}.jpg"
            if not image_path.exists():
                continue
            content.append(
                {
                    "type": "input_text",
                    "text": f"Frame {frame['frame_id']} at {frame['timestamp_s']}s.",
                }
            )
            content.append(
                {
                    "type": "input_image",
                    "image_url": _to_data_url(image_path),
                    "detail": "low",
                }
            )
        if len(content) <= 1:
            return []
        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": 900,
        }
        with httpx.Client(timeout=self._timeout_s) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            response_payload = response.json()
        response_text = _extract_output_text(response_payload)
        parsed = _parse_json_object(response_text)
        labels = parsed.get("labels", []) if isinstance(parsed, dict) else []
        normalized: list[dict[str, Any]] = []
        for item in labels:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "label": item.get("label"),
                    "value": item.get("value"),
                    "confidence": float(item.get("confidence", 0.0) or 0.0),
                    "why": item.get("why") or "",
                    "evidence_frame_ids": [str(frame_id) for frame_id in item.get("evidence_frame_ids", [])],
                    "source": f"{self.provider}:{self.model}",
                }
            )
        return normalized


def build_classifier(*, provider_name: str, model: str | None, api_key: str | None = None) -> FramePackClassifier:
    normalized = provider_name.lower()
    if normalized == "disabled":
        return DisabledFramePackClassifier()
    if normalized != "openai":
        raise ValueError(f"Unsupported VLM provider '{provider_name}'.")
    resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved_api_key or not model:
        return DisabledFramePackClassifier()
    return OpenAiFramePackClassifier(api_key=resolved_api_key, model=model)


def classify_sampling_maps(
    *,
    sampling_maps: list[dict[str, Any]],
    frame_root: Path,
    classifier: FramePackClassifier,
) -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    for sampling_map in sampling_maps:
        references.append(
            {
                "reference_id": sampling_map["reference_id"],
                "labels": classifier.classify_reference(sampling_map=sampling_map, frame_root=frame_root),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": classifier.provider,
        "model": classifier.model,
        "references": references,
    }


def _build_instruction_text(sampling_map: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Analyze this short-form video sample pack and return JSON only.",
            "Focus on packaging intelligence, not topic selection.",
            "Required JSON shape:",
            '{"labels":[{"label":"hook_family","value":"counterintuitive_claim","confidence":0.82,"evidence_frame_ids":["f0"],"why":"..."}]}',
            "Allowed labels: opening_frame_mode, overlay_family, caption_style_family, hook_family, insert_types, format_archetype, pattern_interrupt_types, effect_density, sticky_factors.",
            f"Opening frame ids: {', '.join(sampling_map.get('zones', {}).get('opening_frames', [])) or 'none'}",
            f"Scene frame ids: {', '.join(sampling_map.get('zones', {}).get('scene_frames', [])) or 'none'}",
            f"End frame ids: {', '.join(sampling_map.get('zones', {}).get('end_frames', [])) or 'none'}",
        ]
    )


def _extract_output_text(payload: dict[str, Any]) -> str:
    collected: list[str] = []
    for output_item in payload.get("output", []) or []:
        for content_item in output_item.get("content", []) or []:
            if content_item.get("type") in {"output_text", "text"} and content_item.get("text"):
                collected.append(content_item["text"])
    if collected:
        return "\n".join(collected)
    return payload.get("output_text", "") or ""


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}


def _to_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"
