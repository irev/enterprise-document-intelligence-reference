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


def seed(cursor):
    cursor.execute(
        "DELETE FROM processing.validation_result WHERE result_id='validation-result'"
    )
    cursor.execute(
        "DELETE FROM processing.processing_result WHERE result_id='validation-result'"
    )
    cursor.execute(
        "DELETE FROM processing.processing_run WHERE processing_run_id='validation-run'"
    )
    cursor.execute(
        "DELETE FROM ingestion.source_observation WHERE observation_id='validation-observation'"
    )
    cursor.execute(
        "DELETE FROM ingestion.document WHERE document_id='validation-document'"
    )
    cursor.execute(
        "DELETE FROM control_plane.application WHERE tenant_id='validation-tenant'"
    )
    cursor.execute(
        "DELETE FROM control_plane.tenant WHERE tenant_id='validation-tenant'"
    )
    cursor.execute(
        "INSERT INTO control_plane.tenant (tenant_id) VALUES ('validation-tenant')"
    )
    cursor.execute(
        """INSERT INTO control_plane.application (tenant_id,application_id)
           VALUES ('validation-tenant','validation-app')"""
    )
    cursor.execute(
        """INSERT INTO ingestion.document
           (document_id,tenant_id,application_id,created_at)
           VALUES ('validation-document','validation-tenant','validation-app',
                   CURRENT_TIMESTAMP)"""
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id,document_id,tenant_id,application_id,sha256,
            byte_length,detected_media_type,observed_at)
           VALUES ('validation-observation','validation-document',
                   'validation-tenant','validation-app',%s,10,
                   'application/pdf',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_run
           (processing_run_id,document_id,tenant_id,application_id,
            observation_id,observation_sha256,created_at)
           VALUES ('validation-run','validation-document','validation-tenant',
                   'validation-app','validation-observation',%s,CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_result
           (result_id,result_version,processing_run_id,document_id,tenant_id,
            application_id,observation_id,observation_sha256,schema_version,created_at)
           VALUES ('validation-result','1','validation-run','validation-document',
                   'validation-tenant','validation-app','validation-observation',
                   %s,'2.0',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )


def test_validation_findings_round_trip_for_existing_result():
    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    expected = ValidationResult(
        "validation-result",
        "1",
        "integration-1",
        ValidationStatus.REVIEW_REQUIRED,
        (
            ValidationFinding(
                "AMOUNT_REVIEW",
                FindingSeverity.WARNING,
                "RULE_ENGINE",
                "1.0",
                "Amount requires review.",
                ("validation-document",),
            ),
        ),
    )
    repository = PostgreSqlValidationRepository(connect)
    repository.save(expected, created_at=datetime.now(UTC))
    assert repository.get("validation-result", "1", "integration-1") == expected
