"""PostgreSQL source-observation and processing-run lineage adapters."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.lineage import ProcessingRunBinding, ScopedObservation


class PostgreSqlObservationRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    @staticmethod
    def _map(row):
        if row is None:
            return None
        return ScopedObservation(
            observation_id=row[0], document_id=row[1], tenant_id=row[2],
            application_id=row[3], sha256=row[4], byte_length=row[5],
            detected_media_type=row[6], observed_at=row[7], external_version=row[8],
        )

    def get(self, observation_id: str) -> ScopedObservation | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT observation_id, document_id, tenant_id, application_id, sha256,
                              byte_length, detected_media_type, observed_at, external_version
                       FROM ingestion.source_observation WHERE observation_id=%s""",
                    (observation_id,),
                )
                return self._map(cursor.fetchone())

    def save(self, observation: ScopedObservation) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO ingestion.source_observation
                       (observation_id, document_id, tenant_id, application_id, sha256,
                        byte_length, detected_media_type, observed_at, external_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        observation.observation_id, observation.document_id,
                        observation.tenant_id, observation.application_id,
                        observation.sha256, observation.byte_length,
                        observation.detected_media_type, observation.observed_at,
                        observation.external_version,
                    ),
                )

    def find_by_scope_document_digest(
        self, tenant_id: str, application_id: str, document_id: str, sha256: str
    ) -> ScopedObservation | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT observation_id, document_id, tenant_id, application_id, sha256,
                              byte_length, detected_media_type, observed_at, external_version
                       FROM ingestion.source_observation
                       WHERE tenant_id=%s AND application_id=%s
                         AND document_id=%s AND sha256=%s""",
                    (tenant_id, application_id, document_id, sha256.lower()),
                )
                return self._map(cursor.fetchone())


class PostgreSqlProcessingRunRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def save(self, binding: ProcessingRunBinding) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing.processing_run
                       (processing_run_id, document_id, tenant_id, application_id,
                        observation_id, observation_sha256, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        binding.processing_run_id, binding.document_id, binding.tenant_id,
                        binding.application_id, binding.observation_id,
                        binding.observation_sha256, binding.created_at,
                    ),
                )
