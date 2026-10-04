"""Trusted runtime-python OCR inference for local file processing.

PaddleOCR lives only inside the isolated provider runtime. The core process
resolves a trusted, code-owned argument vector and runs inference through the
runtime interpreter; document bytes never become executable input.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from edi_reference.adapters.paddle_ocr import paddle_results_to_ocr_result
from edi_reference.adapters.paddle_pipeline import (
    PaddlePipelineConfiguration,
    load_governed_model,
)
from edi_reference.application.paddle_models import resolve_paddle_model
from edi_reference.domain.ocr import OcrResult

_PREDICT_SCRIPT = "\n".join(
    (
        "import json, sys",
        "from pathlib import Path",
        "p = json.loads(sys.argv[1])",
        "from paddleocr import PaddleOCR",
        "obj = PaddleOCR(text_detection_model_name=p['names'][0], text_recognition_model_name=p['names'][1])",
        "out = []",
        "for r in obj.predict(p['document']):",
        "    d = getattr(r, 'json', r)",
        "    d = d() if callable(d) else d",
        "    if isinstance(d, dict):",
        "        d = d.get('res', d)",
        "    if not isinstance(d, dict):",
        "        raise SystemExit('INVALID_PADDLE_RESULT')",
        "    out.append(d)",
        "Path(p['output']).write_text(json.dumps(out), encoding='utf-8')",
    )
)


def build_predict_command(
    *,
    python_executable: str,
    model_id: str,
    document_path: Path,
    output_path: Path,
) -> tuple[str, ...]:
    model = resolve_paddle_model(model_id)
    if model.kind != "ocr":
        raise ValueError("MODEL_NOT_SUPPORTED_BY_OCR_PIPELINE")
    payload = json.dumps(
        {
            "document": str(document_path),
            "output": str(output_path),
            "names": list(model.upstream_names),
        }
    )
    return (python_executable, "-c", _PREDICT_SCRIPT, payload)


def run_local_ocr(
    *,
    python_executable: str,
    model_id: str,
    model_root: Path,
    document_bytes: bytes,
    timeout_seconds: int = 300,
) -> OcrResult:
    if timeout_seconds <= 0:
        raise ValueError("INVALID_OCR_TIMEOUT")
    load_governed_model(
        PaddlePipelineConfiguration(
            model_id=model_id,
            model_root=model_root,
            require_local_pinned=False,
        )
    )
    with tempfile.TemporaryDirectory(prefix="edi-process-") as temporary:
        work = Path(temporary)
        document_path = work / "document"
        output_path = work / "ocr-pages.json"
        document_path.write_bytes(document_bytes)
        command = build_predict_command(
            python_executable=python_executable,
            model_id=model_id,
            document_path=document_path,
            output_path=output_path,
        )
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("LOCAL_OCR_TIMEOUT") from exc
        if completed.returncode != 0:
            raise RuntimeError("LOCAL_OCR_FAILED")
        if not output_path.is_file():
            raise RuntimeError("LOCAL_OCR_OUTPUT_MISSING")
        try:
            pages = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("LOCAL_OCR_OUTPUT_INVALID") from exc
    if not isinstance(pages, list) or not pages:
        raise RuntimeError("LOCAL_OCR_OUTPUT_INVALID")
    return paddle_results_to_ocr_result(pages)
