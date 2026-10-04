"""RI-3.1 evidence-bound field extraction vocabulary."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from edi_reference.domain.evidence import EvidenceReference


class FieldState(StrEnum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    EXPLICIT_NULL = "EXPLICIT_NULL"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class ExtractedField:
    field_name: str
    state: FieldState
    raw_value: str | None
    normalized_value: Any | None
    value_type: str
    confidence: float | None
    evidence: tuple[EvidenceReference, ...]
    extractor_id: str
    extractor_version: str
    schema_version: str

    def __post_init__(self) -> None:
        if not self.field_name or not self.value_type:
            raise ValueError("FIELD_METADATA_REQUIRED")
        if not self.extractor_id or not self.extractor_version or not self.schema_version:
            raise ValueError("EXTRACTION_PROVENANCE_REQUIRED")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("INVALID_FIELD_CONFIDENCE")
        if self.state is FieldState.PRESENT:
            if self.raw_value is None or self.normalized_value is None or not self.evidence:
                raise ValueError("PRESENT_FIELD_REQUIRES_VALUE_AND_EVIDENCE")
        elif self.state is FieldState.MISSING:
            if self.raw_value is not None or self.normalized_value is not None or self.evidence:
                raise ValueError("MISSING_FIELD_MUST_NOT_INVENT_VALUE")
        elif self.state is FieldState.EXPLICIT_NULL:
            if self.normalized_value is not None or not self.evidence:
                raise ValueError("EXPLICIT_NULL_REQUIRES_EVIDENCE")
