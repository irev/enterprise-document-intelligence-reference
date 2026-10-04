from datetime import UTC, datetime

from edi_reference.adapters.in_memory import InMemoryAcquisitionAudit, StaticApplicationAuthorizer
from edi_reference.adapters.inbound_memory import InMemoryAtomicAcceptanceStore, InMemoryInboundRepository, InMemoryProcessingDispatcher
from edi_reference.application.inbound import receive_document
from edi_reference.application.ports import AcquiredSource, ApplicationPrincipal
from edi_reference.domain.ingestion import SourcePolicy
from edi_reference.domain.integration import InteractionContext
from edi_reference.domain.source import AcquisitionMethod, SourceReference


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


class SequentialIds:
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> str:
        self.value += 1
        return f"id-{self.value}"


class StaticAcquirer:
    calls = 0

    def acquire(self, source, context):
        self.calls += 1
        return AcquiredSource(content=b"%PDF-1.7\nsynthetic", declared_media_type="application/pdf")


def ctx(key: str = "idem-1") -> InteractionContext:
    return InteractionContext(
        tenant_id="tenant-a",
        application_id="app-a",
        correlation_id="corr-1",
        request_id="req-1",
        idempotency_key=key,
    )


def test_accepted_inbound_is_persisted_and_dispatched() -> None:
    repository = InMemoryInboundRepository()
    dispatcher = InMemoryProcessingDispatcher()
    result = receive_document(
        principal=ApplicationPrincipal("app-a"),
        context=ctx(),
        source=SourceReference(method=AcquisitionMethod.UPLOAD),
        authorizer=StaticApplicationAuthorizer({("app-a", "tenant-a")}),
        acquirer=StaticAcquirer(),
        audit=InMemoryAcquisitionAudit(),
        repository=repository,
        dispatcher=dispatcher,
        policy=SourcePolicy(1024, frozenset({"application/pdf"})),
        clock=FixedClock(),
        ids=SequentialIds(),
    )

    assert result.status.value == "ACCEPTED"
    assert result.observation_sha256
    assert repository.records[result.inbound_id] == result
    assert len(dispatcher.items) == 1
    assert dispatcher.items[0].observation_sha256 == result.observation_sha256


def test_same_idempotency_key_does_not_reacquire_or_redispatch() -> None:
    repository = InMemoryInboundRepository()
    dispatcher = InMemoryProcessingDispatcher()
    acquirer = StaticAcquirer()
    common = dict(
        principal=ApplicationPrincipal("app-a"),
        context=ctx(),
        source=SourceReference(method=AcquisitionMethod.UPLOAD),
        authorizer=StaticApplicationAuthorizer({("app-a", "tenant-a")}),
        acquirer=acquirer,
        audit=InMemoryAcquisitionAudit(),
        repository=repository,
        dispatcher=dispatcher,
        policy=SourcePolicy(1024, frozenset({"application/pdf"})),
        clock=FixedClock(),
        ids=SequentialIds(),
    )

    first = receive_document(**common)
    second = receive_document(**common)

    assert second == first
    assert acquirer.calls == 1
    assert len(dispatcher.items) == 1


def test_idempotency_is_scoped_by_application_and_tenant() -> None:
    repository = InMemoryInboundRepository()
    repository.save(
        __import__("edi_reference.domain.inbound", fromlist=["InboundRecord"]).InboundRecord(
            inbound_id="existing",
            tenant_id="tenant-a",
            application_id="app-a",
            correlation_id="corr",
            request_id="req",
            idempotency_key="same",
            source_method="UPLOAD",
            status=__import__("edi_reference.domain.inbound", fromlist=["InboundStatus"]).InboundStatus.RECEIVED,
            received_at=FixedClock().now(),
            updated_at=FixedClock().now(),
        )
    )

    assert repository.get_by_idempotency("tenant-a", "app-a", "same") is not None
    assert repository.get_by_idempotency("tenant-a", "app-b", "same") is None
    assert repository.get_by_idempotency("tenant-b", "app-a", "same") is None


def test_atomic_acceptance_persists_state_and_pending_outbox_together() -> None:
    repository = InMemoryInboundRepository()
    store = InMemoryAtomicAcceptanceStore(repository)
    result = receive_document(
        principal=ApplicationPrincipal("app-a"),
        context=ctx("atomic-1"),
        source=SourceReference(method=AcquisitionMethod.UPLOAD),
        authorizer=StaticApplicationAuthorizer({("app-a", "tenant-a")}),
        acquirer=StaticAcquirer(),
        audit=InMemoryAcquisitionAudit(),
        repository=repository,
        dispatcher=None,
        acceptance_store=store,
        policy=SourcePolicy(1024, frozenset({"application/pdf"})),
        clock=FixedClock(),
        ids=SequentialIds(),
    )
    assert result.status.value == "ACCEPTED"
    assert repository.records[result.inbound_id].status.value == "ACCEPTED"
    assert len(store.outbox) == 1
    message = next(iter(store.outbox.values()))
    assert message.aggregate_id == result.inbound_id
    assert message.payload_ref == "sha256:" + result.observation_sha256


def test_atomic_acceptance_failure_does_not_persist_accepted_state_or_outbox() -> None:
    import pytest

    repository = InMemoryInboundRepository()
    store = InMemoryAtomicAcceptanceStore(repository, fail_before_commit=True)
    with pytest.raises(RuntimeError, match="ATOMIC_ACCEPTANCE_FAILED"):
        receive_document(
            principal=ApplicationPrincipal("app-a"),
            context=ctx("atomic-fail"),
            source=SourceReference(method=AcquisitionMethod.UPLOAD),
            authorizer=StaticApplicationAuthorizer({("app-a", "tenant-a")}),
            acquirer=StaticAcquirer(),
            audit=InMemoryAcquisitionAudit(),
            repository=repository,
            dispatcher=None,
            acceptance_store=store,
            policy=SourcePolicy(1024, frozenset({"application/pdf"})),
            clock=FixedClock(),
            ids=SequentialIds(),
        )
    assert not store.outbox
    assert all(record.status.value != "ACCEPTED" for record in repository.records.values())
