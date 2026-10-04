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


def test_outbox_cannot_bind_observation_from_another_scope():
    import psycopg
    with connect() as connection:
        with connection.cursor() as cursor:
            seed_lineage(cursor)
            cursor.execute(
                """INSERT INTO ingestion.inbound_request
                   (inbound_id, tenant_id, application_id, correlation_id, request_id,
                    idempotency_key, request_fingerprint, source_method, status,
                    received_at, updated_at, observation_sha256)
                   VALUES ('integrity-inbound','integrity-a','app-b','corr','req',
                           'integrity-outbox-idem',%s,'UPLOAD','ACCEPTED',
                           CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,%s)""",
                ("c" * 64, "a" * 64),
            )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    """INSERT INTO integration.outbox_message
                       (message_id, tenant_id, application_id, correlation_id, aggregate_id,
                        message_type, payload_ref, created_at, observation_id)
                       VALUES ('integrity-message','integrity-a','app-b','corr',
                               'integrity-inbound','PROCESS_DOCUMENT',%s,
                               CURRENT_TIMESTAMP,'integrity-obs')""",
                    ("sha256:" + "a" * 64,),
                )


def test_processing_claim_cannot_bind_observation_from_another_scope():
    import psycopg
    with connect() as connection:
        with connection.cursor() as cursor:
            seed_lineage(cursor)
            cursor.execute(
                """INSERT INTO ingestion.inbound_request
                   (inbound_id, tenant_id, application_id, correlation_id, request_id,
                    idempotency_key, request_fingerprint, source_method, status,
                    received_at, updated_at, observation_sha256)
                   VALUES ('integrity-claim-inbound','integrity-a','app-a','corr','req',
                           'integrity-claim-idem',%s,'UPLOAD','ACCEPTED',
                           CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,%s)""",
                ("d" * 64, "a" * 64),
            )
            cursor.execute(
                """INSERT INTO integration.outbox_message
                   (message_id, tenant_id, application_id, correlation_id, aggregate_id,
                    message_type, payload_ref, created_at, observation_id)
                   VALUES ('integrity-claim-message','integrity-a','app-a','corr',
                           'integrity-claim-inbound','PROCESS_DOCUMENT',%s,
                           CURRENT_TIMESTAMP,'integrity-obs')""",
                ("sha256:" + "a" * 64,),
            )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    """INSERT INTO processing.processing_claim
                       (message_id, processing_run_id, tenant_id, application_id,
                        observation_sha256, status, claimed_at, lease_until,
                        claim_generation, observation_id)
                       VALUES ('integrity-claim-message','integrity-run','integrity-b',
                               'app-a',%s,'CLAIMED',CURRENT_TIMESTAMP,
                               CURRENT_TIMESTAMP,1,'integrity-obs')""",
                    ("a" * 64,),
                )


def test_processing_claim_cannot_bind_wrong_observation_digest():
    import psycopg
    with connect() as connection:
        with connection.cursor() as cursor:
            seed_lineage(cursor)
            cursor.execute(
                """INSERT INTO ingestion.inbound_request
                   (inbound_id, tenant_id, application_id, correlation_id, request_id,
                    idempotency_key, request_fingerprint, source_method, status,
                    received_at, updated_at, observation_sha256)
                   VALUES ('integrity-digest-inbound','integrity-a','app-a','corr','req',
                           'integrity-digest-idem',%s,'UPLOAD','ACCEPTED',
                           CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,%s)""",
                ("e" * 64, "a" * 64),
            )
            cursor.execute(
                """INSERT INTO integration.outbox_message
                   (message_id, tenant_id, application_id, correlation_id, aggregate_id,
                    message_type, payload_ref, created_at, observation_id)
                   VALUES ('integrity-digest-message','integrity-a','app-a','corr',
                           'integrity-digest-inbound','PROCESS_DOCUMENT',%s,
                           CURRENT_TIMESTAMP,'integrity-obs')""",
                ("sha256:" + "a" * 64,),
            )
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                cursor.execute(
                    """INSERT INTO processing.processing_claim
                       (message_id, processing_run_id, tenant_id, application_id,
                        observation_sha256, status, claimed_at, lease_until,
                        claim_generation, observation_id)
                       VALUES ('integrity-digest-message','integrity-digest-run',
                               'integrity-a','app-a',%s,'CLAIMED',CURRENT_TIMESTAMP,
                               CURRENT_TIMESTAMP,1,'integrity-obs')""",
                    ("f" * 64,),
                )
