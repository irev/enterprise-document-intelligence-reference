"""Internal image preparation port; no rendering SDK or public schema dependency."""

from dataclasses import dataclass
from typing import Protocol


class DocumentImageError(ValueError):
    """Stable preparation failure without document content in the message."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DocumentImage:
    source_page_number: int
    content: bytes
    media_type: str
    sha256: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class DocumentImages:
    source_sha256: str
    total_pages: int
    pages: tuple[DocumentImage, ...]
    recipe: tuple[tuple[str, str], ...]

    @property
    def complete(self) -> bool:
        return len(self.pages) == self.total_pages


class DocumentImagePreparer(Protocol):
    def prepare(self, content: bytes, *, media_type: str,
                page_numbers: tuple[int, ...] | None = None) -> DocumentImages: ...
