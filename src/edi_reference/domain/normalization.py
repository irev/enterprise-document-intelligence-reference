"""RI-3.2 deterministic normalization contracts."""

from dataclasses import dataclass
from typing import Any, Protocol


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


class Normalizer(Protocol):
    normalizer_id: str
    version: str
    value_type: str
    def normalize(self, raw_value: str) -> Any: ...
