import hashlib
import http.client
import json
import socket
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from edi_reference.adapters.api_v1_web import ApiHTTPServer, make_handler
from edi_reference.adapters.normalizers import IdIdrMoneyNormalizer, IsoDateNormalizer, TrimmedIdentifierNormalizer
from edi_reference.adapters.sqlite_api_store import SqliteApiStore
from edi_reference.application.api_service import MAX_ATTEMPTS, ApiService, issue_key
from edi_reference.application.normalization import NormalizationRegistry
from edi_reference.application.panel_audit import AuditLog
from edi_reference.application.panel_config import ConfigStore
from edi_reference.application.panel_service import DocumentStore, PanelService
from edi_reference.application.source_fetch import Grant, SourceError
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.invocation import InvocationResult
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "src/edi_reference/contracts"
RESULT_SCHEMA = json.loads((CONTRACTS / "result-v1.schema.json").read_text(encoding="utf-8"))
RESULT = Draft202012Validator(RESULT_SCHEMA, format_checker=FormatChecker())
PDF = b"%PDF-1.7 synthetic invoice"
LINES = ["INVOICE", "Invoice number SYN-0001", "Tanggal 2026-07-15", "Total Rp 1.250.000,00", "Terbit 15 Juli 2026"]


class Pages:
    def __init__(self, lines):
        self.result = OcrResult((OcrPage(1, 1000.0, 1000.0, tuple(
            OcrTextLine(t, BoundingBox(0.1, 0.05 * i, 0.9, 0.05 * i + 0.04), 0.99) for i, t in enumerate(lines))),))
        self.text_layer = "\n".join(lines)
        self.total_pages = 1
        self.raw_pages = None


class FakeOcr:
    fail = False

    def recognize(self, content, media_type, *, max_pages):
        if FakeOcr.fail:
            raise RuntimeError("OCR_TIMEOUT")
        return Pages(LINES)

    def decode(self, raw):
        raise AssertionError("no cache in tests")


class FakeInvoker:
    def __init__(self, model):
        self.model = model

    def invoke(self, request, limits):
        out = {"fields": {"document_number": "SYN-0001", "document_date": "15 Juli 2026",
                          "total_amount": "Rp 1.250.000,00", "tax_id": "00.000.000.0-000.000"}}
        return InvocationResult("lmstudio-local", request.provider_version, json.dumps(out).encode())


class FakeModels:
    def status(self):
        return {"running": True, "loaded": ["synthetic-model"]}

    def start(self):
        pass

    def load(self, key, *, exclusive=True):
        pass


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def env(tmp_path):
    FakeOcr.fail = False
    config = ConfigStore(tmp_path / "config")
    config.save("title_rules", json.loads((ROOT / "deploy/classification-profiles/title-rules-id-en.json").read_text()), author="t")
    config.save("extraction_schema", {"schema_id": "header", "version": "1", "fields": [
        {"field_name": "document_number", "value_type": "identifier"}, {"field_name": "document_date", "value_type": "date"},
        {"field_name": "total_amount", "value_type": "money"}, {"field_name": "tax_id", "value_type": "tax_id"}]}, author="t")
    config.save("pipeline", {"classification_mode": "rules", "max_pages": 2,
                             "llm": {"host": "127.0.0.1", "port": 12340, "model": "synthetic-model"},
                             "ocr": {"det_name": "d", "det_dir": "/d", "rec_name": "r", "rec_dir": "/r"}}, author="t")
    panel = PanelService(store=DocumentStore(tmp_path / "docs"), config=config, ocr=lambda cfg: FakeOcr(),
                         invoker_factory=FakeInvoker, models=FakeModels(), runs_dir=tmp_path / "runs")
    store = SqliteApiStore(tmp_path / "api.sqlite3")
    audit = AuditLog(tmp_path / "audit.jsonl")
    service = ApiService(store=store, panel=panel,
                         registry=NormalizationRegistry((IdIdrMoneyNormalizer(), IsoDateNormalizer(), TrimmedIdentifierNormalizer())),
                         normalizers={"money": ("money.id-ID.IDR", "1"), "date": ("date.iso-8601", "1"),
                                      "identifier": ("identifier.trimmed", "1")},
                         on_event=lambda actor, action, **kw: audit.record(actor, action, **kw), lease_seconds=60)
    for app, tenant in (("app-a", "tenant-1"), ("app-b", "tenant-1"), ("app-c", "tenant-2")):
        store.create_application(application_id=app, tenant_id=tenant, name=app, default_profile="default",
                                 allowed_profiles=["default"], rate_per_minute=1000, max_queued=50, max_bytes=1024, created_by="t")
    port = free_port()
    server = ApiHTTPServer(("127.0.0.1", port), make_handler(service, audit, port=port, tls=False))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    keys = {app: issue_key(store, app, ["documents:write", "documents:read", "results:read"], created_by="t")[1]
            for app in ("app-a", "app-b", "app-c")}
    yield {"port": port, "service": service, "store": store, "keys": keys, "audit": audit, "tmp": tmp_path}
    server.shutdown()
    server.server_close()
    store.close()


