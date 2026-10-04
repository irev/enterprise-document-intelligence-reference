"""Validate extractor output against canonical source evidence."""

from typing import Protocol

from edi_reference.application.evidence import validate_evidence
from edi_reference.application.field_schema import validate_extracted_fields
from edi_reference.domain.document_structure import StructuredDocument
from edi_reference.domain.extraction import ExtractedField
from edi_reference.domain.field_schema import ExtractionSchema


class ExtractorAdapter(Protocol):
    extractor_id: str
    extractor_version: str
    schema_version: str
    def extract(self, document: StructuredDocument, document_type: str) -> tuple[ExtractedField, ...]: ...


def extract_fields(
    document: StructuredDocument,
    *,
    document_type: str,
    extractor: ExtractorAdapter,
    schema: ExtractionSchema,
) -> tuple[ExtractedField, ...]:
    fields = extractor.extract(document, document_type)
    validate_extracted_fields(
        fields,
        schema=schema,
        extractor_schema_version=extractor.schema_version,
    )
    names: set[str] = set()
    for field in fields:
        if field.field_name in names:
            raise ValueError("DUPLICATE_FIELD_NAME")
        names.add(field.field_name)

        if field.extractor_id != extractor.extractor_id:
            raise ValueError("EXTRACTOR_ID_MISMATCH")
        if field.extractor_version != extractor.extractor_version:
            raise ValueError("EXTRACTOR_VERSION_MISMATCH")
        if field.schema_version != extractor.schema_version:
            raise ValueError("EXTRACTION_SCHEMA_VERSION_MISMATCH")

        for evidence in field.evidence:
            validate_evidence(document, evidence)
    return fields
