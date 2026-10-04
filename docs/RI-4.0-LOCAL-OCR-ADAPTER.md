# RI-4.0 — Local OCR Adapter Boundary

The first concrete provider path is a local OCR adapter with no external egress.

The core package does not depend on a specific OCR library. LocalOcrProviderAdapter accepts an injected LocalOcrEngine implementation and exposes it through the existing provider SPI. This proves the execution path without making Tesseract, PaddleOCR, ONNX Runtime, a cloud API, or another engine part of the platform contract.

The adapter requires:
- execution class OCR;
- TEXT_EXTRACTION capability;
- data egress NONE.

Invocation still passes through ExecutionPolicy and the secure invocation boundary. The engine receives document bytes and the configured timeout only. Provider selection, tenant authorization, fallback and business decisions remain outside the engine.

A production engine package can now be added independently and selected through control-plane configuration.
