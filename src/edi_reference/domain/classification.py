"""RI-3 classification vocabulary."""

from dataclasses import dataclass

from edi_reference.domain.evidence import EvidenceReference


UNKNOWN_DOCUMENT_TYPE = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ClassificationCandidate:
    document_type: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.document_type:
            raise ValueError("DOCUMENT_TYPE_REQUIRED")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("INVALID_CLASSIFICATION_CONFIDENCE")


@dataclass(frozen=True, slots=True)
class ClassificationPrediction:
    document_type: str
    confidence: float
    model_id: str
    model_version: str
    taxonomy_version: str
    evidence: tuple[EvidenceReference, ...]
    alternatives: tuple[ClassificationCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("INVALID_CLASSIFICATION_CONFIDENCE")
        if not self.model_id or not self.model_version or not self.taxonomy_version:
            raise ValueError("CLASSIFICATION_PROVENANCE_REQUIRED")
