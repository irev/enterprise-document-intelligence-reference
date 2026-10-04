import os
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.postgresql_acquisition_lineage import PostgreSqlSourceAcquisitionRepository
from edi_reference.adapters.postgresql_lineage import PostgreSqlObservationRepository, PostgreSqlProcessingRunRepository
from edi_reference.application.acquisition_lineage import record_acquisition
from edi_reference.application.retry import RetryAction, orchestrate_retry
from edi_reference.domain.acquisition_lineage import AcquisitionStatus, SourceAcquisition
from edi_reference.domain.lineage import ScopedObservation
from edi_reference.domain.source import AcquisitionMethod, ProcessingIntent

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


class Clock:
    def now(self):
        return datetime.now(UTC)


class Ids:
    values = iter(("observation-refetched", "run-refetched"))
    def new_id(self):
        return next(self.values)


def test_acquisition_and_refetch_reprocess_are_durable():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('retry-tenant') ON CONFLICT DO NOTHING")
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES ('retry-tenant','retry-app') ON CONFLICT DO NOTHING"""
            )
            cursor.execute("DELETE FROM processing.processing_run WHERE document_id='retry-document'")
            cursor.execute("DELETE FROM ingestion.source_acquisition WHERE document_id='retry-document'")
            cursor.execute("DELETE FROM ingestion.source_observation WHERE document_id='retry-document'")
            cursor.execute("DELETE FROM ingestion.source_reference WHERE document_id='retry-document'")
            cursor.execute("DELETE FROM ingestion.document WHERE document_id='retry-document'")
            cursor.execute(
                """INSERT INTO ingestion.document
                   (document_id, tenant_id, application_id, created_at)
                   VALUES ('retry-document','retry-tenant','retry-app',CURRENT_TIMESTAMP)"""
            )

    observations = PostgreSqlObservationRepository(connect)
    current = ScopedObservation(
        "observation-current", "retry-document", "retry-tenant", "retry-app",
        "d" * 64, 100, "application/pdf", datetime.now(UTC), "v1",
    )
    observations.save(current)

    acquisitions = PostgreSqlSourceAcquisitionRepository(connect)
    acquisition = SourceAcquisition(
        "acquisition-refetch", "retry-document", "retry-tenant", "retry-app",
        AcquisitionMethod.CONNECTOR, AcquisitionStatus.ACQUIRED, datetime.now(UTC),
        "observation-current",
    )
    assert record_acquisition(acquisition, repository=acquisitions) == acquisition
    assert acquisitions.get("acquisition-refetch") == acquisition

    result = orchestrate_retry(
        intent=ProcessingIntent.REFETCH_AND_REPROCESS,
        current=current, tenant_id="retry-tenant", application_id="retry-app",
        observation_repository=observations,
        processing_repository=PostgreSqlProcessingRunRepository(connect),
        clock=Clock(), ids=Ids(), reacquired_sha256="e" * 64,
        byte_length=200, detected_media_type="application/pdf", external_version="v2",
    )

    assert result.action is RetryAction.PROCESS_REFETCHED
    assert result.observation.observation_id == "observation-refetched"
    assert result.processing_run.observation_id == "observation-refetched"
    assert observations.get("observation-refetched") == result.observation
