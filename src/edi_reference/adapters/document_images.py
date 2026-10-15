"""Bounded, opt-in PDFium/Pillow rendering for the single-image vision port.

PDFium calls are serialized: its native library is not thread-safe. These limits
bound raster/output size, not native-parser CPU or memory; use worker isolation
for hostile documents. No document is sent to a model by this adapter.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import math
import threading
import warnings
from dataclasses import asdict, dataclass
from importlib.metadata import version

from edi_reference.application.document_images import DocumentImage, DocumentImageError, DocumentImages

_PDF_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class ImagePreparationLimits:
    dpi: int = 150
    max_pages: int = 20
    max_input_bytes: int = 20_000_000
    max_image_bytes: int = 5_000_000
    max_output_bytes: int = 20_000_000
    max_dimension: int = 4096
    max_pixels: int = 16_000_000
    jpeg_quality: int = 85
    page_selection: str = "all"

    def __post_init__(self) -> None:
        for name in ("dpi", "max_pages", "max_input_bytes", "max_image_bytes",
                     "max_output_bytes", "max_dimension", "max_pixels", "jpeg_quality"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError("INVALID_IMAGE_PREPARATION_LIMIT")
        if self.dpi > 600 or self.jpeg_quality > 95 or self.page_selection not in {"all", "first"}:
            raise ValueError("INVALID_IMAGE_PREPARATION_LIMIT")


class _BoundedOutput(io.BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit

    def write(self, data: bytes) -> int:  # type: ignore[override]
        if self.tell() + len(data) > self.limit:
            raise DocumentImageError("IMAGE_OUTPUT_LIMIT_EXCEEDED")
        return super().write(data)


class PdfiumDocumentImagePreparer:
    def __init__(self, limits: ImagePreparationLimits = ImagePreparationLimits()) -> None:
        self.limits = limits

    def _recipe(self, *, pdfium=None) -> tuple[tuple[str, str], ...]:
        recipe = {"algorithm": "pdfium-jpeg/v1" if pdfium else "image-passthrough/v1",
                  "pillow": version("Pillow"),
                  **{name: str(value) for name, value in asdict(self.limits).items()}}
        if pdfium is not None:
            recipe.update(pypdfium2=version("pypdfium2"), pdfium=str(pdfium.PDFIUM_INFO))
        return tuple(sorted(recipe.items()))

    def prepare(self, content: bytes, *, media_type: str,
                page_numbers: tuple[int, ...] | None = None) -> DocumentImages:
        if not content:
            raise DocumentImageError("EMPTY_DOCUMENT")
        if len(content) > self.limits.max_input_bytes:
            raise DocumentImageError("DOCUMENT_INPUT_LIMIT_EXCEEDED")
        if media_type not in {"application/pdf", "image/png", "image/jpeg"}:
            raise DocumentImageError("UNSUPPORTED_DOCUMENT_MEDIA_TYPE")
        try:
            image_module = importlib.import_module("PIL.Image")
            if media_type != "application/pdf":
                return self._image(content, media_type, page_numbers, image_module)
            pdfium = importlib.import_module("pypdfium2")
        except ImportError:
            raise DocumentImageError("IMAGE_PREPARATION_DEPENDENCY_UNAVAILABLE") from None
        with _PDF_LOCK:
            return self._pdf(content, page_numbers, pdfium)

    def _select(self, total: int, requested: tuple[int, ...] | None) -> tuple[int, ...]:
        if total < 1:
            raise DocumentImageError("EMPTY_DOCUMENT")
        if requested is not None:
            if (not requested or any(type(n) is not int or not 1 <= n <= total for n in requested)
                    or len(set(requested)) != len(requested)):
                raise DocumentImageError("INVALID_PAGE_SELECTION")
            selected = requested
        elif self.limits.page_selection == "first":
            selected = tuple(range(1, min(total, self.limits.max_pages) + 1))
        else:
            if total > self.limits.max_pages:
                raise DocumentImageError("DOCUMENT_PAGE_LIMIT_EXCEEDED")
            selected = tuple(range(1, total + 1))
        if len(selected) > self.limits.max_pages:
            raise DocumentImageError("DOCUMENT_PAGE_LIMIT_EXCEEDED")
        return selected

    def _dimensions(self, width: int, height: int) -> None:
        if (min(width, height) < 1 or max(width, height) > self.limits.max_dimension
                or width * height > self.limits.max_pixels):
            raise DocumentImageError("IMAGE_DIMENSION_LIMIT_EXCEEDED")

    def _image(self, content, media_type, requested, image_module) -> DocumentImages:
        self._select(1, requested)
        if len(content) > min(self.limits.max_image_bytes, self.limits.max_output_bytes):
            raise DocumentImageError("IMAGE_OUTPUT_LIMIT_EXCEEDED")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", image_module.DecompressionBombWarning)
                with image_module.open(io.BytesIO(content)) as image:
                    if image.format != {"image/png": "PNG", "image/jpeg": "JPEG"}[media_type]:
                        raise DocumentImageError("IMAGE_MEDIA_TYPE_MISMATCH")
                    self._dimensions(*image.size)
                    width, height = image.size
                    if getattr(image, "n_frames", 1) != 1:
                        raise DocumentImageError("MULTIFRAME_IMAGE_UNSUPPORTED")
                    image.verify()
                with image_module.open(io.BytesIO(content)) as image:
                    image.load()
        except DocumentImageError:
            raise
        except (image_module.DecompressionBombError, image_module.DecompressionBombWarning):
            raise DocumentImageError("IMAGE_DIMENSION_LIMIT_EXCEEDED") from None
        except (OSError, ValueError, SyntaxError):
            raise DocumentImageError("INVALID_IMAGE") from None
        digest = hashlib.sha256(content).hexdigest()
        return DocumentImages(digest, 1, (DocumentImage(1, content, media_type, digest, width, height),), self._recipe())

    def _pdf(self, content, requested, pdfium) -> DocumentImages:
        try:
            document = pdfium.PdfDocument(content)
        except pdfium.PdfiumError:
            code = ("PDF_ENCRYPTED" if pdfium.raw.FPDF_GetLastError() == pdfium.raw.FPDF_ERR_PASSWORD
                    else "INVALID_PDF")
            raise DocumentImageError(code) from None
        try:
            # Reject even encrypted PDFs with an empty user password.
            if pdfium.raw.FPDF_GetSecurityHandlerRevision(document) != -1:
                raise DocumentImageError("PDF_ENCRYPTED")
            total = len(document)
            selected = self._select(total, requested)
            pages = []
            output_size = 0
            for number in selected:
                page = document[number - 1]
                try:
                    scale = self.limits.dpi / 72
                    size = page.get_size()
                    if any(not math.isfinite(v) or v <= 0 for v in size):
                        raise DocumentImageError("INVALID_PDF")
                    self._dimensions(*(math.ceil(v * scale) for v in size))
                    bitmap = page.render(scale=scale)
                    try:
                        with bitmap.to_pil() as image, image.convert("RGB") as rgb:
                            self._dimensions(*rgb.size)
                            budget = min(self.limits.max_image_bytes, self.limits.max_output_bytes - output_size)
                            with _BoundedOutput(budget) as output:
                                rgb.save(output, format="JPEG", quality=self.limits.jpeg_quality)
                                data = output.getvalue()
                            pages.append(DocumentImage(number, data, "image/jpeg",
                                hashlib.sha256(data).hexdigest(), rgb.width, rgb.height))
                            output_size += len(data)
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            return DocumentImages(hashlib.sha256(content).hexdigest(), total, tuple(pages), self._recipe(pdfium=pdfium))
        except (pdfium.PdfiumError, OSError, OverflowError):
            raise DocumentImageError("INVALID_PDF") from None
        finally:
            document.close()
