"""Provider-neutral codec for structured OCR invocation payloads."""

import json

from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine

STRUCTURED_OCR_MEDIA_TYPE = "application/vnd.edi.ocr-result+json;version=1"


def encode_ocr_result(result: OcrResult) -> bytes:
    payload = {
        "pages": [
            {
                "page_number": page.page_number,
                "width": page.width,
                "height": page.height,
                "lines": [
                    {
                        "text": line.text,
                        "bbox": [line.bbox.x0, line.bbox.y0, line.bbox.x1, line.bbox.y1],
                        "confidence": line.confidence,
                    }
                    for line in page.lines
                ],
            }
            for page in result.pages
        ]
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def decode_ocr_result(payload: bytes) -> OcrResult:
    try:
        raw = json.loads(payload.decode("utf-8"))
        pages = tuple(
            OcrPage(
                int(page["page_number"]),
                float(page["width"]),
                float(page["height"]),
                tuple(
                    OcrTextLine(
                        str(line["text"]),
                        BoundingBox(*(float(value) for value in line["bbox"])),
                        None if line.get("confidence") is None else float(line["confidence"]),
                    )
                    for line in page["lines"]
                ),
            )
            for page in raw["pages"]
        )
        return OcrResult(pages)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("INVALID_STRUCTURED_OCR_PAYLOAD") from None
