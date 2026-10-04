# RI-4.5 — PaddleOCR Structured Result Adapter

PaddleOCR-native recognition output can now be converted at the integration boundary into the provider-neutral OcrResult contract.

The adapter validates alignment of recognized text, boxes and optional confidence scores, requires page dimensions, normalizes pixel coordinates to canonical 0..1 BoundingBox coordinates, and preserves the original page dimensions and confidence values.

Malformed or incomplete geometry fails explicitly instead of falling back to fabricated coordinates.

This keeps PaddleOCR-specific result shapes inside the adapter layer. Downstream StructuredDocument and evidence processing consume only provider-neutral domain values.

The existing text-only PaddleOcrEngine path remains compatible. Production layout/evidence processing should prefer the structured adapter whenever the engine exposes geometry.
