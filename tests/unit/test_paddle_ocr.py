import sys

import pytest

from edi_reference.adapters.paddle_ocr import PaddleOcrEngine


class Result:
    json = {"res": {"rec_texts": ["Invoice INV-001", "Total 1250000"]}}


class Pipeline:
    def __init__(self):
        self.paths = []

    def predict(self, path):
        self.paths.append(path)
        return [Result()]


def test_paddle_engine_converts_local_result_to_utf8_text_and_cleans_temp_file():
    pipeline = Pipeline()
    engine = PaddleOcrEngine(pipeline)
    output = engine.extract_text(b"synthetic-image", timeout_seconds=5)
    assert output == b"Invoice INV-001\nTotal 1250000"
    from pathlib import Path
    assert all(not Path(path).exists() for path in pipeline.paths)


def test_paddle_engine_requires_positive_timeout():
    with pytest.raises(ValueError, match="INVALID_OCR_TIMEOUT"):
        PaddleOcrEngine(Pipeline()).extract_text(b"x", timeout_seconds=0)


def test_missing_optional_dependency_has_stable_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "paddleocr", None)
    with pytest.raises(RuntimeError, match="PADDLEOCR_NOT_INSTALLED"):
        PaddleOcrEngine()
