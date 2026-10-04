import pytest

from edi_reference.application.quality import assess_ocr_need
from edi_reference.domain.quality import OcrDecision, OcrDecisionPolicy, PageQuality, TextOrigin


POLICY = OcrDecisionPolicy(
    min_native_characters=40,
    min_native_text_coverage=.10,
    image_dominance_threshold=.80,
)


def page(chars=200, text=.4, image=.2, rotation=0, skew=0.0):
    return PageQuality(1, chars, text, image, rotation, skew, TextOrigin.NATIVE)


def test_good_native_page_does_not_require_ocr():
    result = assess_ocr_need(page(), POLICY)
    assert result.decision is OcrDecision.NOT_REQUIRED


def test_multiple_strong_signals_require_ocr():
    result = assess_ocr_need(page(chars=3, text=.01, image=.95), POLICY)
    assert result.decision is OcrDecision.REQUIRED
    assert "IMAGE_DOMINANT" in result.reasons


def test_single_signal_does_not_force_ocr():
    result = assess_ocr_need(page(chars=20, text=.4, image=.2), POLICY)
    assert result.decision is OcrDecision.REVIEW_REQUIRED


def test_borderline_measurement_is_not_silently_forced():
    result = assess_ocr_need(page(chars=200, text=.11, image=.2), POLICY)
    assert result.decision is OcrDecision.REVIEW_REQUIRED


@pytest.mark.parametrize("coverage", [-.1, 1.1])
def test_quality_ranges_are_validated(coverage):
    with pytest.raises(ValueError, match="INVALID_TEXT_COVERAGE"):
        page(text=coverage)
