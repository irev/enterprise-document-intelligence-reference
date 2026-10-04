"""Deterministic RI-1 source ingestion.

This module validates source bytes and produces source identity. It performs no
OCR, model inference, business approval or provider/network operation.
"""

from __future__ import annotations

import hashlib

from edi_reference.domain.ingestion import (
    Clock,
    IngestionReceipt,
    SourceDisposition,
    SourceIdentity,
    SourcePolicy,
    SourceRejectionCode,
    SourceSubmission,
)


_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def detect_media_type(content: bytes) -> str | None:
    """Detect only media types RI-1 can identify deterministically."""

    for signature, media_type in _SIGNATURES:
        if content.startswith(signature):
            return media_type
    return None


def ingest_source(
    submission: SourceSubmission,
    *,
    policy: SourcePolicy,
    clock: Clock,
) -> IngestionReceipt:
    received_at = clock.now()
    size = len(submission.content)

    if size == 0:
        return IngestionReceipt(
            disposition=SourceDisposition.REJECTED,
            received_at=received_at,
            rejection_code=SourceRejectionCode.EMPTY_DOCUMENT,
        )

    if size > policy.max_bytes:
        return IngestionReceipt(
            disposition=SourceDisposition.REJECTED,
            received_at=received_at,
            rejection_code=SourceRejectionCode.DOCUMENT_TOO_LARGE,
        )

    detected = detect_media_type(submission.content)
    if detected is None or detected not in policy.allowed_media_types:
        return IngestionReceipt(
            disposition=SourceDisposition.UNSUPPORTED,
            received_at=received_at,
            rejection_code=SourceRejectionCode.UNSUPPORTED_MEDIA_TYPE,
        )

    if (
        submission.declared_media_type is not None
        and submission.declared_media_type != detected
    ):
        return IngestionReceipt(
            disposition=SourceDisposition.REJECTED,
            received_at=received_at,
            rejection_code=SourceRejectionCode.CONTENT_TYPE_MISMATCH,
        )

    identity = SourceIdentity(
        algorithm="sha256",
        digest=hashlib.sha256(submission.content).hexdigest(),
        byte_length=size,
        detected_media_type=detected,
    )
    return IngestionReceipt(
        disposition=SourceDisposition.ACCEPTED,
        received_at=received_at,
        source=identity,
    )
