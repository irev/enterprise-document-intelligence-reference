# RI-4.4 — Structured OCR Result Contract

The OCR boundary now has a provider-neutral structured result vocabulary: OcrResult, OcrPage and OcrTextLine.

A text line carries normalized BoundingBox geometry and optional confidence. Pages carry explicit page number and dimensions. The canonical mapper preserves page boundaries, geometry, reading order and confidence when creating StructuredDocument/TextBlock values.

This removes the need to fabricate full-page geometry when an OCR provider can supply coordinates. The RI-4.3 text-only bridge remains a compatibility path for engines that expose text only; it must not be interpreted as precise evidence geometry.

Concrete OCR integrations should adapt engine-native output into OcrResult. Downstream classification, extraction and evidence code remains independent of the OCR vendor.
