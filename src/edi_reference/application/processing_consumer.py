"""At-least-once processing consumer with deduplication and leases."""

from dataclasses import replace
from datetime import timedelta
from typing import Protocol

from edi_reference.domain.ingestion import Clock, IdGenerator
from edi_reference.domain.outbox import OutboxMessage
from edi_reference.domain.processing import ProcessingClaim, ProcessingClaimStatus


class ProcessingClaimRepository(Protocol):
    def get(self, message_id: str) -> ProcessingClaim | None: ...
    def try_create(self, claim: ProcessingClaim) -> bool: ...
    def save(self, claim: ProcessingClaim) -> None: ...


class DocumentProcessor(Protocol):
    def process(self, claim: ProcessingClaim) -> None: ...


def consume_processing_message(
    message: OutboxMessage,
    *,
    repository: ProcessingClaimRepository,
    processor: DocumentProcessor,
    clock: Clock,
    ids: IdGenerator,
    lease_seconds: int = 300,
) -> ProcessingClaim:
    if message.message_type != "PROCESS_DOCUMENT":
        raise ValueError("UNSUPPORTED_MESSAGE_TYPE")
    if not message.payload_ref.startswith("sha256:"):
        raise ValueError("INVALID_CONTENT_REFERENCE")

    existing = repository.get(message.message_id)
    now = clock.now()
    if existing is not None:
        if existing.status is ProcessingClaimStatus.COMPLETED:
            return existing
        if existing.status is ProcessingClaimStatus.CLAIMED and existing.lease_until > now:
            return existing

    digest = message.payload_ref.removeprefix("sha256:")
    if len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
        raise ValueError("INVALID_CONTENT_REFERENCE")

    claim = ProcessingClaim(
        message_id=message.message_id,
        processing_run_id=existing.processing_run_id if existing else ids.new_id(),
        tenant_id=message.tenant_id,
        application_id=message.application_id,
        observation_sha256=digest.lower(),
        status=ProcessingClaimStatus.CLAIMED,
        claimed_at=now,
        lease_until=now + timedelta(seconds=lease_seconds),
    )
    if existing is None and not repository.try_create(claim):
        concurrent = repository.get(message.message_id)
        if concurrent is None:
            raise RuntimeError("CLAIM_CONFLICT")
        return concurrent
    if existing is not None:
        repository.save(claim)

    try:
        processor.process(claim)
    except Exception:
        failed = replace(
            claim,
            status=ProcessingClaimStatus.FAILED,
            failure_code="PROCESSING_FAILED",
        )
        repository.save(failed)
        return failed

    completed = replace(
        claim,
        status=ProcessingClaimStatus.COMPLETED,
        completed_at=clock.now(),
        failure_code=None,
    )
    repository.save(completed)
    return completed
