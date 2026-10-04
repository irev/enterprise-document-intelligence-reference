import os

import pytest

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def seed_lineage(cursor):
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('integrity-a'),('integrity-b') ON CONFLICT DO NOTHING")
    cursor.execute(
        """INSERT INTO control_plane.application (tenant_id, application_id)
           VALUES ('integrity-a','app-a'),('integrity-a','app-b'),('integrity-b','app-a')
           ON CONFLICT DO NOTHING"""
    )
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id LIKE 'integrity-%'")
    cursor.execute("DELETE FROM ingestion.source_acquisition WHERE acquisition_id LIKE 'integrity-%'")
    cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id LIKE 'integrity-%'")
    cursor.execute("DELETE FROM ingestion.document WHERE document_id LIKE 'integrity-%'")
    cursor.execute(
        """INSERT INTO ingestion.document (document_id, tenant_id, application_id, created_at)
           VALUES ('integrity-doc','integrity-a','app-a',CURRENT_TIMESTAMP),
                  ('integrity-doc-other','integrity-a','app-b',CURRENT_TIMESTAMP)"""
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id, document_id, tenant_id, application_id, sha256,
            byte_length, detected_media_type, observed_at)
           VALUES ('integrity-obs','integrity-doc','integrity-a','app-a',%s,10,
                   'application/pdf',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )


def test_observation_cannot_reference_document_in_another_tenant():
    import psycopg
    with connect() as connection:
        with connection.cursor() as cursor:
            seed_lineage(cursor)
            cursor.execute(
                """INSERT INTO ingestion.document (document_id, tenant_id, application_id, created_at)
                   VALUES ('integrity-cross-tenant-doc','integrity-b','app-a',CURRENT_TIMESTAMP)"""
            )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    """INSERT INTO ingestion.source_observation
                       (observation_id, document_id, tenant_id, application_id, sha256,
                        byte_length, detected_media_type, observed_at)
                       VALUES ('integrity-bad-tenant','integrity-cross-tenant-doc',
                               'integrity-a','app-a',%s,10,'application/pdf',CURRENT_TIMESTAMP)""",
                    ("b" * 64,),
                )


def test_observation_cannot_reference_document_in_another_application():
    import psycopg
    with connect() as connection:
        with connection.cursor() as cursor:
            seed_lineage(cursor)
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    """INSERT INTO ingestion.source_observation
                       (observation_id, document_id, tenant_id, application_id, sha256,
                        byte_length, detected_media_type, observed_at)
                       VALUES ('integrity-bad-app','integrity-doc-other',
                               'integrity-a','app-a',%s,10,'application/pdf',CURRENT_TIMESTAMP)""",
                    ("b" * 64,),
                )


def test_processing_run_cannot_bind_wrong_document_or_digest():
    import psycopg
    with connect() as connection:
        with connection.cursor() as cursor:
            seed_lineage(cursor)
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    """INSERT INTO processing.processing_run
                       (processing_run_id, document_id, tenant_id, application_id,
                        observation_id, observation_sha256, created_at)
                       VALUES ('integrity-run-wrong-document','integrity-doc-other',
                               'integrity-a','app-b','integrity-obs',%s,CURRENT_TIMESTAMP)""",
                    ("a" * 64,),
                )
    with connect() as connection:
        with connection.cursor() as cursor:
            seed_lineage(cursor)
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    """INSERT INTO processing.processing_run
                       (processing_run_id, document_id, tenant_id, application_id,
                        observation_id, observation_sha256, created_at)
                       VALUES ('integrity-run-wrong-digest','integrity-doc',
                               'integrity-a','app-a','integrity-obs',%s,CURRENT_TIMESTAMP)""",
                    ("f" * 64,),
                )
