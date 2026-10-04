"""Map structured OCR results to the canonical document structure."""

from edi_reference.domain.document_structure import PageStructure, StructuredDocument, TextBlock
from edi_reference.domain.ocr import OcrResult


def structured_ocr_to_document(
    result: OcrResult,
    *,
    observation_id: str,
    observation_sha256: str,
    component: str,
    component_version: str,
) -> StructuredDocument:
    pages = tuple(
        PageStructure(
            page_number=page.page_number,
            width=page.width,
            height=page.height,
            text_blocks=tuple(
                TextBlock(
                    block_id=f"ocr-p{page.page_number}-l{index}",
                    text=line.text,
                    bbox=line.bbox,
                    reading_order=index - 1,
                    confidence=line.confidence,
                )
                for index, line in enumerate(page.lines, start=1)
            ),
            tables=(),
        )
        for page in result.pages
    )
    return StructuredDocument(
        observation_id=observation_id,
        observation_sha256=observation_sha256,
        pages=pages,
        component=component,
        component_version=component_version,
    )
