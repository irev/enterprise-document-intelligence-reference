# RI-4.8 — Typed Provider Output Envelope

Provider invocation output now declares a media type. InvocationResult remains a byte transport envelope, but consumers no longer need to infer whether bytes contain plain text, structured OCR JSON, or another contract.

Structured OCR has a provider-neutral versioned media type and deterministic JSON codec. The codec serializes only OcrResult domain values; PaddleOCR-native DTOs do not cross the adapter boundary.

This preserves three separations:
- provider-native DTO -> adapter-owned conversion;
- provider-neutral domain result -> versioned transport encoding;
- canonical StructuredDocument -> downstream document understanding contract.

The transport is intentionally not Python object serialization. JSON is used as an interoperable representation and is validated back through OcrResult domain invariants.

Existing providers default to application/octet-stream for backward compatibility. Providers emitting structured OCR SHOULD declare the structured OCR media type explicitly.
