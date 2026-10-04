import pytest

from edi_reference.application.field_schema import validate_extracted_fields
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference
from edi_reference.domain.extraction import ExtractedField, FieldState
from edi_reference.domain.field_schema import ExtractionSchema, FieldDefinition


EV = (EvidenceReference("obs-1", "a"*64, 1, EvidenceKind.TEXT_BLOCK, block_id="b1"),)
SCHEMA = ExtractionSchema(
    "invoice",
    "1",
    (FieldDefinition("invoice_number", "identifier"), FieldDefinition("total_amount", "money")),
)


def extracted(name="invoice_number", value_type="identifier"):
    return ExtractedField(name, FieldState.PRESENT, "INV-001", value_type, .99, EV, "extractor", "1", "1")


def test_registered_field_and_type_are_allowed():
    validate_extracted_fields((extracted(),), schema=SCHEMA, extractor_schema_version="1")


def test_extractor_cannot_invent_field_name():
    with pytest.raises(ValueError, match="FIELD_NOT_IN_EXTRACTION_SCHEMA"):
        validate_extracted_fields((extracted("model_invented_field"),), schema=SCHEMA, extractor_schema_version="1")


def test_extractor_cannot_change_declared_value_type():
    with pytest.raises(ValueError, match="FIELD_VALUE_TYPE_MISMATCH"):
        validate_extracted_fields((extracted(value_type="money"),), schema=SCHEMA, extractor_schema_version="1")


def test_extractor_schema_version_must_match_selected_schema():
    with pytest.raises(ValueError, match="EXTRACTOR_SCHEMA_VERSION_MISMATCH"):
        validate_extracted_fields((extracted(),), schema=SCHEMA, extractor_schema_version="2")
