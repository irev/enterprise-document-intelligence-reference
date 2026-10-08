import io
import json
from pathlib import Path

import pytest

from edi_reference.adapters.openai_compatible import OpenAICompatibleInvoker
from edi_reference.application.classification import ClassificationPolicy, classify_document
from edi_reference.application.extraction import extract_fields
from edi_reference.application.invocation import ProviderInvocationError
from edi_reference.application.llm_extraction import LlmFieldExtractor
from edi_reference.application.title_rules import (
    TitleRule,
    TitleRuleClassifier,
    TitleRuleProfile,
    load_title_rule_profile,
)
from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE
from edi_reference.domain.document_structure import BoundingBox, PageStructure, StructuredDocument, TextBlock
from edi_reference.domain.execution import (
    Capability,
    DataEgress,
    ExecutionClass,
    ExecutionPolicy,
    ProviderCapability,
)
from edi_reference.domain.extraction import FieldState
from edi_reference.domain.field_schema import ExtractionSchema, FieldDefinition
from edi_reference.domain.invocation import InvocationFailureCode, InvocationLimits, InvocationResult
from edi_reference.domain.taxonomy import DocumentTaxonomy

ROOT = Path(__file__).resolve().parents[2]
PROFILE = load_title_rule_profile(ROOT / "deploy" / "classification-profiles" / "title-rules-id-en.json")
TAXONOMY = DocumentTaxonomy(
    "business-documents", PROFILE.taxonomy_version, frozenset(rule.document_type for rule in PROFILE.rules))
POLICY = ClassificationPolicy(accept_threshold=0.9, minimum_margin=0.0)
BOX = BoundingBox(0.0, 0.0, 1.0, 1.0)


def document(*lines: str) -> StructuredDocument:
    blocks = tuple(TextBlock(f"b{n}", text, BOX, n) for n, text in enumerate(lines))
    return StructuredDocument("obs-1", "a" * 64, (PageStructure(1, 1.0, 1.0, blocks, ()),), "ocr", "1")


def classify(doc: StructuredDocument):
    return classify_document(doc, classifier=TitleRuleClassifier(PROFILE), policy=POLICY, taxonomy=TAXONOMY)


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (("Faktur Pajak", "Kode dan Nomor Seri"), "TAX_INVOICE"),
        (("SURAT PESANAN", "Kontrak"), "ORDER_LETTER"),
        (("Surat Permintaan Pembayaran",), "PAYMENT_REQUEST"),
        (("BERITA ACARA SERAH TERIMA",), "HANDOVER_REPORT"),  # taxonomy v2: was ACCEPTANCE_REPORT
        (("KWITANSI",), "RECEIPT"),
        (("Purchase Order",), "PURCHASE_ORDER"),
        (("SURAT PERJANJIAN",), "CONTRACT"),
        (("Receipt", "Paid"), "RECEIPT"),
        (("Invoice", "Invoice number SYN-0001"), "INVOICE"),
    ],
)
def test_first_matching_heading_rule_wins(heading, expected):
    assert classify(document(*heading)).document_type == expected


def test_heading_split_across_blocks_cites_every_spanned_block():
    result = classify(document("FAKTUR", "PAJAK", "Nomor 000"))

    assert result.document_type == "TAX_INVOICE"
    assert [item.block_id for item in result.evidence] == ["b0", "b1"]
    assert all(item.text_quote for item in result.evidence)
    assert result.model_id == "title-rules/title-rules-id-en"


def test_no_heading_match_abstains_to_unknown():
    result = classify(document("API Specification", "Endpoint list"))

    assert result.document_type == UNKNOWN_DOCUMENT_TYPE
    assert result.evidence == ()


def test_keyword_outside_heading_window_is_ignored():
    lines = ["Technical notes"] * PROFILE.heading_blocks + ["Invoice"]

    assert classify(document(*lines)).document_type == UNKNOWN_DOCUMENT_TYPE


