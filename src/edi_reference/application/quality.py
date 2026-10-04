"""Deterministic OCR routing based on multiple observable quality signals."""

from edi_reference.domain.quality import OcrDecision, OcrDecisionPolicy, PageOcrAssessment, PageQuality


def assess_ocr_need(page: PageQuality, policy: OcrDecisionPolicy) -> PageOcrAssessment:
    reasons: list[str] = []

    low_chars = page.native_character_count < policy.min_native_characters
    low_coverage = page.native_text_coverage < policy.min_native_text_coverage
    image_dominant = page.image_coverage >= policy.image_dominance_threshold

    if low_chars:
        reasons.append("LOW_NATIVE_CHARACTER_COUNT")
    if low_coverage:
        reasons.append("LOW_NATIVE_TEXT_COVERAGE")
    if image_dominant:
        reasons.append("IMAGE_DOMINANT")
    if page.rotation_degrees != 0:
        reasons.append("ROTATED_PAGE")
    if page.skew_degrees is not None and abs(page.skew_degrees) >= 2.0:
        reasons.append("SKEW_DETECTED")

    # Strong evidence for OCR requires more than a single weak signal.
    strong_signals = sum((low_chars, low_coverage, image_dominant))
    if strong_signals >= 2:
        return PageOcrAssessment(page.page_number, OcrDecision.REQUIRED, tuple(reasons))

    near_coverage = abs(page.native_text_coverage - policy.min_native_text_coverage) <= policy.uncertain_margin
    near_image = abs(page.image_coverage - policy.image_dominance_threshold) <= policy.uncertain_margin
    if strong_signals == 1 or near_coverage or near_image:
        return PageOcrAssessment(page.page_number, OcrDecision.REVIEW_REQUIRED, tuple(reasons or ["BORDERLINE_QUALITY"]))

    return PageOcrAssessment(page.page_number, OcrDecision.NOT_REQUIRED, tuple(reasons))


def assess_document_ocr(
    pages: tuple[PageQuality, ...], policy: OcrDecisionPolicy
) -> tuple[PageOcrAssessment, ...]:
    return tuple(assess_ocr_need(page, policy) for page in pages)
