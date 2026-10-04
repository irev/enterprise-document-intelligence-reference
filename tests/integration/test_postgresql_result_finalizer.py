import os
from datetime import UTC, datetime, timedelta

import pytest

from edi_reference.adapters.postgresql_result_finalizer import (
    PostgreSqlProcessingResultFinalizer,
    ProcessingFinalizationRejected,
)
from edi_reference.domain.classification import ClassificationPrediction
from edi_reference.domain.processing_result import ProcessingResult

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg

    return psycopg.connect(DSN)


def seed(cursor, *, generation=1, lease_minutes=5):
    now = datetime.now(UTC)
    cursor.execute("DELETE FROM processing.evidence_reference WHERE result_id='final-result'")
    cursor.execute("DELETE FROM processing.processing_result WHERE result_id='final-result'")
    cursor.execute("DELETE FROM processing.processing_claim WHERE message_id='final-message'")
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='final-run'")
    cursor.execute("DELETE FROM integration.outbox_message WHERE message_id='final-message'")
    cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='final-observation'")
    cursor.execute("DELETE FROM ingestion.document WHERE document_id='final-document'")
    cursor.execute("DELETE FROM control_plane.application WHERE tenant_id='final-tenant'")
    cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id='final-tenant'")
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('final-tenant')")
    cursor.execute(
        """INSERT INTO control_plane.application (tenant_id,application_id)
           VALUES ('final-tenant','final-app')"""
    )
    cursor.execute(
        """INSERT INTO ingestion.document
           (document_id,tenant_id,application_id,created_at)
           VALUES ('final-document','final-tenant','final-app',%s)""",
        (now,),
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id,document_id,tenant_id,application_id,sha256,
            byte_length,detected_media_type,observed_at)
           VALUES ('final-observation','final-document','final-tenant','final-app',
                   %s,10,'application/pdf',%s)""",
        ("a" * 64, now),
    )
    cursor.execute(
        """INSERT INTO processing.processing_run
           (processing_run_id,document_id,tenant_id,application_id,observation_id,
            observation_sha256,created_at)
           VALUES ('final-run','final-document','final-tenant','final-app',
                   'final-observation',%s,%s)""",
        ("a" * 64, now),
    )
    cursor.execute(
        """INSERT INTO integration.outbox_message
           (message_id,tenant_id,application_id,correlation_id,aggregate_id,
            message_type,payload_ref,created_at,observation_id)
           VALUES ('final-message','final-tenant','final-app','corr','aggregate',
                   'PROCESS_DOCUMENT',%s,%s,'final-observation')""",
        ("sha256:" + "a" * 64, now),
    )
    cursor.execute(
        """INSERT INTO processing.processing_claim
           (message_id,processing_run_id,tenant_id,application_id,
            observation_sha256,status,claimed_at,lease_until,claim_generation,
            observation_id)
           VALUES ('final-message','final-run','final-tenant','final-app',%s,
                   'CLAIMED',%s,%s,%s,'final-observation')""",
        ("a" * 64, now, now + timedelta(minutes=lease_minutes), generation),
    )
    return now


def result(created_at):
    return ProcessingResult(
        "final-result", "1", "final-run", "final-document", "final-tenant",
        "final-app", "final-observation", "a" * 64, "2.0",
        ClassificationPrediction("INVOICE", 0.9, "classifier", "1", "1", ()),
        (), created_at,
    )


def test_finalization_commits_result_and_claim_together():
    with connect() as connection:
        with connection.cursor() as cursor:
            now = seed(cursor)

    PostgreSqlProcessingResultFinalizer(connect).finalize(
        message_id="final-message",
        expected_generation=1,
        result=result(now),
        completed_at=now + timedelta(seconds=1),
    )

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status FROM processing.processing_claim WHERE message_id='final-message'"
            )
            assert cursor.fetchone()[0] == "COMPLETED"
            cursor.execute(
                "SELECT count(*) FROM processing.processing_result WHERE result_id='final-result'"
            )
            assert cursor.fetchone()[0] == 1


def test_stale_generation_cannot_commit_any_result_rows():
    with connect() as connection:
        with connection.cursor() as cursor:
            now = seed(cursor, generation=2)

    with pytest.raises(ProcessingFinalizationRejected, match="CLAIM_OWNERSHIP_LOST"):
        PostgreSqlProcessingResultFinalizer(connect).finalize(
            message_id="final-message",
            expected_generation=1,
            result=result(now),
            completed_at=now + timedelta(seconds=1),
        )

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM processing.processing_result WHERE result_id='final-result'"
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT status FROM processing.processing_claim WHERE message_id='final-message'"
            )
            assert cursor.fetchone()[0] == "CLAIMED"
