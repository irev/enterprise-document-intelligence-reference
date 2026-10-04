"""Validate classifier output against an explicit taxonomy."""

from edi_reference.domain.classification import ClassificationCandidate
from edi_reference.domain.taxonomy import DocumentTaxonomy


def validate_candidates(
    candidates: tuple[ClassificationCandidate, ...],
    *,
    taxonomy: DocumentTaxonomy,
    classifier_taxonomy_version: str,
) -> None:
    if classifier_taxonomy_version != taxonomy.version:
        raise ValueError("CLASSIFIER_TAXONOMY_VERSION_MISMATCH")
    for candidate in candidates:
        if not taxonomy.allows(candidate.document_type):
            raise ValueError("DOCUMENT_TYPE_NOT_IN_TAXONOMY")
