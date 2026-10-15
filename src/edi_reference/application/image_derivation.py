"""Immutable, scoped image lineage before invocation; not a public result schema."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from edi_reference.application.document_images import DocumentImage, DocumentImagePreparer, DocumentImages
from edi_reference.application.lineage import require_observation_scope
from edi_reference.domain.lineage import ProcessingRunBinding, SourceObservation


def _digest(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True, slots=True)
class ImageDerivation:
    binding: ProcessingRunBinding
    prepared: DocumentImages

    def __post_init__(self) -> None:
        b, p = self.binding, self.prepared
        if any(not value for value in (b.processing_run_id, b.document_id, b.tenant_id,
                                       b.application_id, b.observation_id)):
            raise ValueError("DERIVATION_IDENTITY_REQUIRED")
        if not _digest(p.source_sha256) or p.source_sha256 != b.observation_sha256:
            raise ValueError("DERIVATION_SOURCE_MISMATCH")
        if b.created_at.tzinfo is None or b.created_at.utcoffset() is None:
            raise ValueError("DERIVATION_TIMESTAMP_REQUIRES_TIMEZONE")
        if (type(p.total_pages) is not int or p.total_pages < 1 or not p.pages
                or len({page.source_page_number for page in p.pages}) != len(p.pages)):
            raise ValueError("INVALID_DERIVATION_PAGES")
        if (not p.recipe or len(dict(p.recipe)) != len(p.recipe)
                or any(not key or not value for key, value in p.recipe)
                or not dict(p.recipe).get("algorithm")):
            raise ValueError("INVALID_DERIVATION_RECIPE")
        for page in p.pages:
            if (type(page.source_page_number) is not int or not 1 <= page.source_page_number <= p.total_pages
                    or type(page.width) is not int or type(page.height) is not int
                    or min(page.width, page.height) < 1 or not page.content
                    or page.media_type not in {"image/jpeg", "image/png"}):
                raise ValueError("INVALID_DERIVATION_PAGE")
            if not _digest(page.sha256) or hashlib.sha256(page.content).hexdigest() != page.sha256:
                raise ValueError("DERIVATION_IMAGE_DIGEST_MISMATCH")

    def image_observation_id(self, page: DocumentImage) -> str:
        if page not in self.prepared.pages:
            raise ValueError("DERIVATION_PAGE_NOT_FOUND")
        b = self.binding
        identity = ["image-derivation/v1", b.tenant_id, b.application_id, b.document_id,
                    b.processing_run_id, b.observation_id, b.observation_sha256,
                    sorted(self.prepared.recipe), page.source_page_number, page.sha256,
                    page.media_type, page.width, page.height]
        digest = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return "img_" + digest


class ImageDerivationRepository(Protocol):
    def save(self, derivation: ImageDerivation) -> None:
        """Atomically save a batch; identical retry is allowed, replacement is not."""
        ...

    def get(self, processing_run_id: str, *, tenant_id: str, application_id: str) -> ImageDerivation | None: ...


def prepare_image_derivation(
    content: bytes, *, observation: SourceObservation, binding: ProcessingRunBinding,
    preparer: DocumentImagePreparer, repository: ImageDerivationRepository,
    tenant_id: str, application_id: str, page_numbers: tuple[int, ...] | None = None,
) -> ImageDerivation:
    """Verify source/scope, render, then commit lineage before any model invocation.

    A retry with changed renderer settings/versions or page selection conflicts.
    Reprocessing must supply a new processing run, retaining the prior batch.
    """
    require_observation_scope(observation, tenant_id=tenant_id, application_id=application_id)
    if (binding.tenant_id, binding.application_id, binding.document_id,
        binding.observation_id, binding.observation_sha256) != (
        tenant_id, application_id, observation.document_id,
        observation.observation_id, observation.sha256):
        raise ValueError("DERIVATION_BINDING_MISMATCH")
    if len(content) != observation.byte_length or hashlib.sha256(content).hexdigest() != observation.sha256:
        raise ValueError("DERIVATION_SOURCE_MISMATCH")
    prepared = preparer.prepare(content, media_type=observation.detected_media_type, page_numbers=page_numbers)
    derivation = ImageDerivation(binding, prepared)
    repository.save(derivation)
    return derivation
