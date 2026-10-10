"""Deterministic local RoP extraction and routing; never payment authorization."""

from __future__ import annotations

import math
import re
from dataclasses import asdict
from typing import Callable

from edi_reference.domain.ocr import OcrResult
from edi_reference.domain.rop import FIELD_LABELS, RoutingPolicy, WorkspaceEngine

PATTERNS = {
    "document_number": r"(?:nomor\s*(?:dokumen|invoice|rop|kwitansi)?|no\.?\s*(?:invoice|rop|dokumen)?|invoice\s*(?:no\.?|number))\s*[:#]\s*(\S[^\n]*)",
    "document_date": r"(?:tanggal|date)\s*:\s*([^\n]+)",
    "total_idr": r"(?:grand\s+total|total\s*(?:tagihan|pembayaran)?|jumlah\s+bayar)\s*:\s*((?:Rp\.?\s*)?[\d., ]+)",
    "npwp": r"NPWP\s*:\s*([\d.\- ]+)",
}
SUBTYPES = {
    "RoP": r"\b(?:request\s+(?:of|for)\s+payment|permintaan\s+pembayaran|rop)\b",
    "Invoice": r"\b(?:invoice|faktur\s+penjualan)\b",
    "Receipt": r"\b(?:receipt|kuitansi|kwitansi)\b",
}


def classify(ocr: OcrResult) -> str:
    heading = "\n".join(line.text for page in ocr.pages[:1] for line in page.lines[:5])
    matches = [key for key, pattern in SUBTYPES.items() if re.search(pattern, heading, re.I)]
    return matches[0] if len(matches) == 1 else "UNKNOWN"


def route_reasons(ocr: OcrResult, policy: RoutingPolicy) -> list[str]:
    lines = [line for page in ocr.pages for line in page.lines]
    reasons = []
    if not lines or any(line.confidence is None for line in lines):
        reasons.append("OCR_CONFIDENCE_UNAVAILABLE")
    elif sum(line.confidence or 0 for line in lines) / len(lines) < policy.minimum_ocr_confidence:
        reasons.append("LOW_OCR_CONFIDENCE")
    if len(lines) > policy.maximum_lines:
        reasons.append("DENSE_LAYOUT")
    if any(min(page.width, page.height) < policy.minimum_short_side for page in ocr.pages):
        reasons.append("LOW_RESOLUTION")
    # Multiple separate cells at the same baseline indicate a spatial/table layout.
    for page in ocr.pages:
        rows: dict[int, int] = {}
        for line in page.lines:
            row = round(line.bbox.y0 * 100)
            rows[row] = rows.get(row, 0) + 1
        if sum(count >= 3 for count in rows.values()) >= 2:
            reasons.append("TABULAR_LAYOUT")
            break
    if classify(ocr) == "UNKNOWN":
        reasons.append("UNKNOWN_CLASSIFICATION")
    return reasons


def extract_text(ocr: OcrResult) -> dict:
    fields = {}
    for name, pattern in PATTERNS.items():
        candidates = []
        for page in ocr.pages:
            for line in page.lines:
                match = re.search(pattern, line.text, re.I)
                if match:
                    candidates.append({
                        "raw_value": match.group(1).strip(), "confidence": line.confidence,
                        "evidence": {"page": page.page_number, "text": line.text,
                                     "bbox": list(asdict(line.bbox).values())},
                        "extractor": "paddle-ocr/label-parser-v1",
                    })
        fields[name] = ({"state": "PRESENT", **candidates[0]} if len(candidates) == 1 else
                        {"state": "AMBIGUOUS" if candidates else "NOT_PRESENT", "candidates": candidates})
    return {"subtype": classify(ocr), "fields": fields, "line_items": []}


