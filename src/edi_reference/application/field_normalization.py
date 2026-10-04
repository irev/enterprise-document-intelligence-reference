"""Normalize extracted raw fields as a distinct pipeline stage."""

from edi_reference.application.normalization import NormalizationRegistry
from edi_reference.domain.extraction import ExtractedField, FieldState
from edi_reference.domain.normalization import NormalizedField


def normalize_extracted_field(
    field: ExtractedField,
    *,
    registry: NormalizationRegistry,
    normalizer_id: str,
    version: str,
) -> NormalizedField:
    if field.state is not FieldState.PRESENT:
        return NormalizedField(field, None)
    if field.raw_value is None:
        raise ValueError("PRESENT_FIELD_REQUIRES_RAW_VALUE")
    normalized = registry.normalize(
        field.raw_value, normalizer_id=normalizer_id, version=version
    )
    return NormalizedField(field, normalized)
