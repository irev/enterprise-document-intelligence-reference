import pytest

from edi_reference.application.structured_ocr import structured_ocr_to_document
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine


def test_structured_ocr_preserves_geometry_confidence_and_pages():
    result = OcrResult((
        OcrPage(1, 1000, 1400, (
            OcrTextLine("Invoice INV-001", BoundingBox(.1, .1, .5, .2), .97),
        )),
        OcrPage(2, 1000, 1400, (
            OcrTextLine("Total 1250000", BoundingBox(.2, .7, .7, .8), .91),
        )),
    ))
    document = structured_ocr_to_document(
        result, observation_id="obs-1", observation_sha256="a" * 64,
        component="local-ocr", component_version="1",
    )
    assert len(document.pages) == 2
    assert document.pages[0].text_blocks[0].bbox == BoundingBox(.1, .1, .5, .2)
    assert document.pages[0].text_blocks[0].confidence == .97
    assert document.pages[1].text_blocks[0].block_id == "ocr-p2-l1"


@pytest.mark.parametrize("confidence", [-.01, 1.01])
def test_ocr_line_rejects_invalid_confidence(confidence):
    with pytest.raises(ValueError, match="INVALID_OCR_CONFIDENCE"):
        OcrTextLine("text", BoundingBox(0, 0, 1, 1), confidence)


def test_ocr_result_requires_contiguous_pages():
    with pytest.raises(ValueError, match="NON_CONTIGUOUS_OCR_PAGES"):
        OcrResult((OcrPage(2, 100, 100, ()),))
