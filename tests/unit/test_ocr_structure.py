import pytest

from edi_reference.application.ocr_structure import ocr_text_to_structure
from edi_reference.domain.invocation import InvocationResult


def result(output=b"Invoice INV-001\nTotal 1250000"):
    return InvocationResult("local-ocr", "1", output)


def test_ocr_text_becomes_evidence_addressable_canonical_blocks():
    document = ocr_text_to_structure(
        result(),
        observation_id="obs-1",
        observation_sha256="a" * 64,
        component="local-ocr",
        component_version="1",
    )
    assert document.observation_id == "obs-1"
    assert [block.text for block in document.pages[0].text_blocks] == [
        "Invoice INV-001", "Total 1250000",
    ]
    assert [block.block_id for block in document.pages[0].text_blocks] == [
        "ocr-text-1", "ocr-text-2",
    ]


def test_non_utf8_ocr_output_is_rejected():
    with pytest.raises(ValueError, match="OCR_OUTPUT_NOT_UTF8"):
        ocr_text_to_structure(
            result(b"\xff"), observation_id="obs-1",
            observation_sha256="a" * 64, component="local-ocr", component_version="1",
        )


def test_empty_ocr_output_is_not_silently_accepted():
    with pytest.raises(ValueError, match="OCR_OUTPUT_EMPTY"):
        ocr_text_to_structure(
            result(b"\n  \n"), observation_id="obs-1",
            observation_sha256="a" * 64, component="local-ocr", component_version="1",
        )
