"""Synthetic parser adapter for contract tests only."""

from dataclasses import dataclass

from edi_reference.application.understanding import ParserError
from edi_reference.domain.understanding import PageContent, UnderstandingFailureCode, UnderstandingPolicy


@dataclass
class SyntheticParser:
    component: str = "synthetic-parser"
    version: str = "1.0"
    pages: int = 1
    fail_with: UnderstandingFailureCode | None = None

    def parse(self, content: bytes, *, policy: UnderstandingPolicy) -> tuple[PageContent, ...]:
        if self.fail_with:
            raise ParserError(self.fail_with)
        return tuple(
            PageContent(
                page_number=i,
                text=f"synthetic page {i}",
                parser_component=self.component,
                parser_version=self.version,
            )
            for i in range(1, self.pages + 1)
        )
