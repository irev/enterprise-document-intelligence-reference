"""Resolve and validate evidence against canonical document structure."""

from edi_reference.domain.document_structure import StructuredDocument
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference


class InvalidEvidenceReference(ValueError):
    pass


def validate_evidence(document: StructuredDocument, evidence: EvidenceReference) -> None:
    if evidence.observation_id != document.observation_id:
        raise InvalidEvidenceReference("EVIDENCE_OBSERVATION_MISMATCH")
    if evidence.observation_sha256.lower() != document.observation_sha256.lower():
        raise InvalidEvidenceReference("EVIDENCE_DIGEST_MISMATCH")
    if evidence.page_number > len(document.pages):
        raise InvalidEvidenceReference("EVIDENCE_PAGE_NOT_FOUND")

    page = document.pages[evidence.page_number - 1]

    if evidence.kind is EvidenceKind.TEXT_BLOCK:
        block = next((b for b in page.text_blocks if b.block_id == evidence.block_id), None)
        if block is None:
            raise InvalidEvidenceReference("EVIDENCE_BLOCK_NOT_FOUND")
        _validate_quote(evidence.text_quote, block.text)
        return

    if evidence.kind is EvidenceKind.TABLE_CELL:
        table = next((t for t in page.tables if t.block_id == evidence.block_id), None)
        if table is None:
            raise InvalidEvidenceReference("EVIDENCE_TABLE_NOT_FOUND")
        cell = next(
            (c for c in table.cells if c.row == evidence.row and c.column == evidence.column),
            None,
        )
        if cell is None:
            raise InvalidEvidenceReference("EVIDENCE_CELL_NOT_FOUND")
        _validate_quote(evidence.text_quote, cell.text)
        return

    if evidence.kind is EvidenceKind.REGION:
        return

    raise InvalidEvidenceReference("UNSUPPORTED_EVIDENCE_KIND")


def _validate_quote(quote: str | None, source_text: str) -> None:
    if quote is not None and quote not in source_text:
        raise InvalidEvidenceReference("EVIDENCE_QUOTE_MISMATCH")
