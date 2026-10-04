"""RI-2 document-understanding contracts."""

from dataclasses import dataclass
from enum import StrEnum


class UnderstandingFailureCode(StrEnum):
    ENCRYPTED_DOCUMENT_UNSUPPORTED = "ENCRYPTED_DOCUMENT_UNSUPPORTED"
    CORRUPT_DOCUMENT = "CORRUPT_DOCUMENT"
    PAGE_LIMIT_EXCEEDED = "PAGE_LIMIT_EXCEEDED"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    PARSER_TIMEOUT = "PARSER_TIMEOUT"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    PARSER_FAILED = "PARSER_FAILED"
    OCR_FAILED = "OCR_FAILED"


@dataclass(frozen=True, slots=True)
class UnderstandingPolicy:
    max_pages: int
    parser_timeout_seconds: int
    ocr_timeout_seconds: int
    max_extracted_characters: int


@dataclass(frozen=True, slots=True)
class PageContent:
    page_number: int
    text: str
    parser_component: str
    parser_version: str
    ocr_component: str | None = None
    ocr_version: str | None = None


@dataclass(frozen=True, slots=True)
class UnderstandingResult:
    observation_id: str
    observation_sha256: str
    pages: tuple[PageContent, ...]
    parser_component: str
    parser_version: str
    failure_code: UnderstandingFailureCode | None = None
