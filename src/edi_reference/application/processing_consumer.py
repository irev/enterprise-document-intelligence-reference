"""At-least-once processing consumer with deduplication and leases."""

from dataclasses import replace
from datetime import timedelta
from typing import Protocol

from edi_reference.domain.ingestion import Clock, IdGenerator
from edi_reference.domain.outbox import OutboxMessage
from edi_reference.domain.processing import ProcessingClaim, ProcessingClaimStatus
from edi_reference.domain.lineage import SourceObservation


class ProcessingClaimRepository(Protocol):
    def get(self, message_id: str) -> ProcessingClaim | None: ...
    def try_create(self, claim: ProcessingClaim) -> bool: ...
    def save(self, claim: ProcessingClaim) -> None: ...
    def try_reclaim(self, claim: ProcessingClaim, expected_generation: int, *, now) -> bool: ...
    def save_if_generation(self, claim: ProcessingClaim, expected_generation: int, *, now) -> bool: ...
    def try_renew_lease(self, message_id: str, expected_generation: int, *, now, lease_until) -> bool: ...


class ObservationRepository(Protocol):
    def get(self, observation_id: str) -> SourceObservation | None: ...


class DocumentProcessor(Protocol):
    def process(self, claim: ProcessingClaim) -> None: ...


def renew_processing_lease(
    claim: ProcessingClaim,
    *,
    repository: ProcessingClaimRepository,
    clock: Clock,
    lease_seconds: int = 300,
) -> ProcessingClaim:
    """Renew only the currently owned claim generation while its lease is still live."""
    now = clock.now()
    lease_until = now + timedelta(seconds=lease_seconds)
    if not repository.try_renew_lease(
        claim.message_id,
        claim.claim_generation,
        now=now,
        lease_until=lease_until,
    ):
        raise RuntimeError("CLAIM_LEASE_LOST")
    return replace(claim, lease_until=lease_until)



def consume_processing_message(
    message: OutboxMessage,
    *,
    repository: ProcessingClaimRepository,
    processor: DocumentProcessor,
    observations: ObservationRepository,
    clock: Clock,
    ids: IdGenerator,
    lease_seconds: int = 300,
) -> ProcessingClaim:
    if message.message_type != "PROCESS_DOCUMENT":
        raise ValueError("UNSUPPORTED_MESSAGE_TYPE")
    if message.observation_id is None:
        raise ValueError("OBSERVATION_ID_REQUIRED")
    observation = observations.get(message.observation_id)
    if observation is None:
        raise ValueError("OBSERVATION_NOT_FOUND")
    if (observation.tenant_id, observation.application_id) != (
        message.tenant_id, message.application_id
    ):
        raise ValueError("OBSERVATION_SCOPE_MISMATCH")

    existing = repository.get(message.message_id)
    now = clock.now()
    if existing is not None:
        if existing.status is ProcessingClaimStatus.COMPLETED:
            return existing
        if existing.status is ProcessingClaimStatus.CLAIMED and existing.lease_until > now:
            return existing

    digest = observation.sha256.lower()

    claim = ProcessingClaim(
        message_id=message.message_id,
        processing_run_id=existing.processing_run_id if existing else ids.new_id(),
        tenant_id=message.tenant_id,
        application_id=message.application_id,
        observation_sha256=digest.lower(),
        status=ProcessingClaimStatus.CLAIMED,
        claimed_at=now,
        lease_until=now + timedelta(seconds=lease_seconds),
        claim_generation=(existing.claim_generation + 1) if existing else 1,
        observation_id=message.observation_id,
    )
    if existing is None and not repository.try_create(claim):
        concurrent = repository.get(message.message_id)
        if concurrent is None:
            raise RuntimeError("CLAIM_CONFLICT")
        return concurrent
    if existing is not None:
        if not repository.try_reclaim(claim, existing.claim_generation, now=now):
            concurrent = repository.get(message.message_id)
            if concurrent is None:
                raise RuntimeError("CLAIM_CONFLICT")
            return concurrent

    try:
        processor.process(claim)
    except Exception:
        failed = replace(
            claim,
            status=ProcessingClaimStatus.FAILED,
            failure_code="PROCESSING_FAILED",
        )
        if not repository.save_if_generation(failed, claim.claim_generation, now=clock.now()):
            current = repository.get(message.message_id)
            if current is None:
                raise RuntimeError("CLAIM_LOST")
            return current
        return failed

    completed = replace(
        claim,
        status=ProcessingClaimStatus.COMPLETED,
        completed_at=clock.now(),
        failure_code=None,
    )
    if not repository.save_if_generation(completed, claim.claim_generation, now=clock.now()):
        current = repository.get(message.message_id)
        if current is None:
            raise RuntimeError("CLAIM_LOST")
        return current
    return completed
