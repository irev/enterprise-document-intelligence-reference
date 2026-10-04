from datetime import UTC, datetime

import pytest

from edi_reference.domain.classification import ClassificationPrediction
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference
from edi_reference.domain.extraction import ExtractedField, FieldState
from edi_reference.domain.normalization import NormalizedField, NormalizedValue
from edi_reference.domain.processing_result import ProcessingResult


DIGEST = "a" * 64
EVIDENCE = EvidenceReference(
    "obs-1",
    DIGEST,
    1,
    EvidenceKind.TEXT_BLOCK,
    block_id="block-1",
    bbox=BoundingBox(0.1, 0.1, 0.5, 0.2),
    text_quote="INV-001",
)


def result(*, evidence=EVIDENCE, fields=None):
    classification = ClassificationPrediction(
        "INVOICE",
        0.98,
        "classifier",
        "1",
        "1",
        (evidence,),
    )
    if fields is None:
        extracted = ExtractedField(
            "invoice_number",
            FieldState.PRESENT,
            "INV-001",
            "string",
            0.99,
            (evidence,),
            "extractor",
            "1",
            "1",
        )
        fields = (
            NormalizedField(
                extracted,
                NormalizedValue("INV-001", "string", "identity", "1"),
            ),
        )
    return ProcessingResult(
        "result-1",
        "1",
        "run-1",
        "doc-1",
        "tenant-1",
        "app-1",
        "obs-1",
        DIGEST,
        "2.0",
        classification,
        fields,
        datetime.now(UTC),
    )


def test_processing_result_preserves_machine_provenance():
    actual = result()
    assert actual.processing_run_id == "run-1"
    assert actual.observation_id == "obs-1"
    assert actual.observation_sha256 == DIGEST
    assert actual.classification.model_version == "1"
    assert actual.fields[0].extracted.extractor_version == "1"
    assert actual.fields[0].normalized.normalizer_version == "1"


def test_processing_result_rejects_cross_observation_evidence():
    foreign = EvidenceReference(
        "obs-2", DIGEST, 1, EvidenceKind.TEXT_BLOCK, block_id="block-1"
    )
    with pytest.raises(ValueError, match="RESULT_EVIDENCE_OBSERVATION_MISMATCH"):
        result(evidence=foreign)


def test_processing_result_rejects_evidence_digest_mismatch():
    foreign = EvidenceReference(
        "obs-1", "b" * 64, 1, EvidenceKind.TEXT_BLOCK, block_id="block-1"
    )
    with pytest.raises(ValueError, match="RESULT_EVIDENCE_DIGEST_MISMATCH"):
        result(evidence=foreign)


def test_processing_result_rejects_duplicate_field_names():
    base = result().fields[0]
    with pytest.raises(ValueError, match="DUPLICATE_RESULT_FIELD_NAME"):
        result(fields=(base, base))


def test_processing_result_requires_valid_digest():
    base = result()
    with pytest.raises(ValueError, match="INVALID_PROCESSING_RESULT_DIGEST"):
        ProcessingResult(
            base.result_id,
            base.result_version,
            base.processing_run_id,
            base.document_id,
            base.tenant_id,
            base.application_id,
            base.observation_id,
            "not-a-digest",
            base.schema_version,
            base.classification,
            base.fields,
            base.created_at,
        )
