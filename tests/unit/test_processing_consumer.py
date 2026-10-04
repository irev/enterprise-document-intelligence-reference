from datetime import UTC, datetime, timedelta

from edi_reference.adapters.processing_memory import InMemoryProcessingClaimRepository
from edi_reference.application.processing_consumer import consume_processing_message
from edi_reference.domain.outbox import OutboxMessage
from edi_reference.domain.processing import ProcessingClaim, ProcessingClaimStatus


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 4, 11, 0, tzinfo=UTC)

    def now(self):
        return self.value


class Ids:
    def __init__(self):
        self.n = 0

    def new_id(self):
        self.n += 1
        return f"run-{self.n}"


class Processor:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def process(self, claim):
        self.calls += 1
        if self.fail:
            raise RuntimeError("sensitive provider detail")


def message():
    return OutboxMessage(
        message_id="msg-1",
        tenant_id="tenant-a",
        application_id="app-a",
        correlation_id="corr",
        aggregate_id="inbound-1",
        message_type="PROCESS_DOCUMENT",
        payload_ref="sha256:" + "a" * 64,
        created_at=Clock().now(),
        observation_id="obs-1",
    )


def test_redelivery_after_completion_is_deduplicated():
    repo, processor, clock, ids = InMemoryProcessingClaimRepository(), Processor(), Clock(), Ids()
    first = consume_processing_message(message(), repository=repo, processor=processor, clock=clock, ids=ids)
    second = consume_processing_message(message(), repository=repo, processor=processor, clock=clock, ids=ids)
    assert first.status is ProcessingClaimStatus.COMPLETED
    assert second == first
    assert processor.calls == 1


def test_active_lease_prevents_concurrent_processing():
    clock = Clock()
    repo = InMemoryProcessingClaimRepository()
    repo.save(ProcessingClaim(
        message_id="msg-1", processing_run_id="run-existing",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.CLAIMED,
        claimed_at=clock.now(), lease_until=clock.now() + timedelta(minutes=5),
    ))
    processor = Processor()
    result = consume_processing_message(message(), repository=repo, processor=processor, clock=clock, ids=Ids())
    assert result.processing_run_id == "run-existing"
    assert processor.calls == 0


def test_expired_lease_can_be_reclaimed_without_new_run_identity():
    clock = Clock()
    repo = InMemoryProcessingClaimRepository()
    repo.save(ProcessingClaim(
        message_id="msg-1", processing_run_id="run-existing",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.CLAIMED,
        claimed_at=clock.now() - timedelta(minutes=10), lease_until=clock.now() - timedelta(minutes=5),
    ))
    processor = Processor()
    result = consume_processing_message(message(), repository=repo, processor=processor, clock=clock, ids=Ids())
    assert result.status is ProcessingClaimStatus.COMPLETED
    assert result.processing_run_id == "run-existing"
    assert processor.calls == 1


def test_failure_stores_stable_code_not_exception_detail():
    repo, processor = InMemoryProcessingClaimRepository(), Processor(fail=True)
    result = consume_processing_message(message(), repository=repo, processor=processor, clock=Clock(), ids=Ids())
    assert result.status is ProcessingClaimStatus.FAILED
    assert result.failure_code == "PROCESSING_FAILED"


def test_reclaim_advances_generation():
    clock = Clock()
    repo = InMemoryProcessingClaimRepository()
    repo.save(ProcessingClaim(
        message_id="msg-1", processing_run_id="run-existing",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.CLAIMED,
        claimed_at=clock.now() - timedelta(minutes=10),
        lease_until=clock.now() - timedelta(minutes=5),
        claim_generation=7,
    ))
    result = consume_processing_message(message(), repository=repo, processor=Processor(), clock=clock, ids=Ids())
    assert result.status is ProcessingClaimStatus.COMPLETED
    assert result.claim_generation == 8


def test_stale_worker_cannot_overwrite_newer_claim_generation():
    repo = InMemoryProcessingClaimRepository()
    now = Clock().now()
    newer = ProcessingClaim(
        message_id="msg-1", processing_run_id="run-existing",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.CLAIMED,
        claimed_at=now, lease_until=now + timedelta(minutes=5),
        claim_generation=8,
    )
    repo.save(newer)
    stale_completion = ProcessingClaim(
        message_id="msg-1", processing_run_id="run-existing",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.COMPLETED,
        claimed_at=now - timedelta(minutes=10), lease_until=now - timedelta(minutes=5),
        claim_generation=7, completed_at=now,
    )
    assert repo.save_if_generation(stale_completion, 7, now=now) is False
    assert repo.get("msg-1") == newer


def test_processing_requires_observation_identity():
    msg = message()
    without_observation = OutboxMessage(
        message_id=msg.message_id,
        tenant_id=msg.tenant_id,
        application_id=msg.application_id,
        correlation_id=msg.correlation_id,
        aggregate_id=msg.aggregate_id,
        message_type=msg.message_type,
        payload_ref=msg.payload_ref,
        created_at=msg.created_at,
    )
    import pytest
    with pytest.raises(ValueError, match="OBSERVATION_ID_REQUIRED"):
        consume_processing_message(
            without_observation,
            repository=InMemoryProcessingClaimRepository(),
            processor=Processor(),
            clock=Clock(),
            ids=Ids(),
        )


def test_processing_claim_carries_observation_identity():
    result = consume_processing_message(
        message(),
        repository=InMemoryProcessingClaimRepository(),
        processor=Processor(),
        clock=Clock(),
        ids=Ids(),
    )
    assert result.observation_id == "obs-1"
