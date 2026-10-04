import pytest

from edi_reference.application.taxonomy import validate_candidates
from edi_reference.domain.classification import ClassificationCandidate
from edi_reference.domain.taxonomy import DocumentTaxonomy


TAXONOMY = DocumentTaxonomy(
    taxonomy_id="core-documents",
    version="1",
    document_types=frozenset({"INVOICE", "PURCHASE_ORDER", "CONTRACT"}),
)


def test_registered_document_type_is_allowed():
    validate_candidates(
        (ClassificationCandidate("INVOICE", .95),),
        taxonomy=TAXONOMY,
        classifier_taxonomy_version="1",
    )


def test_unknown_is_reserved_abstention_and_allowed():
    validate_candidates(
        (ClassificationCandidate("UNKNOWN", .80),),
        taxonomy=TAXONOMY,
        classifier_taxonomy_version="1",
    )


def test_classifier_cannot_invent_document_type():
    with pytest.raises(ValueError, match="DOCUMENT_TYPE_NOT_IN_TAXONOMY"):
        validate_candidates(
            (ClassificationCandidate("CUSTOMER_MAGIC_INVOICE", .99),),
            taxonomy=TAXONOMY,
            classifier_taxonomy_version="1",
        )


def test_taxonomy_version_must_match_classifier():
    with pytest.raises(ValueError, match="CLASSIFIER_TAXONOMY_VERSION_MISMATCH"):
        validate_candidates(
            (ClassificationCandidate("INVOICE", .95),),
            taxonomy=TAXONOMY,
            classifier_taxonomy_version="2",
        )


def test_unknown_cannot_be_configured_as_regular_type():
    with pytest.raises(ValueError, match="UNKNOWN_IS_RESERVED"):
        DocumentTaxonomy("bad", "1", frozenset({"INVOICE", "UNKNOWN"}))
