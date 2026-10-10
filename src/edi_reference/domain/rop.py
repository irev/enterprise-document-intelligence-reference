"""Local operator-workspace values, separate from canonical export contracts."""

from dataclasses import dataclass
from typing import Protocol

from edi_reference.domain.ocr import OcrResult


@dataclass(frozen=True, slots=True)
class RoutingPolicy:
    minimum_ocr_confidence: float = 0.85
    maximum_lines: int = 80
    minimum_short_side: int = 900


class WorkspaceEngine(Protocol):
    def prepare(self, content: bytes, media_type: str) -> tuple[bytes, ...]: ...
    def recognize(self, pages: tuple[bytes, ...]) -> OcrResult: ...
    def extract_layout(self, pages: tuple[bytes, ...]) -> dict: ...


FIELD_LABELS = {
    "document_number": "Nomor dokumen",
    "document_date": "Tanggal dokumen",
    "total_idr": "Total (IDR)",
    "npwp": "NPWP",
}
