from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from experiments.autoresearch.taxonomy import SCHEMA_VERSION, average, text_occupancy_band


@dataclass(slots=True)
class OcrBlock:
    text: str
    confidence: float
    bbox: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox,
        }


@dataclass(slots=True)
class OcrFrameResult:
    frame_id: str
    provider: str
    blocks: list[OcrBlock]
    relative_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "provider": self.provider,
            "relative_path": self.relative_path,
            "blocks": [block.to_dict() for block in self.blocks],
        }


class OcrProvider(Protocol):
    name: str
    available: bool

    def recognize(self, image_path: Path) -> list[OcrBlock]:
        ...


class DisabledOcrProvider:
    name = "disabled"
    available = True

    def recognize(self, image_path: Path) -> list[OcrBlock]:
        return []


class TesseractCliOcrProvider:
    name = "tesseract"

    def __init__(self, *, tesseract_bin: str = "tesseract") -> None:
        self._tesseract_bin = tesseract_bin
        self.available = shutil.which(tesseract_bin) is not None

    def recognize(self, image_path: Path) -> list[OcrBlock]:
        if not self.available:
            return []
        command = [self._tesseract_bin, str(image_path), "stdout", "tsv"]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode not in (0, 1):
            return []
        return _parse_tesseract_tsv(completed.stdout)


class PaddleOcrProvider:
    name = "paddleocr"

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore
        except Exception:
            self.available = False
            self._ocr = None
        else:
            self.available = True
            self._ocr = PaddleOCR(use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)

    def recognize(self, image_path: Path) -> list[OcrBlock]:
        if not self.available or self._ocr is None:
            return []
        result = self._ocr.predict(str(image_path))
        blocks: list[OcrBlock] = []
        for item in result or []:
            for box in item.get("rec_boxes", []) or []:
                pass
        rec_texts = []
        rec_scores = []
        rec_boxes = []
        for item in result or []:
            rec_texts.extend(item.get("rec_texts", []) or [])
            rec_scores.extend(item.get("rec_scores", []) or [])
            rec_boxes.extend(item.get("rec_boxes", []) or [])
        for text, confidence, bbox in zip(rec_texts, rec_scores, rec_boxes):
            if not text:
                continue
            flattened = [int(value) for point in bbox for value in point] if bbox and isinstance(bbox[0], (list, tuple)) else [int(value) for value in bbox]
            blocks.append(
                OcrBlock(
                    text=str(text).strip(),
                    confidence=float(confidence or 0.0),
                    bbox=flattened,
                )
            )
        return blocks


class StaticOcrProvider:
    name = "static"
    available = True

    def __init__(self, frame_blocks: dict[str, list[dict[str, Any]]]) -> None:
        self._frame_blocks = frame_blocks

    def recognize(self, image_path: Path) -> list[OcrBlock]:
        frame_id = image_path.stem
        blocks = self._frame_blocks.get(frame_id, [])
        return [
            OcrBlock(
                text=str(block["text"]),
                confidence=float(block.get("confidence", 1.0)),
                bbox=[int(value) for value in block.get("bbox", [0, 0, 0, 0])],
            )
            for block in blocks
        ]


def build_ocr_provider(provider_name: str, *, tesseract_bin: str = "tesseract") -> OcrProvider:
    normalized = provider_name.lower()
    if normalized == "disabled":
        return DisabledOcrProvider()
    if normalized == "tesseract":
        return TesseractCliOcrProvider(tesseract_bin=tesseract_bin)
    if normalized == "paddleocr":
        provider = PaddleOcrProvider()
        if provider.available:
            return provider
        return DisabledOcrProvider()
    if normalized == "auto":
        provider = PaddleOcrProvider()
        if provider.available:
            return provider
        tesseract_provider = TesseractCliOcrProvider(tesseract_bin=tesseract_bin)
        if tesseract_provider.available:
            return tesseract_provider
        return DisabledOcrProvider()
    raise ValueError(f"Unsupported OCR provider '{provider_name}'.")


def run_ocr_pass(
    *,
    sampling_maps: list[dict[str, Any]],
    frame_root: Path,
    provider: OcrProvider,
) -> dict[str, Any]:
    references: list[dict[str, Any]] = []
    for sampling_map in sampling_maps:
        frame_results: list[dict[str, Any]] = []
        reference_dir = frame_root / sampling_map["reference_id"]
        for frame in sampling_map["frames"]:
            relative_path = frame.get("relative_path")
            if not relative_path:
                frame_results.append(OcrFrameResult(frame_id=frame["frame_id"], provider=provider.name, blocks=[], relative_path=None).to_dict())
                continue
            image_path = reference_dir / f"{frame['frame_id']}.jpg"
            blocks = provider.recognize(image_path)
            frame_results.append(
                OcrFrameResult(
                    frame_id=frame["frame_id"],
                    provider=provider.name,
                    blocks=blocks,
                    relative_path=relative_path,
                ).to_dict()
            )
        references.append({"reference_id": sampling_map["reference_id"], "frames": frame_results})
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": provider.name,
        "references": references,
    }


