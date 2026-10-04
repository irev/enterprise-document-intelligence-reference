import os

import pytest

from edi_reference.adapters.postgresql_execution_attempt import PostgreSqlExecutionAttemptRepository
from edi_reference.domain.execution import (
    Capability,
    ExecutionAttempt,
    ExecutionAttemptStatus,
    ExecutionClass,
)

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def seed(cursor):
    cursor.execute("DELETE FROM processing.execution_attempt WHERE processing_run_id='attempt-run'")
    cursor.execute("DELETE FROM processing.execution_plan WHERE processing_run_id='attempt-run'")
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='attempt-run'")
    cursor.execute("DELETE FROM control_plane.processing_profile_version WHERE profile_id='attempt-profile'")
    cursor.execute("DELETE FROM control_plane.execution_policy_version WHERE policy_id='attempt-policy'")
    cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='attempt-observation'")
    cursor.execute("DELETE FROM ingestion.document WHERE document_id='attempt-document'")
    cursor.execute("DELETE FROM control_plane.application WHERE tenant_id='attempt-tenant'")
    cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id='attempt-tenant'")
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('attempt-tenant')")
    cursor.execute(
        "INSERT INTO control_plane.application (tenant_id, application_id) VALUES ('attempt-tenant','attempt-app')"
    )
    cursor.execute(
        """INSERT INTO control_plane.execution_policy_version
           (policy_id, policy_version, policy_document)
           VALUES ('attempt-policy','1',
                   '{"allowed_execution_classes":["LOCAL_MODEL","REMOTE_MODEL"],
                     "allow_external_egress":true,"allow_fallback":true}'::jsonb)"""
    )
    cursor.execute(
        """INSERT INTO control_plane.processing_profile_version
           (profile_id, profile_version, policy_id, policy_version)
           VALUES ('attempt-profile','1','attempt-policy','1')"""
    )
    cursor.execute(
        """INSERT INTO ingestion.document
           (document_id, tenant_id, application_id, created_at)
           VALUES ('attempt-document','attempt-tenant','attempt-app',CURRENT_TIMESTAMP)"""
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id, document_id, tenant_id, application_id, sha256,
            byte_length, detected_media_type, observed_at)
           VALUES ('attempt-observation','attempt-document','attempt-tenant',
                   'attempt-app',%s,10,'application/pdf',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_run
           (processing_run_id, document_id, tenant_id, application_id,
            observation_id, observation_sha256, created_at)
           VALUES ('attempt-run','attempt-document','attempt-tenant','attempt-app',
                   'attempt-observation',%s,CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.execution_plan
           (processing_run_id, profile_id, profile_version, policy_id, policy_version)
           VALUES ('attempt-run','attempt-profile','1','attempt-policy','1')"""
    )


def test_execution_attempts_preserve_fallback_order_and_outcome():
    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlExecutionAttemptRepository(connect)
    repository.append(
        "attempt-run",
        0,
        ExecutionAttempt(
            "attempt-0",
            Capability.CLASSIFICATION,
            "local-model",
            "3",
            ExecutionClass.LOCAL_MODEL,
            ExecutionAttemptStatus.FAILED,
            "MODEL_UNAVAILABLE",
        ),
    )
    repository.append(
        "attempt-run",
        1,
        ExecutionAttempt(
            "attempt-1",
            Capability.CLASSIFICATION,
            "remote-model",
            "7",
            ExecutionClass.REMOTE_MODEL,
            ExecutionAttemptStatus.SUCCEEDED,
        ),
    )

    attempts = repository.list_for_run("attempt-run")
    assert [item.attempt_id for item in attempts] == ["attempt-0", "attempt-1"]
    assert attempts[0].failure_code == "MODEL_UNAVAILABLE"
    assert attempts[1].status is ExecutionAttemptStatus.SUCCEEDED


def test_attempt_history_is_append_only_per_run_ordinal():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlExecutionAttemptRepository(connect)
    item = ExecutionAttempt(
        "attempt-0",
        Capability.CLASSIFICATION,
        "local-model",
        "3",
        ExecutionClass.LOCAL_MODEL,
        ExecutionAttemptStatus.FAILED,
        "MODEL_UNAVAILABLE",
    )
    repository.append("attempt-run", 0, item)

    with pytest.raises(psycopg.errors.UniqueViolation):
        repository.append(
            "attempt-run",
            0,
            ExecutionAttempt(
                "attempt-rewrite",
                Capability.CLASSIFICATION,
                "remote-model",
                "7",
                ExecutionClass.REMOTE_MODEL,
                ExecutionAttemptStatus.SUCCEEDED,
            ),
        )
