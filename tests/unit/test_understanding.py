import pytest

from edi_reference.adapters.understanding_fake import SyntheticParser
from edi_reference.application.understanding import ParserError, understand_document
from edi_reference.domain.lineage import SourceObservation
from edi_reference.domain.understanding import UnderstandingFailureCode, UnderstandingPolicy


POLICY = UnderstandingPolicy(
    max_pages=2,
    parser_timeout_seconds=10,
    ocr_timeout_seconds=20,
    max_extracted_characters=1000,
)


def observation():
    from datetime import UTC, datetime
    return SourceObservation(
        observation_id="obs-1", document_id="doc-1", tenant_id="tenant-a",
        application_id="app-a", sha256="a" * 64, byte_length=10,
        detected_media_type="application/pdf", observed_at=datetime(2026, 10, 4, tzinfo=UTC),
    )


def test_result_is_bound_to_exact_observation_and_parser_version():
    result = understand_document(observation(), b"%PDF-synthetic", parser=SyntheticParser(), policy=POLICY)
    assert result.observation_id == "obs-1"
    assert result.observation_sha256 == "a" * 64
    assert result.parser_component == "synthetic-parser"
    assert result.parser_version == "1.0"


def test_page_limit_is_enforced_after_adapter():
    with pytest.raises(ParserError, match="PAGE_LIMIT_EXCEEDED"):
        understand_document(observation(), b"%PDF-synthetic", parser=SyntheticParser(pages=3), policy=POLICY)


def test_encrypted_document_failure_is_stable_and_provider_neutral():
    with pytest.raises(ParserError, match="ENCRYPTED_DOCUMENT_UNSUPPORTED"):
        understand_document(
            observation(), b"%PDF-synthetic",
            parser=SyntheticParser(fail_with=UnderstandingFailureCode.ENCRYPTED_DOCUMENT_UNSUPPORTED),
            policy=POLICY,
        )


def test_provider_exception_is_sanitized():
    class UnsafeParser:
        component = "unsafe"
        version = "1"
        def parse(self, content, *, policy):
            raise RuntimeError("secret internal parser path /srv/private")

    with pytest.raises(ParserError) as caught:
        understand_document(observation(), b"%PDF-synthetic", parser=UnsafeParser(), policy=POLICY)
    assert caught.value.code is UnderstandingFailureCode.PARSER_FAILED
    assert "/srv/private" not in str(caught.value)
