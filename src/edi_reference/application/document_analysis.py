"""Image analysis port using the existing canonical prediction vocabulary.

This is an internal result, not a new public document-result schema or a
business decision. Evidence coordinates are normalized top-left XYXY.
"""

from dataclasses import dataclass
from typing import Protocol

from edi_reference.domain.classification import ClassificationPrediction
from edi_reference.domain.extraction import ExtractedField


@dataclass(frozen=True, slots=True)
class DocumentAnalysis:
    observation_id: str
    observation_sha256: str
    classification: ClassificationPrediction
    fields: tuple[ExtractedField, ...]


class DocumentAnalyzer(Protocol):
    def analyze(self, image: bytes, *, media_type: str, observation_id: str) -> DocumentAnalysis: ...
