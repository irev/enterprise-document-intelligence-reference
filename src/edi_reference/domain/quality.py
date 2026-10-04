"""RI-2.2 page quality and OCR-decision vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class TextOrigin(StrEnum):
    NATIVE = "NATIVE"
    OCR = "OCR"
    MIXED = "MIXED"
    NONE = "NONE"


class OcrDecision(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True, slots=True)
class PageQuality:
    page_number: int
    native_character_count: int
    native_text_coverage: float
    image_coverage: float
    rotation_degrees: int
    skew_degrees: float | None
    text_origin: TextOrigin

    def __post_init__(self) -> None:
        if self.page_number < 1 or self.native_character_count < 0:
            raise ValueError("INVALID_PAGE_QUALITY")
        if not 0.0 <= self.native_text_coverage <= 1.0:
            raise ValueError("INVALID_TEXT_COVERAGE")
        if not 0.0 <= self.image_coverage <= 1.0:
            raise ValueError("INVALID_IMAGE_COVERAGE")
        if self.rotation_degrees not in (0, 90, 180, 270):
            raise ValueError("INVALID_ROTATION")


@dataclass(frozen=True, slots=True)
class OcrDecisionPolicy:
    min_native_characters: int
    min_native_text_coverage: float
    image_dominance_threshold: float
    uncertain_margin: float = 0.05


@dataclass(frozen=True, slots=True)
class PageOcrAssessment:
    page_number: int
    decision: OcrDecision
    reasons: tuple[str, ...]
