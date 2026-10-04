import os

import pytest

from edi_reference.adapters.postgresql_classification_result import PostgreSqlClassificationResultRepository
from edi_reference.domain.classification import ClassificationCandidate, ClassificationPrediction

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def seed(cursor):
    cursor.execute("DELETE FROM processing.processing_result WHERE result_id='classification-result'")
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='classification-run'")
    cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='classification-observation'")
    cursor.execute("DELETE FROM ingestion.document WHERE document_id='classification-document'")
    cursor.execute("DELETE FROM control_plane.application WHERE tenant_id='classification-tenant'")
    cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id='classification-tenant'")
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('classification-tenant')")
    cursor.execute(
        """INSERT INTO control_plane.application (tenant_id, application_id)
           VALUES ('classification-tenant','classification-app')"""
    )
    cursor.execute(
        """INSERT INTO ingestion.document
           (document_id, tenant_id, application_id, created_at)
           VALUES ('classification-document','classification-tenant',
                   'classification-app',CURRENT_TIMESTAMP)"""
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id, document_id, tenant_id, application_id, sha256,
            byte_length, detected_media_type, observed_at)
           VALUES ('classification-observation','classification-document',
                   'classification-tenant','classification-app',%s,10,
                   'application/pdf',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_run
           (processing_run_id, document_id, tenant_id, application_id,
            observation_id, observation_sha256, created_at)
           VALUES ('classification-run','classification-document',
                   'classification-tenant','classification-app',
                   'classification-observation',%s,CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_result
           (result_id, result_version, processing_run_id, document_id,
            tenant_id, application_id, observation_id, observation_sha256,
            schema_version, created_at)
           VALUES ('classification-result','1','classification-run',
                   'classification-document','classification-tenant',
                   'classification-app','classification-observation',%s,
                   '2.0',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )


def prediction():
    return ClassificationPrediction(
        "INVOICE",
        0.94,
        "classifier",
        "7",
        "taxonomy-3",
        (),
        (
            ClassificationCandidate("RECEIPT", 0.04),
            ClassificationCandidate("PURCHASE_ORDER", 0.02),
        ),
    )


def test_classification_round_trips_provenance_and_ordered_alternatives():
    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlClassificationResultRepository(connect)
    repository.save("classification-result", "1", prediction())
    actual = repository.get("classification-result", "1")

    assert actual == prediction()


def test_classification_is_insert_only_per_result_version():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlClassificationResultRepository(connect)
    repository.save("classification-result", "1", prediction())
    with pytest.raises(psycopg.errors.UniqueViolation):
        repository.save("classification-result", "1", prediction())


def test_database_rejects_invalid_classification_confidence():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)
            with pytest.raises(psycopg.errors.CheckViolation):
                cursor.execute(
                    """INSERT INTO processing.classification_result
                       (result_id, result_version, document_type, confidence,
                        model_id, model_version, taxonomy_version)
                       VALUES ('classification-result','1','INVOICE',1.5,
                               'classifier','7','taxonomy-3')"""
                )
