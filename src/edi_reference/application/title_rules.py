"""Deterministic heading-rule classifier (RI-4.10).

Rules are operator configuration, never document content. A rule matches the
leading text blocks of page 1 in reading order; the first matching rule wins.
No match yields no candidate, so the classification decision abstains to UNKNOWN.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from edi_reference.application.classification import RawClassification
from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE, ClassificationCandidate
from edi_reference.domain.document_structure import StructuredDocument, TextBlock
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference

MAX_RULES = 200
MAX_PATTERN_LENGTH = 300
MAX_HEADING_BLOCKS = 50


@dataclass(frozen=True, slots=True)
class TitleRule:
    pattern: str
    document_type: str

    def __post_init__(self) -> None:
        if not self.pattern or len(self.pattern) > MAX_PATTERN_LENGTH:
            raise ValueError("INVALID_TITLE_RULE_PATTERN")
        if not self.document_type or self.document_type == UNKNOWN_DOCUMENT_TYPE:
            raise ValueError("INVALID_TITLE_RULE_DOCUMENT_TYPE")
        try:
            re.compile(self.pattern)
        except re.error:
            raise ValueError("INVALID_TITLE_RULE_PATTERN") from None


@dataclass(frozen=True, slots=True)
class TitleRuleProfile:
    profile_id: str
    version: str
    taxonomy_version: str
    rules: tuple[TitleRule, ...]
    heading_blocks: int = 8

    def __post_init__(self) -> None:
        if not self.profile_id or not self.version or not self.taxonomy_version:
            raise ValueError("TITLE_RULE_PROFILE_PROVENANCE_REQUIRED")
        if not self.rules or len(self.rules) > MAX_RULES:
            raise ValueError("INVALID_TITLE_RULE_COUNT")
        if not 1 <= self.heading_blocks <= MAX_HEADING_BLOCKS:
            raise ValueError("INVALID_HEADING_BLOCKS")


def load_title_rule_profile(path: Path) -> TitleRuleProfile:
    return title_rule_profile_from_dict(json.loads(path.read_text(encoding="utf-8")))


def title_rule_profile_from_dict(raw: object) -> TitleRuleProfile:
    if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
        raise ValueError("INVALID_TITLE_RULE_PROFILE")
    try:
        return TitleRuleProfile(
            profile_id=str(raw["profile_id"]),
            version=str(raw["version"]),
            taxonomy_version=str(raw["taxonomy_version"]),
            heading_blocks=int(raw.get("heading_blocks", 8)),
            rules=tuple(TitleRule(str(item["pattern"]), str(item["document_type"])) for item in raw["rules"]),
        )
    except (KeyError, TypeError):
        raise ValueError("INVALID_TITLE_RULE_PROFILE") from None


class TitleRuleClassifier:
    """ClassifierAdapter whose only output is a rule match with source evidence."""

    def __init__(self, profile: TitleRuleProfile) -> None:
        self.model_id = f"title-rules/{profile.profile_id}"
        self.model_version = profile.version
        self.taxonomy_version = profile.taxonomy_version
        self._heading_blocks = profile.heading_blocks
        self._rules = tuple(
            (re.compile(rule.pattern, re.IGNORECASE), rule.document_type) for rule in profile.rules
        )

    def classify(self, document: StructuredDocument) -> RawClassification:
        if not document.pages:
            return RawClassification((), ())
        blocks = sorted(document.pages[0].text_blocks, key=lambda block: block.reading_order)
        heading = blocks[: self._heading_blocks]
        # Headings are often split across OCR lines, so match the joined text and
        # cite every block the match spans.
        joined, spans = _join(heading)
        for pattern, document_type in self._rules:
            match = pattern.search(joined)
            if match is None:
                continue
            evidence = tuple(
                EvidenceReference(
                    observation_id=document.observation_id,
                    observation_sha256=document.observation_sha256,
                    page_number=1,
                    kind=EvidenceKind.TEXT_BLOCK,
                    block_id=block.block_id,
                    text_quote=block.text,
                )
                for block, start, end in spans
                if start < match.end() and match.start() < end
            )
            return RawClassification((ClassificationCandidate(document_type, 1.0),), evidence)
        return RawClassification((), ())


def _join(blocks: list[TextBlock]) -> tuple[str, tuple[tuple[TextBlock, int, int], ...]]:
    parts: list[str] = []
    spans: list[tuple[TextBlock, int, int]] = []
    offset = 0
    for block in blocks:
        spans.append((block, offset, offset + len(block.text)))
        parts.append(block.text)
        offset += len(block.text) + 1
    return " ".join(parts), tuple(spans)
