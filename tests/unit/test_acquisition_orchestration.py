from datetime import UTC, datetime

import pytest

from edi_reference.adapters.in_memory import (
    AccessDeniedError,
    InMemoryAcquisitionAudit,
    StaticApplicationAuthorizer,
)
from edi_reference.application.acquire import AcquisitionOutcome, acquire_and_validate
from edi_reference.application.ports import AcquiredSource, ApplicationPrincipal
from edi_reference.domain.ingestion import SourcePolicy
from edi_reference.domain.integration import InteractionContext
from edi_reference.domain.source import AcquisitionMethod, SourceReference


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 4, 8, 0, tzinfo=UTC)


class StaticAcquirer:
    def acquire(self, source: SourceReference, context: InteractionContext) -> AcquiredSource:
        return AcquiredSource(
            content=b"%PDF-1.7\nsynthetic",
            declared_media_type="application/pdf",
            filename="synthetic.pdf",
            external_version="17",
            etag="etag-synthetic",
            connector_version="cfg-3",
        )


POLICY = SourcePolicy(
    max_bytes=1024,
    allowed_media_types=frozenset({"application/pdf"}),
)


def context(application_id: str = "app-a", tenant_id: str = "tenant-a") -> InteractionContext:
    return InteractionContext(
        tenant_id=tenant_id,
        application_id=application_id,
        correlation_id="corr-001",
    )


def test_authorized_application_acquires_and_audits_observed_bytes() -> None:
    audit = InMemoryAcquisitionAudit()
    event = acquire_and_validate(
        principal=ApplicationPrincipal("app-a"),
        context=context(),
        source=SourceReference(
            method=AcquisitionMethod.CONNECTOR,
            connector_id="connector-a",
            resource_locator="resource-001",
        ),
        authorizer=StaticApplicationAuthorizer({("app-a", "tenant-a")}),
        acquirer=StaticAcquirer(),
        audit=audit,
        policy=POLICY,
        clock=FixedClock(),
    )

    assert event.outcome is AcquisitionOutcome.ACQUIRED
    assert event.sha256 is not None
    assert event.external_version == "17"
    assert event.connector_version == "cfg-3"
    assert audit.events == [event]


def test_application_cannot_claim_another_application_identity() -> None:
    with pytest.raises(AccessDeniedError, match="APPLICATION_CONTEXT_MISMATCH"):
        acquire_and_validate(
            principal=ApplicationPrincipal("app-b"),
            context=context(application_id="app-a"),
            source=SourceReference(method=AcquisitionMethod.UPLOAD),
            authorizer=StaticApplicationAuthorizer({("app-a", "tenant-a")}),
            acquirer=StaticAcquirer(),
            audit=InMemoryAcquisitionAudit(),
            policy=POLICY,
            clock=FixedClock(),
        )


def test_application_must_be_granted_to_tenant() -> None:
    with pytest.raises(AccessDeniedError, match="TENANT_ACCESS_DENIED"):
        acquire_and_validate(
            principal=ApplicationPrincipal("app-a"),
            context=context(tenant_id="tenant-b"),
            source=SourceReference(method=AcquisitionMethod.UPLOAD),
            authorizer=StaticApplicationAuthorizer({("app-a", "tenant-a")}),
            acquirer=StaticAcquirer(),
            audit=InMemoryAcquisitionAudit(),
            policy=POLICY,
            clock=FixedClock(),
        )