def test_rule_cannot_emit_reserved_unknown_or_bad_pattern():
    with pytest.raises(ValueError, match="INVALID_TITLE_RULE_DOCUMENT_TYPE"):
        TitleRule("x", UNKNOWN_DOCUMENT_TYPE)
    with pytest.raises(ValueError, match="INVALID_TITLE_RULE_PATTERN"):
        TitleRule("(", "INVOICE")
    with pytest.raises(ValueError, match="INVALID_TITLE_RULE_COUNT"):
        TitleRuleProfile("p", "1", "t", ())


SCHEMA = ExtractionSchema(
    "business-document-header",
    "1",
    (FieldDefinition("document_number", "string"), FieldDefinition("total_amount", "money"),
     FieldDefinition("tax_id", "string")),
)
PROVIDER = ProviderCapability(
    "local-openai-compatible", "synthetic-model", ExecutionClass.LOCAL_MODEL,
    frozenset({Capability.FIELD_EXTRACTION}), DataEgress.NONE,
)
EXEC_POLICY = ExecutionPolicy("local-only", "1", frozenset({ExecutionClass.LOCAL_MODEL}), allow_external_egress=False)
LIMITS = InvocationLimits(timeout_seconds=30, max_input_bytes=100_000, max_output_bytes=10_000)
DOC = document("Invoice", "Invoice number SYN-0001", "Total   Rp 1.250.000,00")


class Invoker:
    def __init__(self, fields):
        self.fields = fields
        self.requests = []

    def invoke(self, request, limits):
        self.requests.append(request)
        return InvocationResult(PROVIDER.provider_id, PROVIDER.provider_version,
                                json.dumps({"fields": self.fields}).encode())


def extractor(invoker, policy=EXEC_POLICY):
    return LlmFieldExtractor(schema=SCHEMA, provider=PROVIDER, policy=policy, limits=LIMITS,
                             invoker=invoker, attempt_id=lambda: "attempt-1")


def test_grounded_values_are_present_with_source_evidence():
    invoker = Invoker({"document_number": "SYN-0001", "total_amount": "Rp 1.250.000,00", "tax_id": None})

    fields = {f.field_name: f for f in extract_fields(DOC, document_type="INVOICE",
                                                       extractor=extractor(invoker), schema=SCHEMA)}

    assert fields["document_number"].state is FieldState.PRESENT
    assert fields["document_number"].evidence[0].block_id == "b1"
    # whitespace-tolerant match quotes the exact source span, not the model's text
    assert fields["total_amount"].raw_value == "Rp 1.250.000,00"
    assert fields["total_amount"].evidence[0].text_quote == "Rp 1.250.000,00"
    assert fields["tax_id"].state is FieldState.MISSING
    assert json.loads(invoker.requests[0].input_bytes)["lines"][1] == "Invoice number SYN-0001"


def test_ungrounded_or_non_string_model_values_are_dropped_to_missing():
    invoker = Invoker({"document_number": "SYN-9999", "total_amount": 1250000, "tax_id": "  "})

    fields = extract_fields(DOC, document_type="INVOICE", extractor=extractor(invoker), schema=SCHEMA)

    assert all(f.state is FieldState.MISSING and f.raw_value is None and not f.evidence for f in fields)


def test_malformed_provider_output_fails_with_stable_code():
    class Bad(Invoker):
        def invoke(self, request, limits):
            return InvocationResult(PROVIDER.provider_id, PROVIDER.provider_version, b"not json")

    with pytest.raises(ProviderInvocationError) as failure:
        extractor(Bad({})).extract(DOC, "INVOICE")
    assert failure.value.code is InvocationFailureCode.INVALID_PROVIDER_RESPONSE


def test_policy_without_local_model_blocks_invocation():
    policy = ExecutionPolicy("ocr-only", "1", frozenset({ExecutionClass.OCR}), allow_external_egress=False)
    invoker = Invoker({})

    with pytest.raises(ProviderInvocationError) as failure:
        extractor(invoker, policy).extract(DOC, "INVOICE")
    assert failure.value.code is InvocationFailureCode.EGRESS_NOT_ALLOWED
    assert invoker.requests == []


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._body = io.BytesIO(json.dumps(payload).encode())

    def read(self, size):
        return self._body.read(size)


