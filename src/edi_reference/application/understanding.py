"""Technology-neutral parser/OCR orchestration."""

from typing import Protocol

from edi_reference.domain.lineage import SourceObservation
from edi_reference.domain.understanding import (
    PageContent,
    UnderstandingFailureCode,
    UnderstandingPolicy,
    UnderstandingResult,
)


class ParserError(Exception):
    def __init__(self, code: UnderstandingFailureCode):
        self.code = code
        super().__init__(code.value)


class ParserAdapter(Protocol):
    component: str
    version: str

    def parse(self, content: bytes, *, policy: UnderstandingPolicy) -> tuple[PageContent, ...]: ...


def understand_document(
    observation: SourceObservation,
    content: bytes,
    *,
    parser: ParserAdapter,
    policy: UnderstandingPolicy,
) -> UnderstandingResult:
    if not content:
        raise ParserError(UnderstandingFailureCode.CORRUPT_DOCUMENT)

    try:
        pages = parser.parse(content, policy=policy)
    except ParserError:
        raise
    except Exception as exc:
        raise ParserError(UnderstandingFailureCode.PARSER_FAILED) from None

    if len(pages) > policy.max_pages:
        raise ParserError(UnderstandingFailureCode.PAGE_LIMIT_EXCEEDED)

    if sum(len(page.text) for page in pages) > policy.max_extracted_characters:
        raise ParserError(UnderstandingFailureCode.RESOURCE_LIMIT_EXCEEDED)

    expected = list(range(1, len(pages) + 1))
    if [page.page_number for page in pages] != expected:
        raise ParserError(UnderstandingFailureCode.PARSER_FAILED)

    return UnderstandingResult(
        observation_id=observation.observation_id,
        observation_sha256=observation.sha256,
        pages=pages,
        parser_component=parser.component,
        parser_version=parser.version,
    )
