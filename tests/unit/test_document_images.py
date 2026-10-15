"""Real raster/decoder tests using generated synthetic documents, no network."""

import hashlib
import io
from dataclasses import replace

import pytest
from PIL import Image
from pypdf import PdfWriter

from edi_reference.adapters.document_images import ImagePreparationLimits, PdfiumDocumentImagePreparer
from edi_reference.application.document_images import DocumentImageError, DocumentImagePreparer


def pdf(pages=2, *, password=None, width=72, height=144):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=height)
    if password is not None:
        writer.encrypt(password, owner_password="synthetic-owner", algorithm="RC4-128")
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def prepare(content, *, media_type="application/pdf", page_numbers=None, **limits):
    preparer: DocumentImagePreparer = PdfiumDocumentImagePreparer(ImagePreparationLimits(**limits))
    return preparer.prepare(content, media_type=media_type, page_numbers=page_numbers)


def test_real_pdf_rendering_dimensions_hashes_and_jpeg():
    source = pdf()
    result = prepare(source, dpi=144)
    assert result.source_sha256 == hashlib.sha256(source).hexdigest()
    assert result.total_pages == 2 and result.complete
    assert [p.source_page_number for p in result.pages] == [1, 2]
    for page in result.pages:
        assert page.media_type == "image/jpeg"
        assert (page.width, page.height) == (144, 288)
        assert page.sha256 == hashlib.sha256(page.content).hexdigest()
        with Image.open(io.BytesIO(page.content)) as image:
            image.load()
            assert image.format == "JPEG" and image.mode == "RGB"


def test_page_limit_rejects_by_default_and_first_is_explicit():
    source = pdf(3)
    with pytest.raises(DocumentImageError, match="DOCUMENT_PAGE_LIMIT_EXCEEDED"):
        prepare(source, max_pages=2)
    result = prepare(source, max_pages=2, page_selection="first")
    assert result.total_pages == 3 and not result.complete
    assert [p.source_page_number for p in result.pages] == [1, 2]


def test_explicit_selection_preserves_source_page_numbers_and_order():
    result = prepare(pdf(3), max_pages=2, page_numbers=(3, 1))
    assert [p.source_page_number for p in result.pages] == [3, 1]
    assert not result.complete


@pytest.mark.parametrize("selection", [(), (0,), (4,), (1, 1), (True,), (1.5,)])
def test_invalid_selection(selection):
    with pytest.raises(DocumentImageError, match="INVALID_PAGE_SELECTION"):
        prepare(pdf(3), page_numbers=selection)


def test_selection_cannot_bypass_page_limit():
    with pytest.raises(DocumentImageError, match="DOCUMENT_PAGE_LIMIT_EXCEEDED"):
        prepare(pdf(3), max_pages=1, page_numbers=(1, 3))


@pytest.mark.parametrize("content", [b"not a pdf", b"%PDF-1.7\ntruncated", pdf()[:100]])
def test_corrupt_pdf_has_stable_error(content):
    with pytest.raises(DocumentImageError, match="^INVALID_PDF$"):
        prepare(content)


@pytest.mark.parametrize("password", ["synthetic-password", ""])
def test_encrypted_pdf_rejected_including_empty_user_password(password):
    with pytest.raises(DocumentImageError, match="^PDF_ENCRYPTED$"):
        prepare(pdf(password=password))


@pytest.mark.parametrize("limits, code", [
    ({"max_input_bytes": 10}, "DOCUMENT_INPUT_LIMIT_EXCEEDED"),
    ({"max_dimension": 100}, "IMAGE_DIMENSION_LIMIT_EXCEEDED"),
    ({"max_pixels": 100}, "IMAGE_DIMENSION_LIMIT_EXCEEDED"),
    ({"max_image_bytes": 100}, "IMAGE_OUTPUT_LIMIT_EXCEEDED"),
    ({"max_output_bytes": 100}, "IMAGE_OUTPUT_LIMIT_EXCEEDED"),
])
def test_resource_limits(limits, code):
    with pytest.raises(DocumentImageError, match=code):
        prepare(pdf(), **limits)


def test_total_output_budget_includes_previous_pages():
    source = pdf()
    size = len(prepare(source, page_numbers=(1,)).pages[0].content)
    with pytest.raises(DocumentImageError, match="IMAGE_OUTPUT_LIMIT_EXCEEDED"):
        prepare(source, max_output_bytes=size + 1)
    assert prepare(source, max_output_bytes=size * 2).complete