class FakeConnection:
    sent: dict = {}

    def __init__(self, host, port, timeout):
        FakeConnection.sent = {"host": host, "port": port, "timeout": timeout}
        self.response = FakeResponse(200, {"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps({"document_number": "SYN-0001", "total_amount": None, "tax_id": None})}}]})

    def request(self, method, path, body, headers):
        FakeConnection.sent.update(method=method, path=path, body=json.loads(body), headers=headers)

    def getresponse(self):
        return self.response

    def close(self):
        pass


def test_openai_compatible_invoker_disables_reasoning_and_reads_key_from_env(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_LLM_KEY", "synthetic-secret")
    invoker = OpenAICompatibleInvoker(provider_id=PROVIDER.provider_id, model=PROVIDER.provider_version,
                                      port=12340, api_key_env="SYNTHETIC_LLM_KEY",
                                      connection_factory=FakeConnection)

    fields = extract_fields(DOC, document_type="INVOICE", extractor=extractor(invoker), schema=SCHEMA)

    sent = FakeConnection.sent
    assert (sent["host"], sent["port"], sent["timeout"]) == ("127.0.0.1", 12340, 30)
    assert sent["body"]["reasoning_effort"] == "none"
    assert sent["body"]["temperature"] == 0
    assert sent["body"]["response_format"]["json_schema"]["schema"]["required"] == [
        "document_number", "total_amount", "tax_id"]
    assert sent["headers"]["Authorization"] == "Bearer synthetic-secret"
    assert "synthetic-secret" not in json.dumps(sent["body"])
    assert fields[0].state is FieldState.PRESENT


def test_openai_compatible_invoker_rejects_non_loopback_and_missing_key(monkeypatch):
    with pytest.raises(ValueError, match="ENDPOINT_MUST_BE_LOOPBACK"):
        OpenAICompatibleInvoker(provider_id="p", model="m", host="10.0.0.5", port=1)
    monkeypatch.delenv("SYNTHETIC_LLM_KEY", raising=False)
    invoker = OpenAICompatibleInvoker(provider_id=PROVIDER.provider_id, model=PROVIDER.provider_version,
                                      port=12340, api_key_env="SYNTHETIC_LLM_KEY",
                                      connection_factory=FakeConnection)
    with pytest.raises(ProviderInvocationError) as failure:
        extractor(invoker).extract(DOC, "INVOICE")
    assert failure.value.code is InvocationFailureCode.PROVIDER_FAILED


def test_new_descriptive_berita_acara_rules_precede_the_generic_one():
    assert classify(document("BERITA ACARA PEMERIKSAAN PEKERJAAN")).document_type == "WORK_INSPECTION_REPORT"
    assert classify(document("Berita Acara Serah Terima")).document_type == "HANDOVER_REPORT"
    assert classify(document("BERITA ACARA PEMBAYARAN")).document_type == "PAYMENT_REPORT"
    assert classify(document("Berita Acara Penggunaan Layanan")).document_type == "SERVICE_USAGE_REPORT"
    assert classify(document("BERITA ACARA RAPAT")).document_type == "ACCEPTANCE_REPORT"


def test_earliest_match_policy_resolves_multiple_category_terms():
    lines = ("INVOICE", "Referensi surat pesanan SYN-1")
    assert classify(document(*lines)).document_type == "ORDER_LETTER"  # FIRST_RULE default: profile order
    profile = TitleRuleProfile(PROFILE.profile_id, PROFILE.version, PROFILE.taxonomy_version, PROFILE.rules,
                               PROFILE.heading_blocks, "EARLIEST_MATCH")
    result = classify_document(document(*lines), classifier=TitleRuleClassifier(profile), policy=POLICY, taxonomy=TAXONOMY)
    assert result.document_type == "INVOICE" and [e.block_id for e in result.evidence] == ["b0"]
    with pytest.raises(ValueError, match="INVALID_MATCH_POLICY"):
        TitleRuleProfile("p", "1", "t", PROFILE.rules, 8, "RANDOM")
