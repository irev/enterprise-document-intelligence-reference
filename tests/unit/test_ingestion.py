from datetime import UTC, datetime

from edi_reference.application.ingest import ingest_source
from edi_reference.domain.ingestion import (
    SourceDisposition,
    SourcePolicy,
    SourceRejectionCode,
    SourceSubmission,
)
from edi_reference.domain.integration import InteractionContext


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 4, 7, 0, tzinfo=UTC)


CONTEXT = InteractionContext(
    tenant_id="tenant-synthetic",
    application_id="app-synthetic",
    correlation_id="corr-001",
)

POLICY = SourcePolicy(
    max_bytes=1024,
    allowed_media_types=frozenset(
        {"application/pdf", "image/png", "image/jpeg"}
    ),
)


def submission(content: bytes, media_type: str | None) -> SourceSubmission:
    return SourceSubmission(
        content=content,
        declared_media_type=media_type,
        filename="synthetic.bin",
        context=CONTEXT,
    )


def test_pdf_is_accepted_and_sha256_is_stable() -> None:
    item = submission(b"%PDF-1.7\nsynthetic", "application/pdf")

    first = ingest_source(item, policy=POLICY, clock=FixedClock())
    second = ingest_source(item, policy=POLICY, clock=FixedClock())

    assert first.disposition is SourceDisposition.ACCEPTED
    assert first.source is not None
    assert first.source.algorithm == "sha256"
    assert first.source.digest == second.source.digest
    assert first.source.detected_media_type == "application/pdf"


def test_empty_source_is_rejected() -> None:
    result = ingest_source(submission(b"", "application/pdf"), policy=POLICY, clock=FixedClock())

    assert result.disposition is SourceDisposition.REJECTED
    assert result.rejection_code is SourceRejectionCode.EMPTY_DOCUMENT


def test_declared_type_must_not_override_detected_content() -> None:
    result = ingest_source(
        submission(b"%PDF-1.7\nsynthetic", "image/png"),
        policy=POLICY,
        clock=FixedClock(),
    )

    assert result.disposition is SourceDisposition.REJECTED
    assert result.rejection_code is SourceRejectionCode.CONTENT_TYPE_MISMATCH


def test_unknown_signature_is_unsupported() -> None:
    result = ingest_source(
        submission(b"not-a-supported-document", "application/pdf"),
        policy=POLICY,
        clock=FixedClock(),
    )

    assert result.disposition is SourceDisposition.UNSUPPORTED
    assert result.rejection_code is SourceRejectionCode.UNSUPPORTED_MEDIA_TYPE


def test_size_limit_is_enforced_before_processing() -> None:
    result = ingest_source(
        submission(b"%PDF-" + b"x" * 1024, "application/pdf"),
        policy=POLICY,
        clock=FixedClock(),
    )

    assert result.disposition is SourceDisposition.REJECTED
    assert result.rejection_code is SourceRejectionCode.DOCUMENT_TOO_LARGE
