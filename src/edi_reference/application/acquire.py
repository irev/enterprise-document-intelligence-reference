"""RI-1.5 acquisition orchestration without protocol coupling."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from edi_reference.application.ingest import ingest_source
from edi_reference.application.ports import (
    AcquisitionAuditSink,
    ApplicationAuthorizer,
    ApplicationPrincipal,
    SourceAcquirer,
)
from edi_reference.domain.ingestion import Clock, SourceDisposition, SourcePolicy, SourceSubmission
from edi_reference.domain.integration import InteractionContext
from edi_reference.domain.source import SourceReference


class AcquisitionOutcome(StrEnum):
    ACQUIRED = "ACQUIRED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class AcquisitionEvent:
    tenant_id: str
    application_id: str
    correlation_id: str
    method: str
    occurred_at: datetime
    outcome: AcquisitionOutcome
    sha256: str | None = None
    byte_length: int | None = None
    media_type: str | None = None
    external_version: str | None = None
    etag: str | None = None
    connector_version: str | None = None
    failure_code: str | None = None


def acquire_and_validate(
    *,
    principal: ApplicationPrincipal,
    context: InteractionContext,
    source: SourceReference,
    authorizer: ApplicationAuthorizer,
    acquirer: SourceAcquirer,
    audit: AcquisitionAuditSink,
    policy: SourcePolicy,
    clock: Clock,
) -> AcquisitionEvent:
    authorizer.authorize(principal, context)
    acquired = acquirer.acquire(source, context)

    receipt = ingest_source(
        SourceSubmission(
            content=acquired.content,
            declared_media_type=acquired.declared_media_type,
            filename=acquired.filename,
            context=context,
        ),
        policy=policy,
        clock=clock,
    )

    source_identity = receipt.source
    if receipt.disposition is SourceDisposition.ACCEPTED:
        outcome = AcquisitionOutcome.ACQUIRED
    elif receipt.disposition is SourceDisposition.UNSUPPORTED:
        outcome = AcquisitionOutcome.UNSUPPORTED
    else:
        outcome = AcquisitionOutcome.REJECTED

    event = AcquisitionEvent(
        tenant_id=context.tenant_id,
        application_id=context.application_id,
        correlation_id=context.correlation_id,
        method=source.method.value,
        occurred_at=receipt.received_at,
        outcome=outcome,
        sha256=source_identity.digest if source_identity else None,
        byte_length=source_identity.byte_length if source_identity else None,
        media_type=source_identity.detected_media_type if source_identity else None,
        external_version=acquired.external_version,
        etag=acquired.etag,
        connector_version=acquired.connector_version,
        failure_code=receipt.rejection_code.value if receipt.rejection_code else None,
    )
    audit.record(event)
    return event