def call(env, method, path, *, key="app-a", body=None, raw=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", env["port"], timeout=10)
    h = {"Host": f"127.0.0.1:{env['port']}"}
    if key:
        h["Authorization"] = "Bearer " + (env["keys"][key] if key in env["keys"] else key)
    payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if raw is not None:
        h["Content-Type"] = "application/pdf"
    elif body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    connection.request(method, path, body=payload, headers=h)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, (json.loads(data) if data else None), response


def upload(env, *, key="app-a", content=PDF, idem="idem-1", extra=None):
    return call(env, "POST", "/v1/documents", key=key, raw=content,
                headers={"Idempotency-Key": idem, "X-Filename": "C:\\fake\\path\\inv.pdf",
                         "X-External-Reference": "po_number=PO-SYN-1", **(extra or {})})


def test_health_openapi_and_host_check(env):
    assert call(env, "GET", "/v1/health", key=None)[1] == {"status": "ok"}
    status, spec, _ = call(env, "GET", "/v1/openapi.json", key=None)
    assert status == 200 and spec["openapi"] == "3.1.0"
    assert call(env, "GET", "/v1/result-v1.schema.json", key=None)[1]["$id"].endswith("result-v1.schema.json")
    status, problem, response = call(env, "GET", "/v1/documents", headers={"Host": "evil.example"})
    assert status == 421 and problem["code"] == "HOST_NOT_ALLOWED"
    assert response.getheader("Content-Type").startswith("application/problem+json")


@pytest.mark.parametrize("token", [None, "garbage", "tlk_k0000000000000000.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"])
def test_missing_or_invalid_key_is_rejected(env, token):
    status, problem, _ = call(env, "GET", "/v1/documents", key=token)
    assert status == 401 and problem["code"] in ("API_KEY_REQUIRED", "API_KEY_INVALID")
    assert problem["request_id"].startswith("req_")


def test_revoked_key_disabled_app_and_scope(env):
    key_id = env["keys"]["app-a"].split(".")[0][4:]
    env["store"].revoke_key(key_id)
    assert call(env, "GET", "/v1/documents")[0] == 401
    env["store"].set_application_disabled("app-b", True)
    assert call(env, "GET", "/v1/documents", key="app-b")[0] == 401
    _, read_only = issue_key(env["store"], "app-c", ["documents:read"], created_by="t")
    env["keys"]["ro"] = read_only
    status, problem, _ = upload(env, key="ro")
    assert status == 403 and problem["code"] == "SCOPE_REQUIRED"


def test_upload_is_idempotent_and_conflicts_are_rejected(env):
    status, doc, response = upload(env)
    assert status == 202 and doc["status"] == "ACCEPTED" and doc["document_id"].startswith("doc_")
    assert response.getheader("Location") == f"/v1/documents/{doc['document_id']}"
    assert doc["filename"] == "inv.pdf" and doc["external_references"] == {"po_number": "PO-SYN-1"}
    status, again, _ = upload(env)
    assert status == 200 and again["document_id"] == doc["document_id"]
    status, problem, _ = upload(env, content=PDF + b" changed")
    assert status == 409 and problem["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
    # the same bytes from another application are a separate document
    status, other, _ = upload(env, key="app-b")
    assert status == 202 and other["document_id"] != doc["document_id"]


@pytest.mark.parametrize(("kwargs", "status", "code"), [
    ({"idem": ""}, 400, "IDEMPOTENCY_KEY_REQUIRED"),
    ({"content": b"MZ not a document"}, 415, "UNSUPPORTED_MEDIA_TYPE"),
    ({"content": b"%PDF-" + b"x" * 2000}, 413, "DOCUMENT_TOO_LARGE"),
    ({"extra": {"X-Processing-Profile": "secret-profile"}}, 400, "PROFILE_NOT_ALLOWED"),
])
def test_submission_validation(env, kwargs, status, code):
    got, problem, _ = upload(env, **kwargs)
    assert (got, problem["code"]) == (status, code)


GRANT_URL = "https://objects.example.test/bucket/obj-1?sig=BEARER-SECRET-123"


class FakeBroker:
    def request_grant(self, connection, binding):
        return Grant(GRANT_URL, "2026-10-11T00:05:00Z", {"X-Grant-Token": "BEARER-SECRET-123"})


class FakeFetcher:
    def __init__(self, outcome):
        self.outcome = outcome

    def fetch(self, target, grant, connection, *, max_bytes):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def reference(env, *, fetched=PDF, sha=None, idem="ref-1", key="app-a", **source):
    env["store"].create_connection(connection_id="store-a", tenant_id="tenant-1", broker_url="https://broker.example.test/g",
                                   origins=["https://objects.example.test"], allow_private_network=False, created_by="t") \
        if env["store"].connection("store-a") is None else None
    env["service"].broker, env["service"].fetcher = FakeBroker(), FakeFetcher(fetched)
    body = {"source": {"method": "STORAGE_REFERENCE", "storage_connection_id": "store-a", "object_id": "inv/2026/1.pdf",
                       "sha256": sha or hashlib.sha256(PDF).hexdigest(), **source}}
    return call(env, "POST", "/v1/documents", key=key, body=body, headers={"Idempotency-Key": idem})


def test_caller_urls_are_never_accepted(env):
    status, problem, _ = call(env, "POST", "/v1/documents", body={"source": {"method": "SIGNED_URL", "url": "https://x"}},
                              headers={"Idempotency-Key": "u1"})
    assert status == 400 and problem["code"] == "CALLER_URL_NOT_ACCEPTED"
    status, problem, _ = call(env, "POST", "/v1/documents", body={"source": {"method": "FTP"}}, headers={"Idempotency-Key": "u2"})
    assert (status, problem["code"]) == (400, "SOURCE_METHOD_NOT_SUPPORTED")
    status, problem, _ = call(env, "POST", "/v1/documents", raw=b"{nope", headers={"Idempotency-Key": "u3",
                                                                                  "Content-Type": "application/json"})
    assert (status, problem["code"]) == (400, "INVALID_JSON")


@pytest.mark.parametrize(("source", "status", "code"), [
    ({"object_id": "../x"}, 400, "INVALID_OBJECT_ID"),
    ({"sha256": "abc"}, 400, "SHA256_REQUIRED"),
    ({"url": "https://x"}, 400, "INVALID_SOURCE"),
    ({"storage_connection_id": "store-zz"}, 404, "STORAGE_CONNECTION_NOT_FOUND"),
])
def test_storage_reference_validation(env, source, status, code):
    got, problem, _ = reference(env, **source)
    assert (got, problem["code"]) == (status, code)


def test_storage_connection_of_another_tenant_is_not_found(env):
    assert reference(env, key="app-c")[1]["code"] == "STORAGE_CONNECTION_NOT_FOUND"
    env["store"].set_connection_disabled("store-a", True)
    assert reference(env, idem="ref-2")[1]["code"] == "STORAGE_CONNECTION_NOT_FOUND"


def test_storage_reference_is_fetched_just_in_time_and_verified(env):
    status, doc, _ = reference(env, version_id="v7", filename="inv.pdf")
    assert status == 202 and doc["media_type"] is None and doc["filename"] == "inv.pdf"
    assert reference(env, version_id="v7", filename="inv.pdf")[0] == 200  # idempotent replay
    assert reference(env)[1]["code"] == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"  # another object version
    assert env["service"].run_once() is True
    result = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")[1]
    assert list(RESULT.iter_errors(result)) == []
    assert result["status"] == "COMPLETED" and result["source"]["media_type"] == "application/pdf"
    assert result["source"]["byte_length"] == len(PDF)
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}")[1]["media_type"] == "application/pdf"


def test_grants_never_reach_storage_results_or_audit(env):
    doc = reference(env)[1]
    env["service"].run_once()
    result = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")[1]
    stored = b"".join(path.read_bytes() for path in env["tmp"].rglob("*") if path.is_file())
    assert b"BEARER-SECRET-123" not in stored and "BEARER-SECRET-123" not in json.dumps(result)


@pytest.mark.parametrize(("outcome", "code"), [
    (b"tampered bytes", "SOURCE_CHECKSUM_MISMATCH"),
    (SourceError("SOURCE_OBJECT_MISSING", permanent=True), "SOURCE_OBJECT_MISSING"),
])
def test_permanent_source_failure_is_failed_safe_without_extraction(env, outcome, code):
    doc = reference(env, fetched=outcome)[1]
    assert env["service"].run_once() is True
    result = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")[1]
    assert list(RESULT.iter_errors(result)) == []
    assert result["failure"] == {"code": code} and result["fields"] == []
    assert result["source"]["media_type"] is None and result["source"]["byte_length"] is None


def test_unsupported_fetched_content_is_failed_safe(env):
    content = b"plain text, not a document"
    doc = reference(env, fetched=content, sha=hashlib.sha256(content).hexdigest())[1]
    env["service"].run_once()
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")[1]["failure"] == {
        "code": "UNSUPPORTED_MEDIA_TYPE"}


