"""PostgreSQL persistence for append-only execution attempt history."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.execution import (
    Capability,
    ExecutionAttempt,
    ExecutionAttemptStatus,
    ExecutionClass,
)


class PostgreSqlExecutionAttemptRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def append(
        self,
        processing_run_id: str,
        attempt_ordinal: int,
        attempt: ExecutionAttempt,
    ) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing.execution_attempt
                       (attempt_id, processing_run_id, attempt_ordinal, capability,
                        provider_id, provider_version, execution_class, status,
                        failure_code)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        attempt.attempt_id,
                        processing_run_id,
                        attempt_ordinal,
                        attempt.capability.value,
                        attempt.provider_id,
                        attempt.provider_version,
                        attempt.execution_class.value,
                        attempt.status.value,
                        attempt.failure_code,
                    ),
                )

    def list_for_run(self, processing_run_id: str) -> tuple[ExecutionAttempt, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT attempt_id, capability, provider_id, provider_version,
                              execution_class, status, failure_code
                       FROM processing.execution_attempt
                       WHERE processing_run_id=%s
                       ORDER BY attempt_ordinal""",
                    (processing_run_id,),
                )
                return tuple(
                    ExecutionAttempt(
                        attempt_id=row[0],
                        capability=Capability(row[1]),
                        provider_id=row[2],
                        provider_version=row[3],
                        execution_class=ExecutionClass(row[4]),
                        status=ExecutionAttemptStatus(row[5]),
                        failure_code=row[6],
                    )
                    for row in cursor.fetchall()
                )
