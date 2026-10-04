"""Validate extracted fields against the selected extraction schema."""

from edi_reference.domain.extraction import ExtractedField
from edi_reference.domain.field_schema import ExtractionSchema


def validate_extracted_fields(
    fields: tuple[ExtractedField, ...],
    *,
    schema: ExtractionSchema,
    extractor_schema_version: str,
) -> None:
    if extractor_schema_version != schema.version:
        raise ValueError("EXTRACTOR_SCHEMA_VERSION_MISMATCH")
    for field in fields:
        definition = schema.definition(field.field_name)
        if definition is None:
            raise ValueError("FIELD_NOT_IN_EXTRACTION_SCHEMA")
        if field.value_type != definition.value_type:
            raise ValueError("FIELD_VALUE_TYPE_MISMATCH")
