# RI-4.3 — OCR to Canonical Document Structure

Provider OCR output now has a deterministic bridge into StructuredDocument.

The initial bridge intentionally consumes provider-neutral UTF-8 text output rather than PaddleOCR-specific objects. Each non-empty line becomes an evidence-addressable TextBlock with stable reading order. Non-UTF-8 and empty outputs fail explicitly.

The initial geometry is deliberately conservative: because the current provider contract returns text bytes only, blocks receive full-page normalized bounding boxes and a synthetic 1x1 page. This is sufficient to exercise downstream classification/extraction/evidence contracts but MUST NOT be represented as precise OCR geometry.

A later layout-capable provider contract should carry page dimensions, line/word coordinates and confidence directly. It must replace this coarse bridge rather than infer coordinates from text.
