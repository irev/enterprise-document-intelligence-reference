"""Validation of canonical structure emitted by parser/OCR adapters."""

from edi_reference.domain.document_structure import PageStructure, StructuredDocument
from edi_reference.domain.lineage import ScopedObservation


class InvalidDocumentStructure(ValueError):
    pass


def validate_structured_document(
    observation: ScopedObservation,
    document: StructuredDocument,
) -> None:
    if document.observation_id != observation.observation_id:
        raise InvalidDocumentStructure("OBSERVATION_ID_MISMATCH")
    if document.observation_sha256.lower() != observation.sha256.lower():
        raise InvalidDocumentStructure("OBSERVATION_DIGEST_MISMATCH")
    if not document.component or not document.component_version:
        raise InvalidDocumentStructure("COMPONENT_PROVENANCE_REQUIRED")

    expected_pages = list(range(1, len(document.pages) + 1))
    if [page.page_number for page in document.pages] != expected_pages:
        raise InvalidDocumentStructure("INVALID_PAGE_SEQUENCE")

    seen_ids: set[str] = set()
    for page in document.pages:
        _validate_page(page, seen_ids)


def _validate_page(page: PageStructure, seen_ids: set[str]) -> None:
    if page.width <= 0 or page.height <= 0:
        raise InvalidDocumentStructure("INVALID_PAGE_DIMENSIONS")

    orders: list[int] = []
    for block in page.text_blocks:
        if block.block_id in seen_ids:
            raise InvalidDocumentStructure("DUPLICATE_BLOCK_ID")
        seen_ids.add(block.block_id)
        orders.append(block.reading_order)

    for table in page.tables:
        if table.block_id in seen_ids:
            raise InvalidDocumentStructure("DUPLICATE_BLOCK_ID")
        seen_ids.add(table.block_id)
        orders.append(table.reading_order)
        seen_cells: set[tuple[int, int]] = set()
        for cell in table.cells:
            if cell.row < 0 or cell.column < 0 or cell.row_span < 1 or cell.column_span < 1:
                raise InvalidDocumentStructure("INVALID_TABLE_CELL")
            key = (cell.row, cell.column)
            if key in seen_cells:
                raise InvalidDocumentStructure("DUPLICATE_TABLE_CELL")
            seen_cells.add(key)

    if len(orders) != len(set(orders)):
        raise InvalidDocumentStructure("DUPLICATE_READING_ORDER")