def test_transient_source_failure_is_retried(env):
    doc = reference(env, fetched=SourceError("SOURCE_UNREACHABLE", permanent=False))[1]
    with pytest.raises(SourceError):
        env["service"].run_once()
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}")[1]["latest_result_version"] is None
    env["service"].fetcher = FakeFetcher(PDF)
    env["service"]._lease = -1
    with sqlite3.connect(str(env["tmp"] / "api.sqlite3")) as db:
        db.execute("UPDATE jobs SET lease_until = '2000-01-01T00:00:00.000Z'")
    assert env["service"].run_once() is True
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")[1]["status"] == "COMPLETED"


def test_reprocess_appends_a_new_version(env):
    env["store"].set_application_profiles("app-a", ["default", "careful"], "default")
    doc = upload(env)[1]
    path = f"/v1/documents/{doc['document_id']}/reprocess"
    status, problem, _ = call(env, "POST", path, headers={"Idempotency-Key": "r1"})
    assert (status, problem["code"]) == (409, "PROCESSING_ALREADY_PENDING")
    env["service"].run_once()
    first = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/1")[1]

    assert call(env, "POST", path, body={"processing_profile": "fast"}, headers={"Idempotency-Key": "r1"})[1]["code"] == \
        "PROFILE_NOT_ALLOWED"
    status, view, _ = call(env, "POST", path, body={"processing_profile": "careful"}, headers={"Idempotency-Key": "r1"})
    assert status == 202 and view["status"] == "ACCEPTED"
    assert call(env, "POST", path, body={"processing_profile": "careful"}, headers={"Idempotency-Key": "r1"})[0] == 200
    assert call(env, "POST", path, headers={"Idempotency-Key": "r1"})[1]["code"] == \
        "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
    env["service"].run_once()

    second = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/2")[1]
    assert list(RESULT.iter_errors(second)) == []
    assert second["provenance"]["processing_profile"]["id"] == "careful"
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}/results/1")[1] == first
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}")[1]["latest_result_version"] == 2