def summarize_ocr_reference(
    *,
    reference_id: str,
    ocr_report: dict[str, Any],
    technical_probe: dict[str, Any],
    frame_ids: list[str] | None = None,
) -> dict[str, Any]:
    reference_payload = next(
        (item for item in ocr_report.get("references", []) if item.get("reference_id") == reference_id),
        {"frames": []},
    )
    allowed_frame_ids = set(frame_ids or [])
    frames = [
        frame
        for frame in reference_payload.get("frames", [])
        if not allowed_frame_ids or frame.get("frame_id") in allowed_frame_ids
    ]
    all_blocks = [block for frame in frames for block in frame.get("blocks", [])]
    occupancy_values: list[float] = []
    emphasis_patterns: set[str] = set()
    headline_card_presence = False
    for block in all_blocks:
        bbox = block.get("bbox", [])
        occupancy_values.append(_bbox_area_ratio(bbox=bbox, technical_probe=technical_probe))
        text = str(block.get("text", "")).strip()
        if not text:
            continue
        if text.isupper() and len(text) >= 4:
            emphasis_patterns.add("all_caps")
        if re.search(r"[!?]", text):
            emphasis_patterns.add("punctuation_emphasis")
        if len(text.split()) <= 5 and len(text) >= 12:
            headline_card_presence = True
        if re.search(r"[\U0001F300-\U0001FAFF]", text):
            emphasis_patterns.add("emoji")
    occupancy_ratio = average(occupancy_values)
    return {
        "provider": ocr_report.get("provider", "disabled"),
        "burned_caption_present": bool(all_blocks),
        "headline_card_presence": headline_card_presence,
        "block_count": len(all_blocks),
        "text_occupancy_ratio": occupancy_ratio,
        "text_occupancy_band": text_occupancy_band(occupancy_ratio),
        "safe_zone_bias": _safe_zone_bias(all_blocks=all_blocks, height=technical_probe.get("height")),
        "emphasis_patterns": sorted(emphasis_patterns),
        "blocks": [
            {
                "frame_id": frame["frame_id"],
                "text": block["text"],
                "bbox": block["bbox"],
                "confidence": block["confidence"],
            }
            for frame in frames
            for block in frame.get("blocks", [])
        ],
    }


def _parse_tesseract_tsv(payload: str) -> list[OcrBlock]:
    lines = [line for line in payload.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0].split("\t")
    indices = {name: index for index, name in enumerate(header)}
    required = {"text", "conf", "left", "top", "width", "height"}
    if not required.issubset(indices):
        return []
    blocks: list[OcrBlock] = []
    for line in lines[1:]:
        columns = line.split("\t")
        text = columns[indices["text"]].strip()
        if not text:
            continue
        confidence = float(columns[indices["conf"]]) if columns[indices["conf"]] not in {"-1", ""} else 0.0
        left = int(columns[indices["left"]] or 0)
        top = int(columns[indices["top"]] or 0)
        width = int(columns[indices["width"]] or 0)
        height = int(columns[indices["height"]] or 0)
        blocks.append(OcrBlock(text=text, confidence=confidence / 100.0, bbox=[left, top, width, height]))
    return blocks


def _bbox_area_ratio(*, bbox: list[int], technical_probe: dict[str, Any]) -> float:
    width = technical_probe.get("width") or 0
    height = technical_probe.get("height") or 0
    if len(bbox) < 4 or width <= 0 or height <= 0:
        return 0.0
    if len(bbox) == 4:
        _, _, box_width, box_height = bbox
    else:
        xs = bbox[0::2]
        ys = bbox[1::2]
        box_width = max(xs) - min(xs)
        box_height = max(ys) - min(ys)
    return round(max(box_width, 0) * max(box_height, 0) / float(width * height), 4)


def _safe_zone_bias(*, all_blocks: list[dict[str, Any]], height: int | None) -> str:
    if not all_blocks or not height:
        return "unknown"
    lower_third = 0
    for block in all_blocks:
        bbox = block.get("bbox", [])
        top = bbox[1] if len(bbox) >= 2 else 0
        box_height = bbox[3] if len(bbox) >= 4 else 0
        if top + box_height >= int(height * 0.55):
            lower_third += 1
    ratio_value = lower_third / len(all_blocks)
    if ratio_value >= 0.75:
        return "lower_third"
    if ratio_value >= 0.35:
        return "mid_lower"
    return "distributed"
