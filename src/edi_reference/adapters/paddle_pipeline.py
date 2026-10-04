"""Explicit construction of governed PaddleOCR pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edi_reference.adapters.paddle_ocr import PaddleOcrEngine
from edi_reference.application.paddle_models import ModelArtifactState, verify_paddle_model


@dataclass(frozen=True, slots=True)
class PaddlePipelineConfiguration:
    model_id: str
    model_root: Path
    require_local_pinned: bool = False


def load_governed_model(
    configuration: PaddlePipelineConfiguration,
) -> ModelArtifactState:
    state = verify_paddle_model(
        configuration.model_root / "paddle-ocr" / configuration.model_id
    )
    if state.provider_id != "paddle-ocr" or state.model_id != configuration.model_id:
        raise ValueError("PADDLE_MODEL_STATE_IDENTITY_MISMATCH")
    if configuration.require_local_pinned and state.storage != "LOCAL_PINNED":
        raise ValueError("LOCAL_PINNED_MODEL_REQUIRED")
    if state.status not in {"WARMED", "READY"}:
        raise ValueError("PADDLE_MODEL_NOT_USABLE")
    return state


def build_paddle_pipeline(
    configuration: PaddlePipelineConfiguration,
) -> Any:
    state = load_governed_model(configuration)
    try:
        from paddleocr import PaddleOCR  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("PADDLEOCR_NOT_INSTALLED") from exc

    if state.model_id == "pp-ocrv6-medium":
        return PaddleOCR(
            text_detection_model_name="PP-OCRv6_medium_det",
            text_recognition_model_name="PP-OCRv6_medium_rec",
        )
    if state.model_id == "pp-ocrv5-server":
        return PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
        )
    raise ValueError("MODEL_NOT_SUPPORTED_BY_OCR_PIPELINE")


@dataclass(frozen=True, slots=True)
class PaddleOcrEngineFactory:
    """Picklable factory for spawn-isolated OCR workers."""

    configuration: PaddlePipelineConfiguration

    def __call__(self) -> PaddleOcrEngine:
        return PaddleOcrEngine(build_paddle_pipeline(self.configuration))
