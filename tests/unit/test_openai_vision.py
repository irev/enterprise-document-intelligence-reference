import base64
import hashlib
import io
import json
from dataclasses import replace

import pytest

from edi_reference.adapters.openai_vision import OpenAICompatibleDocumentAnalyzer
from edi_reference.application.classification import ClassificationPolicy
from edi_reference.application.document_analysis import DocumentAnalyzer
from edi_reference.application.invocation import ProviderInvocationError
from edi_reference.application.provider_config import ProviderConfigurationError, ProviderConfigurationSource
from edi_reference.domain.execution import Capability, DataEgress, ExecutionClass, ExecutionPolicy, ProviderCapability
from edi_reference.domain.extraction import FieldState
from edi_reference.domain.field_schema import ExtractionSchema, FieldDefinition
from edi_reference.domain.invocation import InvocationLimits
from edi_reference.domain.provider_config import ProviderConfiguration
from edi_reference.domain.taxonomy import DocumentTaxonomy


# Synthetic one-pixel PNG; never uses a customer document or a live model.
IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
PROVIDER = ProviderCapability("vision", "synthetic-model-v1", ExecutionClass.REMOTE_MODEL,
                              frozenset({Capability.CLASSIFICATION, Capability.FIELD_EXTRACTION}),
                              DataEgress.APPROVED_EXTERNAL)
LIMITS = InvocationLimits(7, 100_000, 10_000)


class Configurations(ProviderConfigurationSource):
    def __init__(self):
        self.current = ProviderConfiguration("vision", "1", True, "test", "synthetic-model-v1",
            tenant_allowlist=frozenset({"tenant-a"}), application_allowlist=frozenset({("tenant-a", "app-a")}))

    def get(self, provider_id):
        return self.current


def answer():
    return {"classification": {"document_type": "INVOICE", "confidence": 0.95, "bbox": [0.1, 0.1, 0.7, 0.2]},
            "fields": {"number": {"value": "SYN-001", "confidence": 0.9, "bbox": [0.2, 0.3, 0.8, 0.4]},
                       "total": {"value": None, "confidence": 0, "bbox": None}}}


def response(payload=None, *, status=200, finish="stop"):
    raw = json.dumps({"choices": [{"finish_reason": finish, "message": {
        "content": json.dumps(answer() if payload is None else payload)}}]}).encode()
    return status, raw


class Transport:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes or [response()])
        self.sent = []
        self.closed = 0

    def connect(self, host, port, timeout):
        outer = self

        class Connection:
            def request(self, method, path, body, headers):
                outer.sent.append(dict(host=host, port=port, timeout=timeout, method=method,
                                       path=path, body=json.loads(body), headers=headers))

            def getresponse(self):
                outcome = outer.outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                status, raw = outcome
                result = io.BytesIO(raw)
                result.status = status
                return result

            def close(self):
                outer.closed += 1

        return Connection()


def analyzer(transport, **changes):
    options = dict(base_url="https://vision.example.invalid/v1", provider=PROVIDER,
        taxonomy=DocumentTaxonomy("business", "2", frozenset({"INVOICE"})),
        field_matrix={"INVOICE": ExtractionSchema("invoice", "3", (
            FieldDefinition("number", "string"), FieldDefinition("total", "money")))},
        policy=ExecutionPolicy("remote", "1", frozenset({ExecutionClass.REMOTE_MODEL}), True),
        classification_policy=ClassificationPolicy(0.8, 0.1), limits=LIMITS,
        configurations=Configurations(), tenant_id="tenant-a", application_id="app-a",
        connection_factory=transport.connect, sleep=lambda _: None)
    options.update(changes)
    return OpenAICompatibleDocumentAnalyzer(**options)


def analyze(service: DocumentAnalyzer):
    return service.analyze(IMAGE, media_type="image/png", observation_id="obs-synthetic")


