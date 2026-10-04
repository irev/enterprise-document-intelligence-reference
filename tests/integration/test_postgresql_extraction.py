import os
import pytest

from edi_reference.adapters.postgresql_extraction import PostgreSqlExtractedFieldRepository
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference
from edi_reference.domain.extraction import ExtractedField, FieldState
from edi_reference.domain.normalization import NormalizedField, NormalizedValue

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def seed(cursor):
    cursor.execute("DELETE FROM processing.processing_result WHERE result_id='field-result'")
    cursor.execute("DELETE FROM processing.processing_run WHERE processing_run_id='field-run'")
    cursor.execute("DELETE FROM ingestion.source_observation WHERE observation_id='field-observation'")
    cursor.execute("DELETE FROM ingestion.document WHERE document_id='field-document'")
    cursor.execute("DELETE FROM control_plane.application WHERE tenant_id='field-tenant'")
    cursor.execute("DELETE FROM control_plane.tenant WHERE tenant_id='field-tenant'")
    cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('field-tenant')")
    cursor.execute("INSERT INTO control_plane.application (tenant_id,application_id) VALUES ('field-tenant','field-app')")
    cursor.execute("""INSERT INTO ingestion.document
        (document_id,tenant_id,application_id,created_at)
        VALUES ('field-document','field-tenant','field-app',CURRENT_TIMESTAMP)""")
    cursor.execute("""INSERT INTO ingestion.source_observation
        (observation_id,document_id,tenant_id,application_id,sha256,
         byte_length,detected_media_type,observed_at)
        VALUES ('field-observation','field-document','field-tenant','field-app',
                %s,10,'application/pdf',CURRENT_TIMESTAMP)""", ("a"*64,))
    cursor.execute("""INSERT INTO processing.processing_run
        (processing_run_id,document_id,tenant_id,application_id,
         observation_id,observation_sha256,created_at)
        VALUES ('field-run','field-document','field-tenant','field-app',
                'field-observation',%s,CURRENT_TIMESTAMP)""", ("a"*64,))
    cursor.execute("""INSERT INTO processing.processing_result
        (result_id,result_version,processing_run_id,document_id,tenant_id,
         application_id,observation_id,observation_sha256,schema_version,created_at)
        VALUES ('field-result','1','field-run','field-document','field-tenant',
                'field-app','field-observation',%s,'2.0',CURRENT_TIMESTAMP)""", ("a"*64,))


def fields():
    evidence=(EvidenceReference("field-observation","a"*64,1,EvidenceKind.TEXT_BLOCK,block_id="b1"),)
    return (
        NormalizedField(
            ExtractedField("total_amount",FieldState.PRESENT,"Rp 1.250.000,00","money",
                           .98,evidence,"extractor","3","2.0"),
            NormalizedValue({"amount":"1250000.00","currency":"IDR"},"money",
                            "money.id-ID.IDR","1"),
        ),
        NormalizedField(
            ExtractedField("purchase_order",FieldState.MISSING,None,"string",
                           None,(),"extractor","3","2.0"),
            None,
        ),
    )


def test_fields_preserve_raw_state_provenance_and_typed_normalized_json():
    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository=PostgreSqlExtractedFieldRepository(connect)
    repository.save("field-result","1",fields())
    records=repository.list_records("field-result","1")

    assert [item.field_name for item in records] == ["total_amount","purchase_order"]
    assert records[0].raw_value == "Rp 1.250.000,00"
    assert records[0].normalized_value == {"amount":"1250000.00","currency":"IDR"}
    assert records[0].normalizer_id == "money.id-ID.IDR"
    assert records[1].state == "MISSING"
    assert records[1].normalized_value is None


def test_duplicate_field_name_is_rejected_per_result_version():
    import psycopg

    with connect() as connection:
        with connection.cursor() as cursor:
            seed(cursor)

    repository=PostgreSqlExtractedFieldRepository(connect)
    duplicate=(fields()[0],fields()[0])
    with pytest.raises(psycopg.errors.UniqueViolation):
        repository.save("field-result","1",duplicate)