def test_oversized_page_rejected_before_native_render(monkeypatch):
    import pypdfium2

    def forbidden(*args, **kwargs):
        pytest.fail("native render must not be called for oversized dimensions")

    monkeypatch.setattr(pypdfium2.PdfPage, "render", forbidden)
    with pytest.raises(DocumentImageError, match="IMAGE_DIMENSION_LIMIT_EXCEEDED"):
        prepare(pdf(width=100_000))


@pytest.mark.parametrize("format, media", [("PNG", "image/png"), ("JPEG", "image/jpeg")])
def test_image_passthrough_is_byte_exact(format, media):
    with Image.new("RGB", (30, 40), "white") as image:
        stream = io.BytesIO()
        image.save(stream, format=format)
    source = stream.getvalue()
    result = prepare(source, media_type=media)
    assert result.complete and result.total_pages == 1
    assert result.pages[0].content == source
    assert result.pages[0].sha256 == result.source_sha256
    assert (result.pages[0].width, result.pages[0].height) == (30, 40)
    with pytest.raises(DocumentImageError, match="IMAGE_DIMENSION_LIMIT_EXCEEDED"):
        prepare(source, media_type=media, max_pixels=100)
    with pytest.raises(DocumentImageError, match="IMAGE_OUTPUT_LIMIT_EXCEEDED"):
        prepare(source, media_type=media, max_image_bytes=10)


def test_image_type_mismatch_and_corruption():
    stream = io.BytesIO()
    Image.new("RGB", (10, 10)).save(stream, format="PNG")
    with pytest.raises(DocumentImageError, match="IMAGE_MEDIA_TYPE_MISMATCH"):
        prepare(stream.getvalue(), media_type="image/jpeg")
    with pytest.raises(DocumentImageError, match="INVALID_IMAGE"):
        prepare(b"\x89PNG\r\n\x1a\ncorrupt", media_type="image/png")


@pytest.mark.parametrize("content, media, code", [
    (b"", "application/pdf", "EMPTY_DOCUMENT"),
    (b"abc", "text/plain", "UNSUPPORTED_DOCUMENT_MEDIA_TYPE"),
    # PDFium rejects a zero-page page tree during open, before page selection.
    (pdf(0), "application/pdf", "INVALID_PDF"),
])
def test_empty_and_unsupported(content, media, code):
    with pytest.raises(DocumentImageError, match=code):
        prepare(content, media_type=media)


@pytest.mark.parametrize("changes", [
    {"dpi": 0}, {"dpi": 601}, {"max_pages": True}, {"max_pages": -1},
    {"max_pixels": 1.5}, {"jpeg_quality": 96}, {"page_selection": "random"},
])
def test_invalid_configuration(changes):
    with pytest.raises(ValueError, match="INVALID_IMAGE_PREPARATION_LIMIT"):
        replace(ImagePreparationLimits(), **changes)


def test_rendered_page_works_with_existing_vision_adapter():
    from test_openai_vision import Transport, analyzer

    page = prepare(pdf(), page_numbers=(2,)).pages[0]
    result = analyzer(Transport()).analyze(page.content, media_type=page.media_type,
                                         observation_id="synthetic-derived-page-2")
    assert result.observation_sha256 == page.sha256
    # Analyzer evidence is relative to the derived image. Preserve the mapping
    # to original page 2 separately; do not relabel its digest as the PDF digest.
    assert page.source_page_number == 2
    assert result.classification.evidence[0].page_number == 1


def test_native_resources_close_after_output_limit_failure(monkeypatch):
    import pypdfium2

    closed = []
    for name in ("PdfDocument", "PdfPage", "PdfBitmap"):
        cls = getattr(pypdfium2, name)
        original = cls.close

        def close(self, *args, _original=original, _name=name, **kwargs):
            if self.raw:
                closed.append(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(cls, "close", close)
    with pytest.raises(DocumentImageError, match="IMAGE_OUTPUT_LIMIT_EXCEEDED"):
        prepare(pdf(), max_image_bytes=1)
    assert all(name in closed for name in ("PdfDocument", "PdfPage", "PdfBitmap"))


def test_rotated_page_has_correct_output_dimensions():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=144).rotate(90)
    stream = io.BytesIO()
    writer.write(stream)
    page = prepare(stream.getvalue(), dpi=72).pages[0]
    assert (page.width, page.height) == (144, 72)


def test_missing_optional_dependency_is_explicit(monkeypatch):
    import edi_reference.adapters.document_images as adapter

    def unavailable(name):
        raise ImportError(name)

    monkeypatch.setattr(adapter.importlib, "import_module", unavailable)
    with pytest.raises(DocumentImageError, match="IMAGE_PREPARATION_DEPENDENCY_UNAVAILABLE"):
        prepare(pdf())
