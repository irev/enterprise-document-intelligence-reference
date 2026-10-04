"""Optional PaddleOCR engine integration.

Imports PaddleOCR lazily so the core reference package remains dependency-free.
The configured pipeline must operate locally; model provisioning is an
operations concern and must not be inferred from document content.
"""

import tempfile
from pathlib import Path
from typing import Any

from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine


class PaddleOcrEngine:
    def __init__(self, pipeline: Any | None = None):
        if pipeline is None:
            try:
                from paddleocr import PaddleOCR  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError("PADDLEOCR_NOT_INSTALLED") from exc
            pipeline = PaddleOCR()
        self._pipeline = pipeline

    def extract_text(self, document_bytes: bytes, *, timeout_seconds: int) -> bytes:
        # The adapter contract carries the timeout. PaddleOCR's in-process API
        # does not provide a portable hard-cancellation primitive; production
        # deployments requiring a hard deadline should isolate the engine in a
        # supervised worker process.
        if timeout_seconds <= 0:
            raise ValueError("INVALID_OCR_TIMEOUT")
        suffix = ".pdf" if document_bytes.startswith(b"%PDF") else ".img"
        path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
                handle.write(document_bytes)
                path = handle.name
            results = self._pipeline.predict(path)
            lines: list[str] = []
            for result in results:
                payload = getattr(result, "json", result)
                if callable(payload):
                    payload = payload()
                if isinstance(payload, dict):
                    payload = payload.get("res", payload)
                    texts = payload.get("rec_texts", ()) if isinstance(payload, dict) else ()
                    lines.extend(str(text) for text in texts if str(text).strip())
            return "\n".join(lines).encode("utf-8")
        finally:
            if path is not None:
                Path(path).unlink(missing_ok=True)


def paddle_results_to_ocr_result(results: Any) -> OcrResult:
    """Adapt PaddleOCR v3-style result JSON to the provider-neutral OCR model."""
    pages: list[OcrPage] = []
    for page_number, result in enumerate(results, start=1):
        payload = getattr(result, "json", result)
        if callable(payload):
            payload = payload()
        if not isinstance(payload, dict):
            raise ValueError("INVALID_PADDLE_OCR_RESULT")
        payload = payload.get("res", payload)
        if not isinstance(payload, dict):
            raise ValueError("INVALID_PADDLE_OCR_RESULT")

        texts = payload.get("rec_texts")
        boxes = payload.get("rec_boxes")
        scores = payload.get("rec_scores")
        shape = payload.get("doc_preprocessor_res", {}).get("output_img")
        if texts is None or boxes is None or len(texts) != len(boxes):
            raise ValueError("INCOMPLETE_PADDLE_OCR_GEOMETRY")
        if scores is not None and len(scores) != len(texts):
            raise ValueError("INCOMPLETE_PADDLE_OCR_CONFIDENCE")

        width = height = None
        if hasattr(shape, "shape") and len(shape.shape) >= 2:
            height, width = float(shape.shape[0]), float(shape.shape[1])
        elif "input_img_shape" in payload:
            dims = payload["input_img_shape"]
            if isinstance(dims, (list, tuple)) and len(dims) >= 2:
                height, width = float(dims[0]), float(dims[1])
        if not width or not height:
            raise ValueError("MISSING_PADDLE_OCR_PAGE_DIMENSIONS")

        lines: list[OcrTextLine] = []
        for index, (text, box) in enumerate(zip(texts, boxes, strict=True)):
            if not str(text).strip():
                continue
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                raise ValueError("INVALID_PADDLE_OCR_BOX")
            x0, y0, x1, y1 = (float(value) for value in box)
            bbox = BoundingBox(x0 / width, y0 / height, x1 / width, y1 / height)
            confidence = None if scores is None else float(scores[index])
            lines.append(OcrTextLine(str(text), bbox, confidence))
        pages.append(OcrPage(page_number, width, height, tuple(lines)))
    return OcrResult(tuple(pages))
