# RI-4.1 — PaddleOCR Local Engine Integration

PaddleOCR is the first concrete local OCR engine integration behind LocalOcrEngine.

It is intentionally optional and lazily imported: the reference implementation core keeps zero runtime dependencies and does not make PaddleOCR part of the normative platform contract. A deployment may replace it with another engine without changing provider planning, authorization, invocation, or canonical downstream contracts.

The engine writes invocation bytes to a short-lived local file because PaddleOCR's pipeline accepts file input, invokes the injected/local pipeline, converts recognized text to UTF-8 bytes, and deletes the temporary file in a finally block.

## Operational constraint

The in-process PaddleOCR API does not expose a portable hard cancellation primitive matching InvocationLimits. The timeout is therefore validated and propagated at the adapter contract, but production deployments requiring a hard deadline should run the OCR engine in an isolated supervised worker/process and terminate the worker on deadline.

Model installation/provisioning is an operations concern. Production local-only deployments should pre-provision models and must not silently download or switch to a remote OCR service at request time.
