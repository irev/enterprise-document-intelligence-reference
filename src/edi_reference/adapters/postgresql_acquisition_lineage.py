"""PostgreSQL durable source-acquisition lineage adapter."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.acquisition_lineage import AcquisitionStatus, SourceAcquisition
from edi_reference.domain.source import AcquisitionMethod


class PostgreSqlSourceAcquisitionRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    @staticmethod
    def _map(row):
        if row is None:
            return None
        return SourceAcquisition(
            acquisition_id=row[0], document_id=row[1], tenant_id=row[2],
            application_id=row[3], method=AcquisitionMethod(row[4]),
            status=AcquisitionStatus(row[5]), acquired_at=row[6],
            observation_id=row[7], failure_code=row[8],
        )

    def save(self, acquisition: SourceAcquisition) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO ingestion.source_acquisition
                       (acquisition_id, document_id, tenant_id, application_id, method,
                        status, acquired_at, observation_id, failure_code)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        acquisition.acquisition_id, acquisition.document_id,
                        acquisition.tenant_id, acquisition.application_id,
                        acquisition.method.value, acquisition.status.value,
                        acquisition.acquired_at, acquisition.observation_id,
                        acquisition.failure_code,
                    ),
                )

    def get(self, acquisition_id: str) -> SourceAcquisition | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT acquisition_id, document_id, tenant_id, application_id,
                              method, status, acquired_at, observation_id, failure_code
                       FROM ingestion.source_acquisition WHERE acquisition_id=%s""",
                    (acquisition_id,),
                )
                return self._map(cursor.fetchone())
