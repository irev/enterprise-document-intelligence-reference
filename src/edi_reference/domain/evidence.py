"""Evidence references linking predictions to immutable source structure."""

from dataclasses import dataclass
from enum import StrEnum

from edi_reference.domain.document_structure import BoundingBox


class EvidenceKind(StrEnum):
    TEXT_BLOCK = "TEXT_BLOCK"
    TABLE_CELL = "TABLE_CELL"
    REGION = "REGION"


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    observation_id: str
    observation_sha256: str
    page_number: int
    kind: EvidenceKind
    block_id: str | None = None
    row: int | None = None
    column: int | None = None
    bbox: BoundingBox | None = None
    text_quote: str | None = None

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("INVALID_EVIDENCE_PAGE")
        if self.kind is EvidenceKind.TEXT_BLOCK and not self.block_id:
            raise ValueError("TEXT_BLOCK_ID_REQUIRED")
        if self.kind is EvidenceKind.TABLE_CELL:
            if not self.block_id or self.row is None or self.column is None:
                raise ValueError("TABLE_CELL_REFERENCE_REQUIRED")
        if self.kind is EvidenceKind.REGION and self.bbox is None:
            raise ValueError("REGION_BBOX_REQUIRED")
