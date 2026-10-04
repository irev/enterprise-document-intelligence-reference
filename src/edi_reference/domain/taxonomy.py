"""Versioned document taxonomy contract."""

from dataclasses import dataclass

from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE


@dataclass(frozen=True, slots=True)
class DocumentTaxonomy:
    taxonomy_id: str
    version: str
    document_types: frozenset[str]

    def __post_init__(self) -> None:
        if not self.taxonomy_id or not self.version:
            raise ValueError("TAXONOMY_ID_AND_VERSION_REQUIRED")
        if not self.document_types:
            raise ValueError("TAXONOMY_TYPES_REQUIRED")
        if UNKNOWN_DOCUMENT_TYPE in self.document_types:
            raise ValueError("UNKNOWN_IS_RESERVED")

    def allows(self, document_type: str) -> bool:
        return document_type == UNKNOWN_DOCUMENT_TYPE or document_type in self.document_types