def validate_prediction(prediction: object, page_count: int) -> dict:
    """Model JSON is untrusted. Accept only the bounded workspace prediction shape."""
    if not isinstance(prediction, dict) or set(prediction) != {"subtype", "fields", "line_items"}:
        raise ValueError("INVALID_PREDICTION")
    if prediction["subtype"] not in {*SUBTYPES, "UNKNOWN"}:
        raise ValueError("INVALID_PREDICTION")
    fields, items = prediction["fields"], prediction["line_items"]
    if not isinstance(fields, dict) or set(fields) != set(FIELD_LABELS):
        raise ValueError("INVALID_PREDICTION")
    if not isinstance(items, list) or len(items) > 200:
        raise ValueError("INVALID_PREDICTION")
    for field in list(fields.values()) + items:
        if not isinstance(field, dict) or field.get("state") not in {"PRESENT", "NOT_PRESENT", "ILLEGIBLE", "AMBIGUOUS"}:
            raise ValueError("INVALID_PREDICTION")
        if field["state"] != "PRESENT":
            if set(field) != {"state"}:
                raise ValueError("INVALID_PREDICTION")
            continue
        if set(field) != {"state", "raw_value", "confidence", "evidence"}:
            raise ValueError("INVALID_PREDICTION")
        raw, confidence, evidence = field["raw_value"], field["confidence"], field["evidence"]
        if not isinstance(raw, str) or not raw.strip() or len(raw) > 2000:
            raise ValueError("INVALID_PREDICTION")
        if confidence is not None and (type(confidence) not in {int, float} or not math.isfinite(confidence)
                                       or not 0 <= confidence <= 1):
            raise ValueError("INVALID_PREDICTION")
        if not isinstance(evidence, dict) or set(evidence) != {"page", "text", "bbox"}:
            raise ValueError("INVALID_PREDICTION")
        if type(evidence["page"]) is not int or not 1 <= evidence["page"] <= page_count:
            raise ValueError("INVALID_PREDICTION")
        box = evidence["bbox"]
        if (not isinstance(box, list) or len(box) != 4 or
                any(type(v) not in {int, float} or not math.isfinite(v) or not 0 <= v <= 1 for v in box) or
                box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError("INVALID_PREDICTION")
        if not isinstance(evidence["text"], str) or not evidence["text"].strip() or len(evidence["text"]) > 4000:
            raise ValueError("INVALID_PREDICTION")
        field["extractor"] = "local-vision"
    return prediction


def process_document(
    content: bytes, media_type: str, *, engine: WorkspaceEngine,
    normalize: Callable[[str, str], object], progress: Callable[[str, int], None],
    save_pages: Callable[[tuple[bytes, ...]], None], policy: RoutingPolicy = RoutingPolicy(),
) -> dict:
    progress("PREPROCESSING", 10)
    pages = engine.prepare(content, media_type)
    if not pages or len(pages) > 20:
        raise ValueError("PAGE_LIMIT")
    save_pages(pages)
    progress("OCR", 35)
    warnings = []
    try:
        ocr = engine.recognize(pages)
        prediction = extract_text(ocr)
        reasons = route_reasons(ocr, policy)
    except (ValueError, RuntimeError):
        prediction = None
        reasons = ["OCR_UNAVAILABLE"]
    route = "OCR"
    if reasons:
        progress("VISION", 65)
        try:
            prediction = validate_prediction(engine.extract_layout(pages), len(pages))
            route = "VISION"
        except (ValueError, RuntimeError, OSError):
            if prediction is None:
                raise RuntimeError("EXTRACTION_UNAVAILABLE") from None
            warnings.append("VISION_UNAVAILABLE_REVIEW_OCR")
    assert prediction is not None
    progress("NORMALIZING", 90)
    for name, field in prediction["fields"].items():
        if field["state"] == "PRESENT":
            try:
                field["normalized_value"] = normalize(name, field["raw_value"])
            except ValueError:
                field["normalized_value"] = None
                field["normalization_error"] = True
    return {**prediction, "route": route, "route_reasons": reasons, "warnings": warnings,
            "page_count": len(pages), "review_required": True, "workspace_schema_version": "1",
            "coordinate_space": "NORMALIZED_TOP_LEFT_XYXY_PREPROCESSED_PAGE",
            "confidence_calibrated": False}
