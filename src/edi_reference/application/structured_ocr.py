"""Map structured OCR results to the canonical document structure."""

from edi_reference.domain.document_structure import PageStructure, StructuredDocument, TextBlock
from edi_reference.domain.ocr import OcrResult
from edi_reference.domain.lineage import SourceObservation
from edi_reference.application.structure import validate_structured_document


def structured_ocr_to_document(
    result: OcrResult,
    *,
    observation: SourceObservation,
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
    document = StructuredDocument(
        observation_id=observation.observation_id,
        observation_sha256=observation.sha256,
        pages=pages,
        component=component,
        component_version=component_version,
    )
    validate_structured_document(observation, document)
    return document
