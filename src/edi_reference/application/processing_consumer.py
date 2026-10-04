"""At-least-once processing consumer with deduplication and leases."""

from dataclasses import replace
from datetime import timedelta
from typing import Callable, Protocol, cast

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


class ProcessingFailure(Exception):
    """Expected document-processing failure safe to persist as PROCESSING_FAILED."""


class DocumentProcessor(Protocol):
    """Process one owned claim.

    Expected document-level failures MUST raise ProcessingFailure. Unexpected
    implementation defects and ownership/control failures MUST propagate.
    """

    def process(self, claim: ProcessingClaim) -> None: ...


class FinalizingDocumentProcessor(Protocol):\n    """Processor that atomically persists its result and terminal success."""\n\n    def process_and_finalize(self, claim: ProcessingClaim) -> None: ...\n\n\nclass LeaseAwareDocumentProcessor(Protocol):
    """Process one owned claim with explicit lease renewal.

    Expected document-level failures MUST raise ProcessingFailure. Unexpected
    implementation defects and ownership/control failures MUST propagate.
    """

    def process(
        self,
        claim: ProcessingClaim,
        renew_lease: Callable[[], ProcessingClaim],
    ) -> None: ...


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
    processor: DocumentProcessor | LeaseAwareDocumentProcessor,
    observations: ObservationRepository,
    clock: Clock,
    ids: IdGenerator,
    lease_seconds: int = 300,
    lease_aware: bool = False,
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
        if lease_aware:
            active_claim = claim

            def renew_lease() -> ProcessingClaim:
                nonlocal active_claim
                active_claim = renew_processing_lease(
                    active_claim,
                    repository=repository,
                    clock=clock,
                    lease_seconds=lease_seconds,
                )
                return active_claim

            cast(LeaseAwareDocumentProcessor, processor).process(claim, renew_lease)
            claim = active_claim
        else:
            cast(DocumentProcessor, processor).process(claim)
    except ProcessingFailure:
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
