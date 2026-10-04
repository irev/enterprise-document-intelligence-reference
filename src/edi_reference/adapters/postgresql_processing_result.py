"""PostgreSQL persistence for immutable processing-result roots."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from edi_reference.domain.processing_result import ProcessingResult


@dataclass(frozen=True, slots=True)
class ProcessingResultRoot:
    result_id: str
    result_version: str
    processing_run_id: str
    document_id: str
    tenant_id: str
    application_id: str
    observation_id: str
    observation_sha256: str
    schema_version: str
    created_at: datetime


class PostgreSqlProcessingResultRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def save_root(self, result: ProcessingResult) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing.processing_result
                       (result_id, result_version, processing_run_id, document_id,
                        tenant_id, application_id, observation_id,
                        observation_sha256, schema_version, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        result.result_id,
                        result.result_version,
                        result.processing_run_id,
                        result.document_id,
                        result.tenant_id,
                        result.application_id,
                        result.observation_id,
                        result.observation_sha256,
                        result.schema_version,
                        result.created_at,
                    ),
                )

    def get_root(
        self, result_id: str, result_version: str
    ) -> ProcessingResultRoot | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT result_id, result_version, processing_run_id,
                              document_id, tenant_id, application_id, observation_id,
                              observation_sha256, schema_version, created_at
                       FROM processing.processing_result
                       WHERE result_id=%s AND result_version=%s""",
                    (result_id, result_version),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return ProcessingResultRoot(*row)
