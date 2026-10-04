import pytest

from edi_reference.application.ocr_codec import decode_ocr_result, encode_ocr_result
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine


def sample():
    return OcrResult((OcrPage(1, 1000, 1400, (
        OcrTextLine("Invoice", BoundingBox(.1, .2, .4, .3), .97),
    )),))


def test_structured_ocr_codec_round_trip_preserves_contract():
    decoded = decode_ocr_result(encode_ocr_result(sample()))
    assert decoded == sample()


@pytest.mark.parametrize("payload", [b"not-json", b"{}", b'{"pages":"wrong"}'])
def test_structured_ocr_codec_rejects_invalid_payload(payload):
    with pytest.raises(ValueError, match="INVALID_STRUCTURED_OCR_PAYLOAD"):
        decode_ocr_result(payload)
