"""Run PaddleOCR pages through the isolated runtime interpreter (RI-4.11).

The core never imports PaddleOCR. It verifies pinned model directories, writes
the document to a private temporary directory and runs a fixed argument
vector (`<runtime python> -I paddle_page_worker.py <workdir>`) with a timeout.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from edi_reference.adapters.paddle_ocr import paddle_results_to_ocr_result
from edi_reference.domain.ocr import OcrResult

MAX_RESULT_BYTES = 32 * 1024 * 1024
WORKER = Path(__file__).with_name("paddle_page_worker.py")
LOG = logging.getLogger("edi.ocr")


def model_dir_digest(directory: Path) -> str:
    """Digest over every file's relative path and SHA-256, order-independent."""
    root = directory.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("MODEL_DIRECTORY_REQUIRED")
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        with path.open("rb") as handle:
            entries.append(f"{path.relative_to(root).as_posix()}:{hashlib.file_digest(handle, 'sha256').hexdigest()}")
    if not entries:
        raise ValueError("MODEL_DIRECTORY_EMPTY")
    return hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OcrPages:
    result: OcrResult
    text_layer: str
    total_pages: int
    raw_pages: list


class RuntimeOcrEngine:
    def __init__(self, *, python: Path, ocr: dict, timeout_seconds: int = 600) -> None:
        self.python = python
        self.ocr = ocr
        self.timeout_seconds = timeout_seconds

    def verify_models(self) -> None:
        for prefix in ("det", "rec"):
            pinned = self.ocr.get(f"{prefix}_digest")
            if pinned and model_dir_digest(Path(self.ocr[f"{prefix}_dir"])) != pinned:
                raise RuntimeError("OCR_MODEL_DIGEST_MISMATCH")

    def decode(self, raw_pages: list) -> OcrResult:
        return paddle_results_to_ocr_result(raw_pages)

    def recognize(self, content: bytes, media_type: str, *, max_pages: int) -> OcrPages:
        if not self.python.is_file():
            raise RuntimeError("OCR_RUNTIME_NOT_INSTALLED")
        self.verify_models()
        with tempfile.TemporaryDirectory(prefix="edi-ocr-") as temporary:
            work = Path(temporary)
            (work / "input").write_bytes(content)
            (work / "request.json").write_text(json.dumps({
                "media": media_type, "max_pages": max_pages,
                "ocr": {key: self.ocr[key] for key in ("det_name", "det_dir", "rec_name", "rec_dir")},
            }), encoding="utf-8")
            try:
                done = subprocess.run([str(self.python), "-I", str(WORKER), str(work)], capture_output=True,
                                      timeout=self.timeout_seconds, shell=False, check=False)
            except subprocess.TimeoutExpired:
                raise RuntimeError("OCR_TIMEOUT") from None
            output = work / "result.json"
            if done.returncode != 0 or not output.is_file():
                # Operator diagnostics only; never returned to clients.
                LOG.warning("OCR worker failed (rc=%s): %s", done.returncode,
                            done.stderr.decode("utf-8", "replace")[-2000:])
                raise RuntimeError("OCR_FAILED")
            if output.stat().st_size > MAX_RESULT_BYTES:
                raise RuntimeError("OCR_OUTPUT_LIMIT")
            payload = json.loads(output.read_text(encoding="utf-8"))
        pages = payload["pages"]
        if not pages:
            raise RuntimeError("OCR_NO_PAGES")
        return OcrPages(paddle_results_to_ocr_result(pages), "\n".join(payload.get("text_layer", [])),
                        int(payload.get("total_pages", len(pages))), pages)
