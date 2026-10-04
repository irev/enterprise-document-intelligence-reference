from datetime import UTC, datetime, timedelta

from edi_reference.adapters.processing_memory import InMemoryProcessingClaimRepository
from edi_reference.application.processing_consumer import consume_processing_message, renew_processing_lease
from edi_reference.domain.outbox import OutboxMessage
from edi_reference.domain.processing import ProcessingClaim, ProcessingClaimStatus
from edi_reference.domain.lineage import SourceObservation


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


class Observations:
    def __init__(self, item=None):
        self.item = item or SourceObservation(
            "obs-1", "inbound-1", "tenant-a", "app-a", "a" * 64,
            100, "application/pdf", Clock().now(),
        )

    def get(self, observation_id):
        return self.item if self.item.observation_id == observation_id else None


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
    first = consume_processing_message(message(), repository=repo, processor=processor, observations=Observations(), clock=clock, ids=ids)
    second = consume_processing_message(message(), repository=repo, processor=processor, observations=Observations(), clock=clock, ids=ids)
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
    result = consume_processing_message(message(), repository=repo, processor=processor, observations=Observations(), clock=clock, ids=Ids())
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
    result = consume_processing_message(message(), repository=repo, processor=processor, observations=Observations(), clock=clock, ids=Ids())
    assert result.status is ProcessingClaimStatus.COMPLETED
    assert result.processing_run_id == "run-existing"
    assert processor.calls == 1


def test_failure_stores_stable_code_not_exception_detail():
    repo, processor = InMemoryProcessingClaimRepository(), Processor(fail=True)
    result = consume_processing_message(message(), repository=repo, processor=processor, observations=Observations(), clock=Clock(), ids=Ids())
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
    result = consume_processing_message(message(), repository=repo, processor=Processor(), observations=Observations(), clock=clock, ids=Ids())
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
            observations=Observations(),
            clock=Clock(),
            ids=Ids(),
        )


def test_processing_claim_carries_observation_identity():
    result = consume_processing_message(
        message(),
        repository=InMemoryProcessingClaimRepository(),
        processor=Processor(),
        observations=Observations(),
        clock=Clock(),
        ids=Ids(),
    )
    assert result.observation_id == "obs-1"


def test_processing_digest_is_resolved_from_observation_not_payload_reference():
    msg = message()
    misleading_payload = OutboxMessage(
        message_id=msg.message_id,
        tenant_id=msg.tenant_id,
        application_id=msg.application_id,
        correlation_id=msg.correlation_id,
        aggregate_id=msg.aggregate_id,
        message_type=msg.message_type,
        payload_ref="sha256:" + "f" * 64,
        created_at=msg.created_at,
        observation_id=msg.observation_id,
    )
    result = consume_processing_message(
        misleading_payload,
        repository=InMemoryProcessingClaimRepository(),
        processor=Processor(),
        observations=Observations(),
        clock=Clock(),
        ids=Ids(),
    )
    assert result.observation_sha256 == "a" * 64


def test_active_claim_lease_can_be_renewed_without_advancing_generation():
    clock = Clock()
    repo = InMemoryProcessingClaimRepository()
    claim = ProcessingClaim(
        message_id="renew-msg", processing_run_id="renew-run",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.CLAIMED,
        claimed_at=clock.now(), lease_until=clock.now() + timedelta(minutes=1),
        claim_generation=3,
    )
    repo.save(claim)
    renewed = renew_processing_lease(
        claim, repository=repo, clock=clock, lease_seconds=300
    )
    assert renewed.claim_generation == 3
    assert renewed.lease_until == clock.now() + timedelta(seconds=300)
    assert repo.get("renew-msg") == renewed


def test_expired_claim_lease_cannot_be_renewed():
    import pytest
    clock = Clock()
    repo = InMemoryProcessingClaimRepository()
    claim = ProcessingClaim(
        message_id="expired-renew-msg", processing_run_id="renew-run",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.CLAIMED,
        claimed_at=clock.now() - timedelta(minutes=10),
        lease_until=clock.now() - timedelta(seconds=1), claim_generation=3,
    )
    repo.save(claim)
    with pytest.raises(RuntimeError, match="CLAIM_LEASE_LOST"):
        renew_processing_lease(claim, repository=repo, clock=clock)


def test_stale_generation_cannot_renew_newer_claim():
    import pytest
    clock = Clock()
    repo = InMemoryProcessingClaimRepository()
    current = ProcessingClaim(
        message_id="stale-renew-msg", processing_run_id="renew-run",
        tenant_id="tenant-a", application_id="app-a",
        observation_sha256="a" * 64, status=ProcessingClaimStatus.CLAIMED,
        claimed_at=clock.now(), lease_until=clock.now() + timedelta(minutes=5),
        claim_generation=4,
    )
    repo.save(current)
    stale = ProcessingClaim(
        message_id=current.message_id, processing_run_id=current.processing_run_id,
        tenant_id=current.tenant_id, application_id=current.application_id,
        observation_sha256=current.observation_sha256,
        status=ProcessingClaimStatus.CLAIMED,
        claimed_at=clock.now() - timedelta(minutes=10),
        lease_until=clock.now() + timedelta(minutes=1), claim_generation=3,
    )
    with pytest.raises(RuntimeError, match="CLAIM_LEASE_LOST"):
        renew_processing_lease(stale, repository=repo, clock=clock)
    assert repo.get(current.message_id) == current


class LeaseAwareProcessor:
    def __init__(self, clock):
        self.clock = clock
        self.calls = 0
        self.renewed = None

    def process(self, claim, renew_lease):
        self.calls += 1
        self.clock.value += timedelta(seconds=30)
        self.renewed = renew_lease()


def test_long_running_processor_renews_lease_before_finalization():
    clock = Clock()
    repo = InMemoryProcessingClaimRepository()
    processor = LeaseAwareProcessor(clock)

    result = consume_processing_message(
        message(),
        repository=repo,
        processor=processor,
        observations=Observations(),
        clock=clock,
        ids=Ids(),
        lease_seconds=60,
        lease_aware=True,
    )

    assert processor.calls == 1
    assert processor.renewed is not None
    assert processor.renewed.claim_generation == 1
    assert processor.renewed.lease_until == clock.now() + timedelta(seconds=60)
    assert result.status is ProcessingClaimStatus.COMPLETED
    assert result.claim_generation == 1
    assert result.lease_until == processor.renewed.lease_until
