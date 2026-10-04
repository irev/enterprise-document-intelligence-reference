import os

import pytest

from edi_reference.adapters.postgresql_evidence import PostgreSqlEvidenceRepository
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg

    return psycopg.connect(DSN)


def seed(cursor):
    cursor.execute("DELETE FROM processing.processing_result WHERE result_id='evidence-result'")
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='evidence-run'")
    cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='evidence-observation'")
    cursor.execute("DELETE FROM ingestion.document WHERE document_id='evidence-document'")
    cursor.execute("DELETE FROM control_plane.application WHERE tenant_id='evidence-tenant'")
    cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id='evidence-tenant'")
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('evidence-tenant')")
    cursor.execute(
        """INSERT INTO control_plane.application (tenant_id,application_id)
           VALUES ('evidence-tenant','evidence-app')"""
    )
    cursor.execute(
        """INSERT INTO ingestion.document
           (document_id,tenant_id,application_id,created_at)
           VALUES ('evidence-document','evidence-tenant','evidence-app',CURRENT_TIMESTAMP)"""
    )
    cursor.execute(
        """INSERT INTO ingestion.source_observation
           (observation_id,document_id,tenant_id,application_id,sha256,
            byte_length,detected_media_type,observed_at)
           VALUES ('evidence-observation','evidence-document','evidence-tenant',
                   'evidence-app',%s,10,'application/pdf',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_run
           (processing_run_id,document_id,tenant_id,application_id,
            observation_id,observation_sha256,created_at)
           VALUES ('evidence-run','evidence-document','evidence-tenant',
                   'evidence-app','evidence-observation',%s,CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.processing_result
           (result_id,result_version,processing_run_id,document_id,tenant_id,
            application_id,observation_id,observation_sha256,schema_version,created_at)
           VALUES ('evidence-result','1','evidence-run','evidence-document',
                   'evidence-tenant','evidence-app','evidence-observation',%s,
                   '2.0',CURRENT_TIMESTAMP)""",
        ("a" * 64,),
    )
    cursor.execute(
        """INSERT INTO processing.classification_result
           (result_id,result_version,document_type,confidence,model_id,
            model_version,taxonomy_version)
           VALUES ('evidence-result','1','INVOICE',0.9,'classifier','1','1')"""
    )
    cursor.execute(
        """INSERT INTO processing.extracted_field
           (result_id,result_version,field_ordinal,field_name,state,raw_value,
            value_type,confidence,extractor_id,extractor_version,schema_version)
           VALUES ('evidence-result','1',0,'invoice_number','PRESENT','INV-1',
                   'string',0.95,'extractor','1','2.0')"""
    )


def references():
    block = EvidenceReference(
        "evidence-observation", "a" * 64, 1, EvidenceKind.TEXT_BLOCK,
        block_id="block-1", text_quote="INV-1",
    )
    region = EvidenceReference(
        "evidence-observation", "a" * 64, 1, EvidenceKind.REGION,
        bbox=BoundingBox(0.1, 0.2, 0.3, 0.4),
    )
    return block, region


def test_evidence_round_trips_and_is_shared_by_claim_links():
    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    block, region = references()
    repository = PostgreSqlEvidenceRepository(connect)
    repository.save_result_evidence(
        "evidence-result", "1", (block,), ((block, region),)
    )

    assert repository.list_classification("evidence-result", "1") == (block,)
    assert repository.list_field("evidence-result", "1", 0) == (block, region)


def test_database_rejects_evidence_from_different_observation_digest():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    invalid = EvidenceReference(
        "evidence-observation", "b" * 64, 1, EvidenceKind.TEXT_BLOCK,
        block_id="block-1",
    )
    repository = PostgreSqlEvidenceRepository(connect)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        repository.save_result_evidence("evidence-result", "1", (invalid,), ((),))
