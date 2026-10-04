"""Versioned extraction field-schema contract."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    field_name: str
    value_type: str

    def __post_init__(self) -> None:
        if not self.field_name or not self.value_type:
            raise ValueError("FIELD_DEFINITION_REQUIRED")


@dataclass(frozen=True, slots=True)
class ExtractionSchema:
    schema_id: str
    version: str
    fields: tuple[FieldDefinition, ...]

    def __post_init__(self) -> None:
        if not self.schema_id or not self.version or not self.fields:
            raise ValueError("EXTRACTION_SCHEMA_REQUIRED")
        names = [field.field_name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("DUPLICATE_FIELD_DEFINITION")

    def definition(self, field_name: str) -> FieldDefinition | None:
        return next((field for field in self.fields if field.field_name == field_name), None)