def test_image_request_and_canonical_predictions_keep_source_provenance(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_VISION_KEY", "synthetic-secret")
    transport = Transport()
    result = analyze(analyzer(transport, api_key_env="SYNTHETIC_VISION_KEY"))
    sent = transport.sent[0]
    assert (sent["host"], sent["port"], sent["path"], sent["timeout"]) == (
        "vision.example.invalid", 443, "/v1/chat/completions", 7)
    assert sent["headers"]["Authorization"] == "Bearer synthetic-secret"
    assert "synthetic-secret" not in json.dumps(sent["body"])
    content = sent["body"]["messages"][1]["content"]
    assert base64.b64decode(content[1]["image_url"]["url"].split(",")[1]) == IMAGE
    assert json.loads(content[0]["text"])["field_matrix"]["INVOICE"]["version"] == "3"
    assert "untrusted" in sent["body"]["messages"][0]["content"]
    assert result.classification.document_type == "INVOICE"
    assert result.classification.taxonomy_version == "2"
    assert result.observation_sha256 == hashlib.sha256(IMAGE).hexdigest()
    number, total = result.fields
    assert number.state is FieldState.PRESENT and number.raw_value == "SYN-001"
    assert number.extractor_version == "synthetic-model-v1" and number.schema_version == "3"
    assert number.evidence[0].observation_sha256 == result.observation_sha256
    assert number.evidence[0].observation_id == result.observation_id
    assert number.evidence[0].page_number == 1
    assert total.state is FieldState.MISSING and total.evidence == ()
    assert transport.closed == 1


@pytest.mark.parametrize("changes", [
    {"document_type": "UNKNOWN"}, {"document_type": "OUTSIDE_TAXONOMY"},
    {"confidence": 0.3}, {"bbox": None}, {"bbox": [0, 0, 0, 1]},
])
def test_uncertain_or_unsupported_classification_abstains(changes):
    payload = answer()
    payload["classification"].update(changes)
    result = analyze(analyzer(Transport(response(payload))))
    assert result.classification.document_type == "UNKNOWN" and result.fields == ()


@pytest.mark.parametrize("changes", [
    {"value": 123}, {"value": " "}, {"value": "x" * 501}, {"confidence": True},
    {"confidence": float("nan")}, {"bbox": None}, {"bbox": [0.8, 0, 0.2, 1]},
    {"bbox": [False, 0, 1, 1]}, {"bbox": [0, 0, 2, 1]},
])
def test_unsupported_field_claim_is_missing(changes):
    payload = answer()
    payload["fields"]["number"].update(changes)
    payload["fields"]["unrequested"] = {"value": "injected"}
    result = analyze(analyzer(Transport(response(payload))))
    assert len(result.fields) == 2
    assert result.fields[0].state is FieldState.MISSING
    assert result.fields[0].raw_value is None and result.fields[0].evidence == ()


@pytest.mark.parametrize("outcome", [response(status=429), response(status=503), TimeoutError(), ConnectionResetError()])
def test_transient_failures_retry_and_close_connections(outcome):
    transport = Transport(outcome, response())
    assert analyze(analyzer(transport)).classification.document_type == "INVOICE"
    assert len(transport.sent) == transport.closed == 2


def test_timeout_exhaustion_has_stable_code_without_exception_details():
    transport = Transport(TimeoutError("private details"), TimeoutError("private details"))
    with pytest.raises(ProviderInvocationError, match="^PROVIDER_TIMEOUT$"):
        analyze(analyzer(transport))
    assert transport.closed == 2


@pytest.mark.parametrize("outcome", [
    response(status=401), response(status=302), response(finish="length"),
    (200, b"not json"), (200, b'{"choices": []}'), response([]),
    response({"classification": {"document_type": "INVOICE", "confidence": True}, "fields": {}}),
])
def test_invalid_response_is_not_retried(outcome):
    transport = Transport(outcome)
    with pytest.raises(ProviderInvocationError, match="^INVALID_PROVIDER_RESPONSE$"):
        analyze(analyzer(transport))
    assert transport.closed == 1


def test_revocation_during_retry_prevents_second_request():
    configurations = Configurations()
    transport = Transport(response(status=503))

    def revoke(_):
        configurations.current = replace(configurations.current, enabled=False)

    with pytest.raises(ProviderConfigurationError, match="PROVIDER_DISABLED"):
        analyze(analyzer(transport, configurations=configurations, sleep=revoke))
    assert transport.closed == 1


@pytest.mark.parametrize("changes, error", [
    ({"tenant_id": "tenant-b"}, "PROVIDER_NOT_ALLOWED_FOR_TENANT"),
    ({"application_id": "app-b"}, "PROVIDER_NOT_ALLOWED_FOR_APPLICATION"),
    ({"policy": ExecutionPolicy("deny", "1", frozenset({ExecutionClass.REMOTE_MODEL}), False)}, "EGRESS_NOT_ALLOWED"),
])
def test_authorization_and_egress_fail_before_http(changes, error):
    transport = Transport()
    with pytest.raises((ProviderInvocationError, ProviderConfigurationError), match=error):
        analyze(analyzer(transport, **changes))
    assert transport.sent == []


@pytest.mark.parametrize("limit", [10, len(IMAGE) + 1])
def test_raw_and_encoded_request_size_limits_prevent_http(limit):
    transport = Transport()
    with pytest.raises(ProviderInvocationError, match="RESOURCE_LIMIT_EXCEEDED"):
        analyze(analyzer(transport, limits=replace(LIMITS, max_input_bytes=limit)))
    assert transport.sent == []


def test_response_size_is_bounded_and_not_retried():
    transport = Transport((200, b"x" * 101))
    with pytest.raises(ProviderInvocationError, match="RESOURCE_LIMIT_EXCEEDED"):
        analyze(analyzer(transport, limits=replace(LIMITS, max_output_bytes=100)))
    assert transport.closed == 1


def test_missing_key_never_opens_connection(monkeypatch):
    monkeypatch.delenv("SYNTHETIC_VISION_KEY", raising=False)
    transport = Transport()
    with pytest.raises(ProviderInvocationError, match="PROVIDER_FAILED"):
        analyze(analyzer(transport, api_key_env="SYNTHETIC_VISION_KEY"))
    assert transport.sent == []


@pytest.mark.parametrize("url", ["http://vision.example.invalid/v1", "ftp://host/v1", "https://user:secret@host/v1",
                                 "https://host/v1?key=secret", "https://host/v1#fragment"])
def test_invalid_or_unapproved_endpoint_rejected(url):
    with pytest.raises(ValueError):
        analyzer(Transport(), base_url=url)


def test_http_requires_explicit_configuration_and_still_requires_egress():
    transport = Transport()
    analyze(analyzer(transport, base_url="http://ai-server/v1", allow_insecure_http=True))
    assert transport.sent[0]["host"] == "ai-server" and transport.sent[0]["port"] == 80


@pytest.mark.parametrize("media_type, image", [("application/pdf", b"%PDF"), ("image/png", b"not an image")])
def test_unsupported_input_is_rejected_before_http(media_type, image):
    transport = Transport()
    with pytest.raises(ValueError, match="VISION_REQUIRES_PNG_OR_JPEG"):
        analyzer(transport).analyze(image, media_type=media_type, observation_id="obs")
    assert transport.sent == []
