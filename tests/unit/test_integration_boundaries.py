from datetime import UTC, datetime

from edi_reference.domain.integration import (
    DeliveryAttempt,
    DeliveryStatus,
    InteractionContext,
)


def test_interaction_keeps_application_and_tenant_identity_distinct() -> None:
    context = InteractionContext(
        tenant_id="tenant-synthetic",
        application_id="app-synthetic",
        correlation_id="corr-001",
        request_id="req-001",
    )

    assert context.tenant_id != context.application_id
    assert context.correlation_id == "corr-001"


def test_delivery_state_is_separate_from_document_processing_state() -> None:
    attempt = DeliveryAttempt(
        delivery_id="delivery-001",
        message_id="message-001",
        subscription_id="subscription-001",
        tenant_id="tenant-synthetic",
        application_id="app-synthetic",
        correlation_id="corr-001",
        document_id="document-001",
        result_version="1",
        attempt=2,
        attempted_at=datetime(2026, 10, 4, tzinfo=UTC),
        status=DeliveryStatus.RETRY_PENDING,
        failure_code="DESTINATION_UNAVAILABLE",
    )

    assert attempt.status is DeliveryStatus.RETRY_PENDING
    assert attempt.document_id == "document-001"
