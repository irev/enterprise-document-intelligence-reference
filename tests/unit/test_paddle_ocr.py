import sys

import pytest

from edi_reference.adapters.paddle_ocr import PaddleOcrEngine, paddle_results_to_ocr_result


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


def test_paddle_geometry_is_normalized_into_structured_ocr():
    raw = [{
        "res": {
            "rec_texts": ["Invoice INV-001", "Total 1250000"],
            "rec_boxes": [[100, 140, 500, 280], [200, 980, 700, 1120]],
            "rec_scores": [.97, .91],
            "input_img_shape": [1400, 1000, 3],
        }
    }]
    result = paddle_results_to_ocr_result(raw)
    assert result.pages[0].width == 1000
    assert result.pages[0].height == 1400
    assert result.pages[0].lines[0].bbox.x0 == pytest.approx(.1)
    assert result.pages[0].lines[0].bbox.y0 == pytest.approx(.1)
    assert result.pages[0].lines[0].confidence == pytest.approx(.97)


def test_paddle_geometry_requires_page_dimensions():
    raw = [{"res": {"rec_texts": ["x"], "rec_boxes": [[0, 0, 1, 1]]}}]
    with pytest.raises(ValueError, match="MISSING_PADDLE_OCR_PAGE_DIMENSIONS"):
        paddle_results_to_ocr_result(raw)


def test_paddle_geometry_rejects_misaligned_confidence():
    raw = [{
        "res": {
            "rec_texts": ["a", "b"],
            "rec_boxes": [[0, 0, 10, 10], [10, 10, 20, 20]],
            "rec_scores": [.9],
            "input_img_shape": [100, 100, 3],
        }
    }]
    with pytest.raises(ValueError, match="INCOMPLETE_PADDLE_OCR_CONFIDENCE"):
        paddle_results_to_ocr_result(raw)
