"""Canonical document structure for evidence-grade understanding."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.x0 <= self.x1 <= 1.0 and 0.0 <= self.y0 <= self.y1 <= 1.0):
            raise ValueError("INVALID_NORMALIZED_BOUNDING_BOX")


class BlockKind(StrEnum):
    TEXT = "TEXT"
    TABLE = "TABLE"
    IMAGE = "IMAGE"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class TextBlock:
    block_id: str
    text: str
    bbox: BoundingBox
    reading_order: int
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.reading_order < 0:
            raise ValueError("INVALID_READING_ORDER")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("INVALID_CONFIDENCE")


@dataclass(frozen=True, slots=True)
class TableCell:
    row: int
    column: int
    text: str
    bbox: BoundingBox
    row_span: int = 1
    column_span: int = 1


@dataclass(frozen=True, slots=True)
class TableBlock:
    block_id: str
    bbox: BoundingBox
    reading_order: int
    cells: tuple[TableCell, ...]


@dataclass(frozen=True, slots=True)
class PageStructure:
    page_number: int
    width: float
    height: float
    text_blocks: tuple[TextBlock, ...] = ()
    tables: tuple[TableBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class StructuredDocument:
    observation_id: str
    observation_sha256: str
    pages: tuple[PageStructure, ...]
    component: str
    component_version: str
