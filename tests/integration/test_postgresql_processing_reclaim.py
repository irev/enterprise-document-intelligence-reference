import os
from datetime import UTC, datetime, timedelta

import pytest

from edi_reference.adapters.postgresql_processing import PostgreSqlProcessingClaimRepository
from edi_reference.domain.processing import ProcessingClaim, ProcessingClaimStatus

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def test_only_one_worker_can_reclaim_same_generation():
    now = datetime.now(UTC)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('cas-tenant') ON CONFLICT DO NOTHING")
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES ('cas-tenant','cas-app') ON CONFLICT DO NOTHING"""
            )
            cursor.execute("DELETE FROM processing.processing_claim WHERE message_id='cas-message'")
            cursor.execute("DELETE FROM integration.outbox_message WHERE message_id='cas-message'")
            cursor.execute("DELETE FROM ingestion.inbound_request WHERE inbound_id='cas-inbound'")
            cursor.execute(
                """INSERT INTO ingestion.inbound_request
                   (inbound_id, tenant_id, application_id, correlation_id, request_id,
                    idempotency_key, request_fingerprint, source_method, status,
                    received_at, updated_at, observation_sha256)
                   VALUES ('cas-inbound','cas-tenant','cas-app','corr','req','idem-cas',
                           %s,'UPLOAD','ACCEPTED',%s,%s,%s)""",
                ("a" * 64, now, now, "b" * 64),
            )
            cursor.execute(
                """INSERT INTO integration.outbox_message
                   (message_id, tenant_id, application_id, correlation_id, aggregate_id,
                    message_type, payload_ref, created_at)
                   VALUES ('cas-message','cas-tenant','cas-app','corr','cas-inbound',
                           'PROCESS_DOCUMENT',%s,%s)""",
                ("sha256:" + "b" * 64, now),
            )

    repo = PostgreSqlProcessingClaimRepository(connect)
    expired = ProcessingClaim(
        "cas-message", "run-cas", "cas-tenant", "cas-app", "b" * 64,
        ProcessingClaimStatus.CLAIMED, now - timedelta(minutes=10),
        now - timedelta(minutes=5), 4,
    )
    assert repo.try_create(expired)

    worker_a = ProcessingClaim(
        "cas-message", "run-cas", "cas-tenant", "cas-app", "b" * 64,
        ProcessingClaimStatus.CLAIMED, now, now + timedelta(minutes=5), 5,
    )
    worker_b = ProcessingClaim(
        "cas-message", "run-cas", "cas-tenant", "cas-app", "b" * 64,
        ProcessingClaimStatus.CLAIMED, now, now + timedelta(minutes=5), 5,
    )

    assert repo.try_reclaim(worker_a, 4, now=now) is True
    assert repo.try_reclaim(worker_b, 4, now=now) is False
    assert repo.get("cas-message").claim_generation == 5


def test_active_lease_cannot_be_reclaimed_even_with_matching_generation():
    now = datetime.now(UTC)
    repo = PostgreSqlProcessingClaimRepository(connect)
    current = repo.get("cas-message")
    assert current is not None
    active = ProcessingClaim(
        current.message_id, current.processing_run_id, current.tenant_id,
        current.application_id, current.observation_sha256,
        ProcessingClaimStatus.CLAIMED, now, now + timedelta(minutes=5),
        current.claim_generation + 1,
    )
    assert repo.try_reclaim(active, current.claim_generation, now=now) is False
