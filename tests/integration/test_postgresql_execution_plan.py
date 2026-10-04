import os
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.postgresql_execution_plan import PostgreSqlExecutionPlanRepository
from edi_reference.domain.execution import Capability, ExecutionClass, ExecutionPlan, PlannedStep
from edi_reference.domain.lineage import ProcessingRunBinding
from edi_reference.domain.processing_run import ProcessingRunExecutionSnapshot

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def seed(cursor):
    cursor.execute("DELETE FROM processing.execution_plan WHERE processing_run_id='plan-run'")
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='plan-run'")
    cursor.execute(
        "DELETE FROM control_plane.processing_profile_binding WHERE tenant_id='plan-tenant'"
    )
    cursor.execute(
        "DELETE FROM control_plane.processing_profile_version WHERE profile_id='plan-profile'"
    )
    cursor.execute(
        "DELETE FROM control_plane.execution_policy_version WHERE policy_id='plan-policy'"
    )
    cursor.execute(
        "DELETE FROM ingestion.source_observation WHERE observation_id='plan-observation'"
    )
    cursor.execute("DELETE FROM ingestion.document WHERE document_id='plan-document'")
    cursor.execute("DELETE FROM control_plane.application WHERE tenant_id='plan-tenant'")
    cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id='plan-tenant'")
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('plan-tenant')")
    cursor.execute(
        """INSERT INTO control_plane.application (tenant_id, application_id)
           VALUES ('plan-tenant','plan-app')"""
    )
    cursor.execute(
        """INSERT INTO control_plane.execution_policy_version
           (policy_id, policy_version, policy_document)
           VALUES ('plan-policy','4',
                   '{"allowed_execution_classes":["LOCAL_MODEL"],
                     "allow_external_egress":false}'::jsonb)"""
    )
    cursor.execute(
        """INSERT INTO control_plane.processing_profile_version
           (profile_id, profile_version, policy_id, policy_version)
           VALUES ('plan-profile','2','plan-policy','4')"""
    )
    cursor.execute(
        """INSERT INTO ingestion.document
           (document_id, tenant_id, application_id, created_at)
           VALUES ('plan-document','plan-tenant','plan-app',CURRENT_TIMESTAMP)"""
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id, document_id, tenant_id, application_id, sha256,
            byte_length, detected_media_type, observed_at)
           VALUES ('plan-observation','plan-document','plan-tenant','plan-app',%s,
                   10,'application/pdf',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_run
           (processing_run_id, document_id, tenant_id, application_id,
            observation_id, observation_sha256, created_at)
           VALUES ('plan-run','plan-document','plan-tenant','plan-app',
                   'plan-observation',%s,CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )


def snapshot():
    binding = ProcessingRunBinding(
        "plan-run",
        "plan-document",
        "plan-tenant",
        "plan-app",
        "plan-observation",
        "a" * 64,
        datetime(2026, 10, 4, tzinfo=UTC),
    )
    return ProcessingRunExecutionSnapshot(
        binding,
        "plan-profile",
        "2",
        ExecutionPlan(
            "plan-policy",
            "4",
            (
                PlannedStep(
                    Capability.CLASSIFICATION,
                    "local-model",
                    "11",
                    ExecutionClass.LOCAL_MODEL,
                    "CAPABILITY_POLICY_PREFERENCE",
                ),
                PlannedStep(
                    Capability.FIELD_EXTRACTION,
                    "local-model",
                    "11",
                    ExecutionClass.LOCAL_MODEL,
                    "CAPABILITY_POLICY_PREFERENCE",
                ),
            ),
        ),
    )


def test_execution_plan_round_trips_as_ordered_snapshot():
    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlExecutionPlanRepository(connect)
    expected = snapshot()
    repository.save(expected)
    actual = repository.get("plan-run", binding=expected.binding)

    assert actual == expected


def test_execution_plan_is_insert_only_for_processing_run():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository = PostgreSqlExecutionPlanRepository(connect)
    repository.save(snapshot())

    with pytest.raises(psycopg.errors.UniqueViolation):
        repository.save(snapshot())
