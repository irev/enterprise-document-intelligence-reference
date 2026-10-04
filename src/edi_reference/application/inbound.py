"""RI-1.5 durable inbound lifecycle orchestration."""

from dataclasses import replace
from typing import Protocol

from edi_reference.application.acquire import AcquisitionOutcome, acquire_and_validate
from edi_reference.application.ports import (
    AcquisitionAuditSink,
    ApplicationAuthorizer,
    ApplicationPrincipal,
    SourceAcquirer,
)
from edi_reference.domain.inbound import InboundRecord, InboundStatus, ProcessingDispatch
from edi_reference.domain.outbox import OutboxMessage
from edi_reference.domain.ingestion import Clock, IdGenerator, SourcePolicy
from edi_reference.domain.integration import InteractionContext
from edi_reference.domain.source import SourceReference
from edi_reference.application.security import validate_source_reference


class InboundRepository(Protocol):
    def get_by_idempotency(self, tenant_id: str, application_id: str, key: str) -> InboundRecord | None: ...
    def save(self, record: InboundRecord) -> None: ...


class ProcessingDispatcher(Protocol):
    def dispatch(self, item: ProcessingDispatch) -> None: ...


class InboundAcceptanceStore(Protocol):
    """Atomically persist ACCEPTED inbound state and its processing outbox message."""

    def accept_and_enqueue(self, record: InboundRecord, message: OutboxMessage) -> None: ...


def receive_document(
    *,
    principal: ApplicationPrincipal,
    context: InteractionContext,
    source: SourceReference,
    authorizer: ApplicationAuthorizer,
    acquirer: SourceAcquirer,
    audit: AcquisitionAuditSink,
    repository: InboundRepository,
    dispatcher: ProcessingDispatcher | None,
    acceptance_store: InboundAcceptanceStore | None = None,
    policy: SourcePolicy,
    clock: Clock,
    ids: IdGenerator,
) -> InboundRecord:
    validate_source_reference(source)

    if not context.request_id or not context.idempotency_key:
        raise ValueError("REQUEST_ID_AND_IDEMPOTENCY_KEY_REQUIRED")

    existing = repository.get_by_idempotency(
        context.tenant_id, context.application_id, context.idempotency_key
    )
    if existing is not None:
        return existing

    now = clock.now()
    record = InboundRecord(
        inbound_id=ids.new_id(),
        tenant_id=context.tenant_id,
        application_id=context.application_id,
        correlation_id=context.correlation_id,
        request_id=context.request_id,
        idempotency_key=context.idempotency_key,
        source_method=source.method.value,
        status=InboundStatus.RECEIVED,
        received_at=now,
        updated_at=now,
    )
    repository.save(record)
    repository.save(replace(record, status=InboundStatus.ACQUIRING, updated_at=clock.now()))

    event = acquire_and_validate(
        principal=principal,
        context=context,
        source=source,
        authorizer=authorizer,
        acquirer=acquirer,
        audit=audit,
        policy=policy,
        clock=clock,
    )

    mapping = {
        AcquisitionOutcome.ACQUIRED: InboundStatus.ACCEPTED,
        AcquisitionOutcome.REJECTED: InboundStatus.REJECTED,
        AcquisitionOutcome.UNSUPPORTED: InboundStatus.UNSUPPORTED,
        AcquisitionOutcome.FAILED: InboundStatus.FAILED,
    }
    final = replace(
        record,
        status=mapping[event.outcome],
        updated_at=clock.now(),
        observation_sha256=event.sha256,
        failure_code=event.failure_code,
    )
    if final.status is InboundStatus.ACCEPTED and final.observation_sha256:
        if acceptance_store is not None:
            acceptance_store.accept_and_enqueue(
                final,
                OutboxMessage(
                    message_id=ids.new_id(),
                    tenant_id=final.tenant_id,
                    application_id=final.application_id,
                    correlation_id=final.correlation_id,
                    aggregate_id=final.inbound_id,
                    message_type="PROCESS_DOCUMENT",
                    payload_ref="sha256:" + final.observation_sha256,
                    created_at=clock.now(),
                ),
            )
        else:
            # Compatibility path for the reference's earlier dispatcher port.
            # Production adapters must use acceptance_store to close the commit/dispatch crash window.
            repository.save(final)
            if dispatcher is None:
                raise ValueError("PROCESSING_DISPATCHER_REQUIRED")
            dispatcher.dispatch(
                ProcessingDispatch(
                    dispatch_id=ids.new_id(),
                    inbound_id=final.inbound_id,
                    tenant_id=final.tenant_id,
                    application_id=final.application_id,
                    correlation_id=final.correlation_id,
                    observation_sha256=final.observation_sha256,
                    created_at=clock.now(),
                )
            )
    else:
        repository.save(final)

    return final
