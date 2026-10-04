"""Convert provider-neutral OCR text output into canonical document structure."""

from edi_reference.domain.document_structure import BoundingBox, PageStructure, StructuredDocument, TextBlock
from edi_reference.domain.invocation import InvocationResult


def ocr_text_to_structure(
    result: InvocationResult,
    *,
    observation_id: str,
    observation_sha256: str,
    component: str,
    component_version: str,
) -> StructuredDocument:
    try:
        text = result.output_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("OCR_OUTPUT_NOT_UTF8") from None

    blocks = tuple(
        TextBlock(
            block_id=f"ocr-text-{index}",
            text=line,
            bbox=BoundingBox(0.0, 0.0, 1.0, 1.0),
            reading_order=index - 1,
        )
        for index, line in enumerate((value.strip() for value in text.splitlines()), start=1)
        if line
    )
    if not blocks:
        raise ValueError("OCR_OUTPUT_EMPTY")

    return StructuredDocument(
        observation_id=observation_id,
        observation_sha256=observation_sha256,
        pages=(PageStructure(1, 1.0, 1.0, blocks, ()),),
        component=component,
        component_version=component_version,
    )