def test_reprocess_is_limited_to_the_owning_application(env):
    doc = upload(env)[1]
    env["service"].run_once()
    _, tenant_key = issue_key(env["store"], "app-b", ["documents:write", "documents:read:tenant"], created_by="t")
    env["keys"]["tenant-b"] = tenant_key
    path = f"/v1/documents/{doc['document_id']}/reprocess"
    assert call(env, "POST", path, key="tenant-b", headers={"Idempotency-Key": "r1"})[1]["code"] == "DOCUMENT_NOT_FOUND"
    assert call(env, "POST", path, key="app-c", headers={"Idempotency-Key": "r1"})[1]["code"] == "DOCUMENT_NOT_FOUND"
    assert call(env, "POST", path, body={"other": 1}, headers={"Idempotency-Key": "r1"})[1]["code"] == "INVALID_REQUEST"


def test_documents_are_visible_only_to_their_application(env):
    doc = upload(env)[1]
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}")[0] == 200
    status, problem, _ = call(env, "GET", f"/v1/documents/{doc['document_id']}", key="app-b")
    assert status == 404 and problem["code"] == "DOCUMENT_NOT_FOUND"
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}/results", key="app-c")[0] == 404
    assert call(env, "GET", "/v1/documents", key="app-b")[1]["documents"] == []
    _, tenant_key = issue_key(env["store"], "app-b", ["documents:read", "documents:read:tenant"], created_by="t")
    env["keys"]["tenant-b"] = tenant_key
    assert [d["document_id"] for d in call(env, "GET", "/v1/documents", key="tenant-b")[1]["documents"]] == [doc["document_id"]]
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}", key="tenant-b")[0] == 200


