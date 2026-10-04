"""In-memory inbound persistence and dispatch adapters."""

from dataclasses import dataclass, field

from edi_reference.domain.inbound import InboundRecord, ProcessingDispatch
from edi_reference.domain.outbox import OutboxMessage


@dataclass
class InMemoryInboundRepository:
    records: dict[str, InboundRecord] = field(default_factory=dict)
    idempotency: dict[tuple[str, str, str], str] = field(default_factory=dict)

    def get_by_idempotency(self, tenant_id: str, application_id: str, key: str) -> InboundRecord | None:
        inbound_id = self.idempotency.get((tenant_id, application_id, key))
        return self.records.get(inbound_id) if inbound_id else None

    def save(self, record: InboundRecord) -> None:
        self.records[record.inbound_id] = record
        self.idempotency.setdefault(
            (record.tenant_id, record.application_id, record.idempotency_key),
            record.inbound_id,
        )


@dataclass
class InMemoryProcessingDispatcher:
    items: list[ProcessingDispatch] = field(default_factory=list)

    def dispatch(self, item: ProcessingDispatch) -> None:
        self.items.append(item)


@dataclass
class InMemoryAtomicAcceptanceStore:
    """Test adapter modelling one atomic commit of accepted state + outbox."""

    repository: InMemoryInboundRepository
    outbox: dict[str, OutboxMessage] = field(default_factory=dict)
    fail_before_commit: bool = False

    def accept_and_enqueue(self, record: InboundRecord, message: OutboxMessage) -> None:
        if self.fail_before_commit:
            raise RuntimeError("ATOMIC_ACCEPTANCE_FAILED")
        # Mutate both only after all pre-commit work succeeds.
        self.repository.save(record)
        self.outbox[message.message_id] = message
