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


def test_stale_generation_cannot_complete_reclaimed_claim():
    now = datetime.now(UTC)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('claim-tenant') ON CONFLICT DO NOTHING")
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES ('claim-tenant','claim-app') ON CONFLICT DO NOTHING"""
            )
            cursor.execute("DELETE FROM processing.processing_claim WHERE message_id='claim-message'")
            cursor.execute("DELETE FROM integration.outbox_message WHERE message_id='claim-message'")
            cursor.execute("DELETE FROM ingestion.inbound_request WHERE inbound_id='claim-inbound'")
            cursor.execute(
                """INSERT INTO ingestion.inbound_request
                   (inbound_id, tenant_id, application_id, correlation_id, request_id,
                    idempotency_key, request_fingerprint, source_method, status,
                    received_at, updated_at, observation_sha256)
                   VALUES ('claim-inbound','claim-tenant','claim-app','corr','req','idem-claim',
                           %s,'UPLOAD','ACCEPTED',%s,%s,%s)""",
                ("a" * 64, now, now, "b" * 64),
            )
            cursor.execute(
                """INSERT INTO integration.outbox_message
                   (message_id, tenant_id, application_id, correlation_id, aggregate_id,
                    message_type, payload_ref, created_at)
                   VALUES ('claim-message','claim-tenant','claim-app','corr','claim-inbound',
                           'PROCESS_DOCUMENT',%s,%s)""",
                ("sha256:" + "b" * 64, now),
            )

    repo = PostgreSqlProcessingClaimRepository(connect)
    generation_1 = ProcessingClaim(
        "claim-message", "run-claim", "claim-tenant", "claim-app", "b" * 64,
        ProcessingClaimStatus.CLAIMED, now - timedelta(minutes=10),
        now - timedelta(minutes=5), 1,
    )
    assert repo.try_create(generation_1)

    generation_2 = ProcessingClaim(
        "claim-message", "run-claim", "claim-tenant", "claim-app", "b" * 64,
        ProcessingClaimStatus.CLAIMED, now, now + timedelta(minutes=5), 2,
    )
    repo.save(generation_2)

    stale_completion = ProcessingClaim(
        "claim-message", "run-claim", "claim-tenant", "claim-app", "b" * 64,
        ProcessingClaimStatus.COMPLETED, generation_1.claimed_at,
        generation_1.lease_until, 1, completed_at=now,
    )
    assert repo.save_if_generation(stale_completion, 1) is False
    assert repo.get("claim-message") == generation_2

    valid_completion = ProcessingClaim(
        "claim-message", "run-claim", "claim-tenant", "claim-app", "b" * 64,
        ProcessingClaimStatus.COMPLETED, generation_2.claimed_at,
        generation_2.lease_until, 2, completed_at=now,
    )
    assert repo.save_if_generation(valid_completion, 2)
    assert repo.get("claim-message").status is ProcessingClaimStatus.COMPLETED
