import os
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.postgresql_validation import PostgreSqlValidationRepository
from edi_reference.domain.validation import (
    FindingSeverity,
    ValidationFinding,
    ValidationResult,
    ValidationStatus,
)

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg

    return psycopg.connect(DSN)


def test_validation_findings_round_trip_for_existing_result():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT result_id,result_version
                   FROM processing.processing_result
                   WHERE result_id='final-result' AND result_version='1'"""
            )
            parent = cursor.fetchone()
            assert parent == ("final-result", "1")
            result_id, result_version = parent
            cursor.execute(
                """DELETE FROM processing.validation_result
                   WHERE result_id=%s AND result_version=%s
                     AND validation_version='integration-1'""",
                (result_id, result_version),
            )

    expected = ValidationResult(
        result_id,
        result_version,
        "integration-1",
        ValidationStatus.REVIEW_REQUIRED,
        (
            ValidationFinding(
                "AMOUNT_REVIEW",
                FindingSeverity.WARNING,
                "RULE_ENGINE",
                "1.0",
                "Amount requires review.",
                ("document-a",),
            ),
        ),
    )
    repository = PostgreSqlValidationRepository(connect)
    repository.save(expected, created_at=datetime.now(UTC))
    assert repository.get(result_id, result_version, "integration-1") == expected
