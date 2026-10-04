"""RI-3.2 deterministic normalization contracts."""

from dataclasses import dataclass
from typing import Any, Protocol

from edi_reference.domain.extraction import ExtractedField


class NormalizationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    value: Any
    value_type: str
    normalizer_id: str
    normalizer_version: str


@dataclass(frozen=True, slots=True)
class NormalizedField:
    extracted: ExtractedField
    normalized: NormalizedValue | None

    @property
    def field_name(self) -> str:
        return self.extracted.field_name


class Normalizer(Protocol):
    normalizer_id: str
    version: str
    value_type: str
    def normalize(self, raw_value: str) -> Any: ...
