import hashlib
import json
import pickle
import sys
from pathlib import Path

import pytest

from edi_reference.adapters.paddle_pipeline import (
    PaddleOcrEngineFactory,
    PaddlePipelineConfiguration,
    build_paddle_pipeline,
    load_governed_model,
)


def write_state(root: Path, *, storage: str = "UPSTREAM_CACHE") -> None:
    artifact = root / "paddle-ocr" / "pp-ocrv6-medium"
    artifact.mkdir(parents=True)
    manifest = artifact / "resolved-model.json"
    manifest.write_text(
        '{"model_id":"pp-ocrv6-medium","names":["PP-OCRv6_medium_det","PP-OCRv6_medium_rec"]}',
        encoding="utf-8",
    )
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    (artifact / "model-state.json").write_text(
        json.dumps(
            {
                "provider_id": "paddle-ocr",
                "model_id": "pp-ocrv6-medium",
                "source": "HUGGINGFACE",
                "artifact_dir": str(artifact),
                "storage": storage,
                "status": "WARMED" if storage == "UPSTREAM_CACHE" else "READY",
                "manifest_sha256": digest,
            }
        ),
        encoding="utf-8",
    )


def test_connected_profile_accepts_warmed_governed_model(tmp_path: Path) -> None:
    write_state(tmp_path)

    state = load_governed_model(
        PaddlePipelineConfiguration("pp-ocrv6-medium", tmp_path)
    )

    assert state.status == "WARMED"


def test_offline_profile_rejects_upstream_cache(tmp_path: Path) -> None:
    write_state(tmp_path)

    with pytest.raises(ValueError, match="LOCAL_PINNED_MODEL_REQUIRED"):
        load_governed_model(
            PaddlePipelineConfiguration(
                "pp-ocrv6-medium",
                tmp_path,
                require_local_pinned=True,
            )
        )


def test_factory_uses_explicit_v6_model_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_state(tmp_path)
    calls: dict[str, object] = {}

    class PaddleOCR:
        def __init__(self, **kwargs: object) -> None:
            calls.update(kwargs)

    class Module:
        pass

    module = Module()
    module.PaddleOCR = PaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", module)

    build_paddle_pipeline(PaddlePipelineConfiguration("pp-ocrv6-medium", tmp_path))

    assert calls == {
        "text_detection_model_name": "PP-OCRv6_medium_det",
        "text_recognition_model_name": "PP-OCRv6_medium_rec",
    }


def test_engine_factory_is_pickle_safe_configuration(tmp_path: Path) -> None:
    factory = PaddleOcrEngineFactory(
        PaddlePipelineConfiguration("pp-ocrv6-medium", tmp_path)
    )

    restored = pickle.loads(pickle.dumps(factory))

    assert restored.configuration == factory.configuration