def test_processing_produces_a_schema_valid_normalized_result(env):
    doc = upload(env)[1]
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")[0] == 404
    assert env["service"].run_once() is True
    assert env["service"].run_once() is False

    status, view, _ = call(env, "GET", f"/v1/documents/{doc['document_id']}")
    assert view["status"] == "COMPLETED" and view["latest_result_version"] == 1
    status, result, response = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")
    assert status == 200 and response.getheader("ETag") == f'"{result["result_id"]}"'
    assert list(RESULT.iter_errors(result)) == []
    assert result["classification"]["document_type"] == "INVOICE"
    assert result["classification"]["method"] == "TITLE_RULE"
    assert result["classification"]["evidence"][0]["quote"] == "INVOICE"
    fields = {f["name"]: f for f in result["fields"]}
    assert fields["total_amount"]["normalized"]["value"] == {"amount": "1250000.00", "currency": "IDR"}
    assert fields["document_number"]["normalized"]["value"] == "SYN-0001"
    # an Indonesian date stays raw with a stable error instead of being guessed
    assert fields["document_date"]["raw_value"] == "15 Juli 2026"
    assert fields["document_date"]["normalized"] is None
    assert fields["document_date"]["normalization_error"] == "INVALID_DATE_FORMAT"
    assert fields["tax_id"]["state"] == "MISSING"  # model value not found in the source
    assert result["provenance"]["model"] == {"id": "synthetic-model", "execution_class": "LOCAL_MODEL", "data_egress": "NONE"}
    assert result["source"]["external_references"] == {"po_number": "PO-SYN-1"}
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}/results")[1]["results"][0]["result_version"] == 1


def test_ocr_failure_yields_a_valid_failed_safe_result(env):
    FakeOcr.fail = True
    doc = upload(env)[1]
    env["service"].run_once()
    result = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/1")[1]
    assert list(RESULT.iter_errors(result)) == []
    assert result["status"] == "FAILED_SAFE" and result["failure"] == {"code": "OCR_TIMEOUT"}
    assert result["classification"]["document_type"] == "UNKNOWN"
    assert call(env, "GET", f"/v1/documents/{doc['document_id']}")[1]["status"] == "FAILED_SAFE"


def test_results_are_immutable_in_the_database(env):
    doc = upload(env)[1]
    env["service"].run_once()
    db = sqlite3.connect(str(env["tmp"] / "api.sqlite3"))
    with pytest.raises(sqlite3.IntegrityError, match="RESULT_IMMUTABLE"):
        db.execute("UPDATE results SET body = '{}' WHERE document_id = ?", (doc["document_id"],))
    with pytest.raises(sqlite3.IntegrityError, match="RESULT_IMMUTABLE"):
        db.execute("DELETE FROM results")
    db.close()


