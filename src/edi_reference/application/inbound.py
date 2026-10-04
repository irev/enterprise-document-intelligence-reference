"""RI-1.5 durable inbound lifecycle orchestration."""

from dataclasses import replace
import hashlib
import json
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
from edi_reference.domain.lineage import SourceObservation
from edi_reference.domain.ingestion import Clock, IdGenerator, SourcePolicy
from edi_reference.domain.integration import InteractionContext
from edi_reference.domain.source import SourceReference
from edi_reference.application.security import validate_source_reference


class InboundRepository(Protocol):
    def get_by_idempotency(self, tenant_id: str, application_id: str, key: str) -> InboundRecord | None: ...
    def save(self, record: InboundRecord) -> None: ...


class IdempotencyConflict(ValueError):
    pass


def request_fingerprint(source: SourceReference) -> str:
    material = {
        "method": source.method.value,
        "resource_locator": source.resource_locator,
        "connector_id": source.connector_id,
        "external_version": source.external_version,
        "expected_sha256": source.expected_sha256.lower() if source.expected_sha256 else None,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ProcessingDispatcher(Protocol):
    def dispatch(self, item: ProcessingDispatch) -> None: ...


class InboundAcceptanceStore(Protocol):
    """Atomically persist accepted inbound state, observation, and processing outbox."""

    def accept_and_enqueue(
        self, record: InboundRecord, observation: SourceObservation, message: OutboxMessage
    ) -> None: ...


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

    fingerprint = request_fingerprint(source)
    existing = repository.get_by_idempotency(
        context.tenant_id, context.application_id, context.idempotency_key
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise IdempotencyConflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST")
        return existing

    now = clock.now()
    record = InboundRecord(
        inbound_id=ids.new_id(),
        tenant_id=context.tenant_id,
        application_id=context.application_id,
        correlation_id=context.correlation_id,
        request_id=context.request_id,
        idempotency_key=context.idempotency_key,
        request_fingerprint=fingerprint,
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
        if event.byte_length is None or event.media_type is None:
            raise ValueError("ACCEPTED_ACQUISITION_REQUIRES_OBSERVATION_METADATA")
        if acceptance_store is not None:
            observation = SourceObservation(
                observation_id=ids.new_id(),
                document_id=final.inbound_id,
                tenant_id=final.tenant_id,
                application_id=final.application_id,
                sha256=final.observation_sha256.lower(),
                byte_length=event.byte_length,
                detected_media_type=event.media_type,
                observed_at=event.occurred_at,
                external_version=event.external_version,
            )
            acceptance_store.accept_and_enqueue(
                final,
                observation,
                OutboxMessage(
                    message_id=ids.new_id(),
                    tenant_id=final.tenant_id,
                    application_id=final.application_id,
                    correlation_id=final.correlation_id,
                    aggregate_id=final.inbound_id,
                    message_type="PROCESS_DOCUMENT",
                    payload_ref="sha256:" + final.observation_sha256,
                    created_at=clock.now(),
                    observation_id=observation.observation_id,
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
