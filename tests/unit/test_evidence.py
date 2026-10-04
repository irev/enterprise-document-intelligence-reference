import pytest

from edi_reference.application.evidence import InvalidEvidenceReference, validate_evidence
from edi_reference.domain.document_structure import (
    BoundingBox, PageStructure, StructuredDocument, TableBlock, TableCell, TextBlock,
)
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference


DOC = StructuredDocument(
    observation_id="obs-1", observation_sha256="a"*64,
    component="layout", component_version="1",
    pages=(PageStructure(
        page_number=1, width=100, height=100,
        text_blocks=(TextBlock("b1", "Invoice INV-001", BoundingBox(.1,.1,.5,.2), 0),),
        tables=(TableBlock("t1", BoundingBox(.1,.3,.9,.8), 1, (
            TableCell(0, 0, "Amount", BoundingBox(.1,.3,.4,.4)),
            TableCell(0, 1, "1250000", BoundingBox(.4,.3,.8,.4)),
        )),),
    ),),
)


def test_text_evidence_resolves_to_source_block():
    evidence = EvidenceReference("obs-1", "a"*64, 1, EvidenceKind.TEXT_BLOCK, block_id="b1", text_quote="INV-001")
    validate_evidence(DOC, evidence)


def test_table_cell_evidence_resolves_to_exact_cell():
    evidence = EvidenceReference(
        "obs-1", "a"*64, 1, EvidenceKind.TABLE_CELL,
        block_id="t1", row=0, column=1, text_quote="1250000",
    )
    validate_evidence(DOC, evidence)


def test_wrong_digest_cannot_be_rebound_to_structure():
    evidence = EvidenceReference("obs-1", "b"*64, 1, EvidenceKind.TEXT_BLOCK, block_id="b1")
    with pytest.raises(InvalidEvidenceReference, match="EVIDENCE_DIGEST_MISMATCH"):
        validate_evidence(DOC, evidence)


def test_quote_must_exist_in_referenced_source_text():
    evidence = EvidenceReference("obs-1", "a"*64, 1, EvidenceKind.TEXT_BLOCK, block_id="b1", text_quote="PO-999")
    with pytest.raises(InvalidEvidenceReference, match="EVIDENCE_QUOTE_MISMATCH"):
        validate_evidence(DOC, evidence)


def test_missing_table_cell_is_rejected():
    evidence = EvidenceReference("obs-1", "a"*64, 1, EvidenceKind.TABLE_CELL, block_id="t1", row=9, column=9)
    with pytest.raises(InvalidEvidenceReference, match="EVIDENCE_CELL_NOT_FOUND"):
        validate_evidence(DOC, evidence)