def test_interrupted_job_is_retried_then_failed_safe(env):
    doc = upload(env)[1]
    for _ in range(MAX_ATTEMPTS):
        assert env["store"].claim(lease_seconds=-1) is not None  # claimed, then the worker "crashes"
    service = env["service"]
    service._lease = -1
    assert service.run_once() is True
    result = call(env, "GET", f"/v1/documents/{doc['document_id']}/results/latest")[1]
    assert result["failure"] == {"code": "PROCESSING_ATTEMPTS_EXHAUSTED"}
    assert list(RESULT.iter_errors(result)) == []


def test_rate_and_queue_limits(env):
    with sqlite3.connect(str(env["tmp"] / "api.sqlite3")) as db:
        db.execute("UPDATE applications SET max_queued = 1 WHERE application_id = 'app-a'")
    upload(env)
    status, problem, response = upload(env, content=PDF + b"2", idem="idem-2")
    assert status == 429 and problem["code"] == "QUEUE_LIMIT_REACHED" and response.getheader("Retry-After")
    with sqlite3.connect(str(env["tmp"] / "api.sqlite3")) as db:
        db.execute("UPDATE applications SET rate_per_minute = 2 WHERE application_id = 'app-c'")
    codes = [call(env, "GET", "/v1/documents", key="app-c")[0] for _ in range(4)]
    assert codes[:2] == [200, 200] and 429 in codes[2:]


def test_discovery_endpoints(env):
    taxonomy = call(env, "GET", "/v1/taxonomy")[1]
    assert "INVOICE" in taxonomy["document_types"] and taxonomy["unknown"] == "UNKNOWN"
    schema = call(env, "GET", "/v1/schemas/INVOICE")[1]
    assert {"name": "total_amount", "value_type": "money", "normalizer": {"id": "money.id-ID.IDR", "version": "1"}} in schema["fields"]
    assert call(env, "GET", "/v1/schemas/MADE_UP")[0] == 404


def test_requests_are_audited_without_secrets(env):
    upload(env)
    call(env, "GET", "/v1/documents", key="garbage")
    # The handler audits in `finally`, after the response is sent: wait for the record.
    deadline = time.monotonic() + 5
    while '"outcome": "401"' not in (text := (env["tmp"] / "audit.jsonl").read_text(encoding="utf-8")) \
            and time.monotonic() < deadline:
        time.sleep(0.02)
    assert '"action": "api.post"' in text and '"outcome": "401"' in text
    assert all(token.split(".")[1] not in text for token in env["keys"].values())


def test_design_examples_validate_against_the_contracts():
    examples = ROOT / "docs/api/examples"
    for name in ("result-completed.json", "result-failed-safe.json", "result-failed-safe-source.json"):
        assert list(RESULT.iter_errors(json.loads((examples / name).read_text(encoding="utf-8")))) == []
    # null source facts are allowed only for a document that was never fetched, i.e. FAILED_SAFE
    completed = json.loads((examples / "result-completed.json").read_text(encoding="utf-8"))
    completed["source"].update(media_type=None, byte_length=None)
    assert list(RESULT.iter_errors(completed)) != []
    spec = json.loads((CONTRACTS / "openapi-v1.json").read_text(encoding="utf-8"))
    registry = Registry().with_resource("urn:openapi", Resource.from_contents(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "components": spec["components"]}))
    exchanges = json.loads((examples / "http-exchanges.json").read_text(encoding="utf-8"))
    reference = {"source": {"method": "STORAGE_REFERENCE", "storage_connection_id": "store-a", "object_id": "inv/1.pdf",
                            "sha256": "0" * 64}}
    caller_url = {"source": {"method": "SIGNED_URL", "url": "https://x"}}
    submission = Draft202012Validator({"$ref": "urn:openapi#/components/schemas/StorageReferenceSubmission"}, registry=registry)
    assert list(submission.iter_errors(reference)) == [] and list(submission.iter_errors(caller_url)) != []
    for schema, body in (("Document", exchanges["submit_upload"]["response"]["body"]),
                         ("Problem", exchanges["idempotency_conflict"]["response"]["body"]),
                         ("WebhookEvent", exchanges["webhook"]["body"])):
        validator = Draft202012Validator({"$ref": f"urn:openapi#/components/schemas/{schema}"}, registry=registry)
        assert list(validator.iter_errors(body)) == []
