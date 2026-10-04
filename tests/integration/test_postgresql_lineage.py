import os
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.postgresql_lineage import (
    PostgreSqlObservationRepository,
    PostgreSqlProcessingRunRepository,
)
from edi_reference.application.lineage import bind_processing_run
from edi_reference.domain.lineage import ScopedObservation

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


class Clock:
    def now(self):
        return datetime.now(UTC)


class Ids:
    def new_id(self):
        return "run-lineage"


def test_processing_run_is_bound_to_scoped_observation_not_digest_alone():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('lineage-tenant') ON CONFLICT DO NOTHING")
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES ('lineage-tenant','lineage-app') ON CONFLICT DO NOTHING"""
            )
            cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='run-lineage'")
            cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='observation-lineage'")
            cursor.execute("DELETE FROM ingestion.document WHERE document_id='document-lineage'")
            cursor.execute(
                """INSERT INTO ingestion.document
                   (document_id, tenant_id, application_id, created_at)
                   VALUES ('document-lineage','lineage-tenant','lineage-app',CURRENT_TIMESTAMP)"""
            )

    observation = ScopedObservation(
        "observation-lineage", "document-lineage", "lineage-tenant", "lineage-app",
        "c" * 64, 1234, "application/pdf", datetime.now(UTC), "source-v1",
    )
    observations = PostgreSqlObservationRepository(connect)
    observations.save(observation)

    found = observations.find_by_scope_document_digest(
        "lineage-tenant", "lineage-app", "document-lineage", "c" * 64
    )
    assert found == observation

    runs = PostgreSqlProcessingRunRepository(connect)
    binding = bind_processing_run(
        found, tenant_id="lineage-tenant", application_id="lineage-app",
        repository=runs, clock=Clock(), ids=Ids(),
    )
    assert binding.observation_id == "observation-lineage"

    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT observation_id, observation_sha256
                   FROM processing.processing_run WHERE processing_run_id='run-lineage'"""
            )
            assert cursor.fetchone() == ("observation-lineage", "c" * 64)
