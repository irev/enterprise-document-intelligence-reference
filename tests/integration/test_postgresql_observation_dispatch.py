import os
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.postgresql_lineage import PostgreSqlObservationRepository
from edi_reference.adapters.postgresql_processing import PostgreSqlProcessingClaimRepository
from edi_reference.application.processing_consumer import consume_processing_message
from edi_reference.domain.lineage import ScopedObservation
from edi_reference.domain.outbox import OutboxMessage
from edi_reference.domain.processing import ProcessingClaimStatus

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


class Clock:
    def __init__(self, value):
        self.value = value

    def now(self):
        return self.value


class Ids:
    def new_id(self):
        return "run-observation-dispatch"


class Processor:
    def __init__(self):
        self.claim = None

    def process(self, claim):
        self.claim = claim


def test_processing_resolves_exact_observation_not_payload_digest():
    now = datetime.now(UTC)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('dispatch-tenant') ON CONFLICT DO NOTHING")
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES ('dispatch-tenant','dispatch-app') ON CONFLICT DO NOTHING"""
            )
            cursor.execute("DELETE FROM processing.processing_claim WHERE message_id='dispatch-message'")
            cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='dispatch-observation'")
            cursor.execute("DELETE FROM ingestion.document WHERE document_id='dispatch-document'")
            cursor.execute(
                """INSERT INTO ingestion.document
                   (document_id, tenant_id, application_id, created_at)
                   VALUES ('dispatch-document','dispatch-tenant','dispatch-app',%s)""",
                (now,),
            )
            cursor.execute(
                """INSERT INTO ingestion.source_observation
                   (observation_id, document_id, tenant_id, application_id, sha256,
                    byte_length, detected_media_type, observed_at)
                   VALUES ('dispatch-observation','dispatch-document','dispatch-tenant',
                           'dispatch-app',%s,123,'application/pdf',%s)""",
                ("a" * 64, now),
            )

    message = OutboxMessage(
        message_id="dispatch-message",
        tenant_id="dispatch-tenant",
        application_id="dispatch-app",
        correlation_id="corr",
        aggregate_id="dispatch-document",
        message_type="PROCESS_DOCUMENT",
        payload_ref="sha256:" + "f" * 64,
        created_at=now,
        observation_id="dispatch-observation",
    )
    processor = Processor()
    result = consume_processing_message(
        message,
        repository=PostgreSqlProcessingClaimRepository(connect),
        processor=processor,
        observations=PostgreSqlObservationRepository(connect),
        clock=Clock(now),
        ids=Ids(),
    )

    assert result.status is ProcessingClaimStatus.COMPLETED
    assert result.observation_id == "dispatch-observation"
    assert result.observation_sha256 == "a" * 64
    assert processor.claim.observation_id == "dispatch-observation"
