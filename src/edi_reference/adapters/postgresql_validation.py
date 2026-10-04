"""PostgreSQL persistence for versioned validation results."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from edi_reference.domain.validation import (
    FindingSeverity,
    ValidationFinding,
    ValidationResult,
    ValidationStatus,
)


class PostgreSqlValidationRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def save(self, validation: ValidationResult, *, created_at: datetime) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing.validation_result
                       (result_id,result_version,validation_version,status,created_at)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (
                        validation.result_id,
                        validation.result_version,
                        validation.validation_version,
                        validation.status.value,
                        created_at,
                    ),
                )
                for ordinal, finding in enumerate(validation.findings):
                    cursor.execute(
                        """INSERT INTO processing.validation_finding
                           (result_id,result_version,validation_version,finding_ordinal,
                            code,severity,source,rule_version,message,documents)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            validation.result_id,
                            validation.result_version,
                            validation.validation_version,
                            ordinal,
                            finding.code,
                            finding.severity.value,
                            finding.source,
                            finding.rule_version,
                            finding.message,
                            json.dumps(finding.documents, separators=(",", ":")),
                        ),
                    )

    def get(
        self, result_id: str, result_version: str, validation_version: str
    ) -> ValidationResult | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT status FROM processing.validation_result
                       WHERE result_id=%s AND result_version=%s
                         AND validation_version=%s""",
                    (result_id, result_version, validation_version),
                )
                root = cursor.fetchone()
                if root is None:
                    return None
                cursor.execute(
                    """SELECT code,severity,source,rule_version,message,documents
                       FROM processing.validation_finding
                       WHERE result_id=%s AND result_version=%s
                         AND validation_version=%s
                       ORDER BY finding_ordinal""",
                    (result_id, result_version, validation_version),
                )
                findings = tuple(
                    ValidationFinding(
                        code=row[0],
                        severity=FindingSeverity(row[1]),
                        source=row[2],
                        rule_version=row[3],
                        message=row[4],
                        documents=tuple(row[5]),
                    )
                    for row in cursor.fetchall()
                )
        return ValidationResult(
            result_id,
            result_version,
            validation_version,
            ValidationStatus(root[0]),
            findings,
        )
