"""Optional PaddleOCR engine integration.

Imports PaddleOCR lazily so the core reference package remains dependency-free.
The configured pipeline must operate locally; model provisioning is an
operations concern and must not be inferred from document content.
"""

import tempfile
from pathlib import Path
from typing import Any


class PaddleOcrEngine:
    def __init__(self, pipeline: Any | None = None):
        if pipeline is None:
            try:
                from paddleocr import PaddleOCR
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
