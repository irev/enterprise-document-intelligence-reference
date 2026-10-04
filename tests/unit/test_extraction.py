import pytest

from edi_reference.application.extraction import extract_fields
from edi_reference.domain.document_structure import BoundingBox, PageStructure, StructuredDocument, TextBlock
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference
from edi_reference.domain.extraction import ExtractedField, FieldState


DOC = StructuredDocument(
    "obs-1", "a"*64,
    (PageStructure(1, 100, 100, (
        TextBlock("b1", "Invoice INV-001 Total Rp 1.250.000,00", BoundingBox(.1,.1,.9,.2), 0),
    ), ()),), "layout", "1",
)
EV = (EvidenceReference("obs-1", "a"*64, 1, EvidenceKind.TEXT_BLOCK, block_id="b1"),)


class Extractor:
    extractor_id = "synthetic-extractor"
    extractor_version = "1"
    schema_version = "1"
    def __init__(self, fields):
        self.fields = fields
    def extract(self, document, document_type):
        return tuple(self.fields)


def field(name, state, raw=None, evidence=(), confidence=None, value_type="string"):
    return ExtractedField(
        name, state, raw, value_type, confidence, evidence,
        "synthetic-extractor", "1", "1",
    )


def test_present_field_preserves_raw_value_and_evidence_only():
    result = extract_fields(
        DOC, document_type="INVOICE",
        extractor=Extractor([field("invoice_number", FieldState.PRESENT, "INV-001", EV, .98)]),
    )
    assert result[0].raw_value == "INV-001"
    assert result[0].evidence == EV
    assert not hasattr(result[0], "normalized_value")


def test_missing_field_cannot_invent_value():
    with pytest.raises(ValueError, match="MISSING_FIELD_MUST_NOT_INVENT_VALUE"):
        field("purchase_order_number", FieldState.MISSING, raw="PO-FAKE")


def test_present_field_requires_evidence():
    with pytest.raises(ValueError, match="PRESENT_FIELD_REQUIRES_RAW_VALUE_AND_EVIDENCE"):
        field("invoice_number", FieldState.PRESENT, "INV-001")


def test_explicit_null_is_distinct_from_missing_and_requires_evidence():
    result = field("reference", FieldState.EXPLICIT_NULL, raw="N/A", evidence=EV)
    assert result.state is FieldState.EXPLICIT_NULL


def test_duplicate_field_names_are_rejected():
    one = field("invoice_number", FieldState.PRESENT, "INV-001", EV)
    with pytest.raises(ValueError, match="DUPLICATE_FIELD_NAME"):
        extract_fields(DOC, document_type="INVOICE", extractor=Extractor([one, one]))


def test_explicit_null_requires_observed_raw_marker():
    with pytest.raises(ValueError, match="EXPLICIT_NULL_REQUIRES_RAW_VALUE_AND_EVIDENCE"):
        field("reference", FieldState.EXPLICIT_NULL, raw=None, evidence=EV)


def test_invalid_field_requires_raw_value_and_evidence():
    result = field("total_amount", FieldState.INVALID, raw="Rp ???", evidence=EV)
    assert result.state is FieldState.INVALID
    with pytest.raises(ValueError, match="INVALID_FIELD_REQUIRES_RAW_VALUE_AND_EVIDENCE"):
        field("total_amount", FieldState.INVALID, raw=None, evidence=EV)
    with pytest.raises(ValueError, match="INVALID_FIELD_REQUIRES_RAW_VALUE_AND_EVIDENCE"):
        field("total_amount", FieldState.INVALID, raw="Rp ???", evidence=())
