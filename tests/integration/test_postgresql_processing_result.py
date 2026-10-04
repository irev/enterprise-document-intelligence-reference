import os
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.postgresql_processing_result import PostgreSqlProcessingResultRepository
from edi_reference.domain.classification import ClassificationPrediction
from edi_reference.domain.processing_result import ProcessingResult

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def seed(cursor):
    cursor.execute("DELETE FROM processing.processing_result WHERE result_id LIKE 'root-result-%'")
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='root-run'")
    cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='root-observation'")
    cursor.execute("DELETE FROM ingestion.document WHERE document_id='root-document'")
    cursor.execute("DELETE FROM control_plane.application WHERE tenant_id='root-tenant'")
    cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id='root-tenant'")
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('root-tenant')")
    cursor.execute(
        "INSERT INTO control_plane.application (tenant_id, application_id) VALUES ('root-tenant','root-app')"
    )
    cursor.execute(
        """INSERT INTO ingestion.document
           (document_id, tenant_id, application_id, created_at)
           VALUES ('root-document','root-tenant','root-app',CURRENT_TIMESTAMP)"""
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id, document_id, tenant_id, application_id, sha256,
            byte_length, detected_media_type, observed_at)
           VALUES ('root-observation','root-document','root-tenant','root-app',
                   %s,10,'application/pdf',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_run
           (processing_run_id, document_id, tenant_id, application_id,
            observation_id, observation_sha256, created_at)
           VALUES ('root-run','root-document','root-tenant','root-app',
                   'root-observation',%s,CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )


def result(result_id="root-result-1", digest="a" * 64):
    return ProcessingResult(
        result_id,
        "1",
        "root-run",
        "root-document",
        "root-tenant",
        "root-app",
        "root-observation",
        digest,
        "2.0",
        ClassificationPrediction("INVOICE", 0.9, "classifier", "1", "1", ()),
        (),
        datetime(2026, 10, 4, tzinfo=UTC),
    )


def test_processing_result_root_round_trips_identity_and_lineage():
    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlProcessingResultRepository(connect)
    expected = result()
    repository.save_root(expected)
    actual = repository.get_root(expected.result_id, expected.result_version)

    assert actual is not None
    assert actual.processing_run_id == expected.processing_run_id
    assert actual.observation_id == expected.observation_id
    assert actual.observation_sha256 == expected.observation_sha256
    assert actual.schema_version == expected.schema_version


def test_database_rejects_result_with_wrong_run_digest():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlProcessingResultRepository(connect)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repository.save_root(result("root-result-wrong-digest", "b" * 64))


def test_processing_result_root_is_insert_only():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlProcessingResultRepository(connect)
    repository.save_root(result())
    with pytest.raises(psycopg.errors.UniqueViolation):
        repository.save_root(result())
