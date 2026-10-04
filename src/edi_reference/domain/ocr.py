"""Provider-neutral structured OCR result vocabulary."""

from dataclasses import dataclass

from edi_reference.domain.document_structure import BoundingBox


@dataclass(frozen=True, slots=True)
class OcrTextLine:
    text: str
    bbox: BoundingBox
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("EMPTY_OCR_TEXT_LINE")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("INVALID_OCR_CONFIDENCE")


@dataclass(frozen=True, slots=True)
class OcrPage:
    page_number: int
    width: float
    height: float
    lines: tuple[OcrTextLine, ...]

    def __post_init__(self) -> None:
        if self.page_number < 1 or self.width <= 0 or self.height <= 0:
            raise ValueError("INVALID_OCR_PAGE")


@dataclass(frozen=True, slots=True)
class OcrResult:
    pages: tuple[OcrPage, ...]

    def __post_init__(self) -> None:
        if not self.pages:
            raise ValueError("EMPTY_OCR_RESULT")
        numbers = [page.page_number for page in self.pages]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("NON_CONTIGUOUS_OCR_PAGES")
