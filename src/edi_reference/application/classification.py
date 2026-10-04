"""Safe classification decision with mandatory UNKNOWN abstention."""

from dataclasses import dataclass
from typing import Protocol

from edi_reference.application.evidence import validate_evidence
from edi_reference.domain.classification import (
    UNKNOWN_DOCUMENT_TYPE,
    ClassificationCandidate,
    ClassificationPrediction,
)
from edi_reference.domain.document_structure import StructuredDocument
from edi_reference.domain.evidence import EvidenceReference
from edi_reference.domain.taxonomy import DocumentTaxonomy
from edi_reference.application.taxonomy import validate_candidates


@dataclass(frozen=True, slots=True)
class ClassificationPolicy:
    accept_threshold: float
    minimum_margin: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.accept_threshold <= 1.0:
            raise ValueError("INVALID_ACCEPT_THRESHOLD")
        if not 0.0 <= self.minimum_margin <= 1.0:
            raise ValueError("INVALID_MINIMUM_MARGIN")


@dataclass(frozen=True, slots=True)
class RawClassification:
    candidates: tuple[ClassificationCandidate, ...]
    evidence: tuple[EvidenceReference, ...]


class ClassifierAdapter(Protocol):
    model_id: str
    model_version: str
    taxonomy_version: str
    def classify(self, document: StructuredDocument) -> RawClassification: ...


def classify_document(
    document: StructuredDocument,
    *,
    classifier: ClassifierAdapter,
    policy: ClassificationPolicy,
    taxonomy: DocumentTaxonomy | None = None,
) -> ClassificationPrediction:
    raw = classifier.classify(document)
    if taxonomy is not None:
        validate_candidates(
            raw.candidates,
            taxonomy=taxonomy,
            classifier_taxonomy_version=classifier.taxonomy_version,
        )
    if not raw.candidates:
        return _unknown(classifier, raw.evidence)

    candidates = tuple(sorted(raw.candidates, key=lambda item: item.confidence, reverse=True))
    for evidence in raw.evidence:
        validate_evidence(document, evidence)

    top = candidates[0]
    second = candidates[1].confidence if len(candidates) > 1 else 0.0
    if (
        top.document_type == UNKNOWN_DOCUMENT_TYPE
        or top.confidence < policy.accept_threshold
        or top.confidence - second < policy.minimum_margin
    ):
        return _unknown(classifier, raw.evidence, candidates)

    return ClassificationPrediction(
        document_type=top.document_type,
        confidence=top.confidence,
        model_id=classifier.model_id,
        model_version=classifier.model_version,
        taxonomy_version=classifier.taxonomy_version,
        evidence=raw.evidence,
        alternatives=candidates[1:],
    )


def _unknown(classifier, evidence, candidates=()):
    confidence = candidates[0].confidence if candidates else 0.0
    return ClassificationPrediction(
        document_type=UNKNOWN_DOCUMENT_TYPE,
        confidence=confidence,
        model_id=classifier.model_id,
        model_version=classifier.model_version,
        taxonomy_version=classifier.taxonomy_version,
        evidence=evidence,
        alternatives=tuple(candidates),
    )
