"""Storage references, restricted fetcher and grant broker client (ADR-0001). No network."""

import hashlib
import hmac
import json
import sqlite3

import pytest

from edi_reference.adapters.restricted_http import (
    FileSecretStore,
    HttpGrantBroker,
    HttpObjectFetcher,
    RestrictedHttps,
    broker_signature,
)
from edi_reference.adapters.sqlite_api_store import IdempotencyConflict, SqliteApiStore
from edi_reference.application.source_fetch import (
    FetchTarget,
    Grant,
    GrantBinding,
    Origin,
    SourceError,
    SourceReference,
    StorageConnection,
    check_address,
    fetch_verified,
    validate_grant,
)

CONTENT = b"%PDF-1.4 synthetic"
SHA = hashlib.sha256(CONTENT).hexdigest()
GRANT_URL = "https://objects.example.test/bucket/obj-1?sig=SECRET-SIGNATURE"


def connection(**kw):
    return StorageConnection(**{"connection_id": "store-a", "tenant_id": "tenant-1",
                                "broker_url": "https://broker.example.test/grants",
                                "origins": (Origin.parse("https://objects.example.test"),), **kw})


def binding(tenant="tenant-1"):
    return GrantBinding(tenant, "store-a", "doc_X", "obj-1", None)


# ---------------------------------------------------------------- policy
@pytest.mark.parametrize(("kwargs", "code"), [
    ({"connection_id": "Bad_Id"}, "INVALID_STORAGE_CONNECTION_ID"),
    ({"object_id": "../etc/passwd"}, "INVALID_OBJECT_ID"),
    ({"object_id": "a b"}, "INVALID_OBJECT_ID"),
    ({"sha256": "ABC"}, "SHA256_REQUIRED"),
    ({"version_id": "v 1"}, "INVALID_VERSION_ID"),
])
def test_source_reference_validation(kwargs, code):
    with pytest.raises(ValueError, match=code):
        SourceReference(**{"connection_id": "store-a", "object_id": "inv/2026/1.pdf", "sha256": SHA, **kwargs})


@pytest.mark.parametrize("text", ["http://h", "https://u:p@h", "https://h/path", "https://h?q=1", "ftp://h"])
def test_origin_rejects_non_origins(text):
    with pytest.raises(ValueError):
        Origin.parse(text)


def test_storage_connection_requires_https_broker_and_origins():
    assert str(Origin.parse("https://Objects.Example.test")) == "https://objects.example.test:443"
    with pytest.raises(ValueError):
        connection(broker_url="http://broker.example.test/grants")
    with pytest.raises(ValueError):
        connection(origins=())


@pytest.mark.parametrize(("url", "headers", "code"), [
    ("https://other.example.test/x", {}, "SOURCE_HOST_FORBIDDEN"),
    ("http://objects.example.test/x", {}, "SOURCE_HOST_FORBIDDEN"),
    ("https://u:p@objects.example.test/x", {}, "SOURCE_HOST_FORBIDDEN"),
    ("https://objects.example.test:8443/x", {}, "SOURCE_HOST_FORBIDDEN"),
    ("https://objects.example.test/x", {"Host": "evil"}, "SOURCE_BROKER_INVALID_RESPONSE"),
    ("https://objects.example.test/x", {"X-A": "1\r\nX-B: 2"}, "SOURCE_BROKER_INVALID_RESPONSE"),
    ("https://objects.example.test/x y", {}, "SOURCE_BROKER_INVALID_RESPONSE"),
])
def test_validate_grant_rejects(url, headers, code):
    with pytest.raises(SourceError, match=code):
        validate_grant(Grant(url, "", headers), connection())


def test_validate_grant_keeps_path_and_query():
    target = validate_grant(Grant(GRANT_URL, ""), connection())
    assert target == FetchTarget("objects.example.test", 443, "/bucket/obj-1?sig=SECRET-SIGNATURE")


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "192.168.0.1", "100.64.0.1", "::1", "fc00::1",
                                     "::ffff:10.0.0.1"])
def test_private_addresses_need_explicit_permission(address):
    with pytest.raises(SourceError, match="SOURCE_HOST_FORBIDDEN"):
        check_address(address, allow_private_network=False)
    check_address(address, allow_private_network=True)


@pytest.mark.parametrize("address", ["169.254.169.254", "fe80::1", "fe80::1%eth0", "224.0.0.1", "0.0.0.0", "240.0.0.1",
                                     "::ffff:169.254.169.254"])
def test_metadata_link_local_and_reserved_are_always_forbidden(address):
    with pytest.raises(SourceError, match="SOURCE_HOST_FORBIDDEN"):
        check_address(address, allow_private_network=True)


def test_public_address_is_allowed():
    check_address("93.184.216.34", allow_private_network=False)


class FakeBroker:
    def __init__(self):
        self.calls = 0

    def request_grant(self, conn, bind):
        self.calls += 1
        return Grant(GRANT_URL, "2026-10-11T00:05:00Z")


class FakeFetcher:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)

    def fetch(self, target, grant, conn, *, max_bytes):
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fetch(fetcher, broker=None, conn=None, bind=None):
    return fetch_verified(SourceReference("store-a", "obj-1", SHA), bind or binding(), conn or connection(),
                          broker=broker or FakeBroker(), fetcher=fetcher, max_bytes=1024)


def test_fetch_verified_returns_verified_bytes():
    assert fetch(FakeFetcher(CONTENT)) == CONTENT


def test_checksum_mismatch_is_permanent():
    with pytest.raises(SourceError, match="SOURCE_CHECKSUM_MISMATCH") as info:
        fetch(FakeFetcher(b"tampered"))
    assert info.value.permanent


def test_expired_grant_is_refreshed_once():
    broker = FakeBroker()
    expired = SourceError("SOURCE_GRANT_EXPIRED", permanent=False)
    assert fetch(FakeFetcher(expired, CONTENT), broker) == CONTENT and broker.calls == 2
    with pytest.raises(SourceError, match="SOURCE_GRANT_EXPIRED") as info:
        fetch(FakeFetcher(expired, SourceError("SOURCE_GRANT_EXPIRED", permanent=False)))
    assert info.value.permanent


def test_transient_failure_is_not_permanent():
    with pytest.raises(SourceError) as info:
        fetch(FakeFetcher(SourceError("SOURCE_UNREACHABLE", permanent=False)))
    assert not info.value.permanent


def test_other_tenant_and_disabled_connection_are_refused_before_any_grant():
    broker = FakeBroker()
    with pytest.raises(SourceError, match="SOURCE_ACCESS_DENIED"):
        fetch(FakeFetcher(CONTENT), broker, bind=binding("tenant-2"))
    with pytest.raises(SourceError, match="STORAGE_CONNECTION_DISABLED"):
        fetch(FakeFetcher(CONTENT), broker, conn=connection(disabled=True))
    assert broker.calls == 0


def test_grant_repr_redacts_bearer_values():
    text = repr(Grant(GRANT_URL, "t", {"Authorization": "Bearer SECRET"}))
    assert "SECRET" not in text and "objects.example.test" not in text


# ---------------------------------------------------------------- restricted HTTPS client
class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status, self._body, self._headers = status, body, headers or {}

    def getheader(self, name, default=None):
        return self._headers.get(name, default)

    def read(self, n):
        chunk, self._body = self._body[:n], self._body[n:]
        return chunk


class FakeConnection:
    instances = []

    def __init__(self, host, port, address, context, timeout, response=None):
        self.host, self.port, self.address = host, port, address
        self.response = response
        self.sent = None
        FakeConnection.instances.append(self)

    def request(self, method, target, body=None, headers=None):
        self.sent = (method, target, body, headers)

    def getresponse(self):
        return self.response

    def close(self):
        pass


def client(response, addresses=("93.184.216.34",)):
    FakeConnection.instances = []

    def factory(host, port, address, context, timeout):
        return FakeConnection(host, port, address, context, timeout, response)

    return RestrictedHttps(resolver=lambda host, port: list(addresses), connection_factory=factory)


def get(http, **kw):
    return http.request("GET", "objects.example.test", 443, "/o", allow_private_network=False, headers={},
                        body=None, max_bytes=kw.get("max_bytes", 100))


def test_connects_to_the_checked_address():
    http = client(FakeResponse(200, b"ok"))
    assert get(http) == (200, b"ok")
    assert FakeConnection.instances[0].address == "93.184.216.34"
    assert FakeConnection.instances[0].host == "objects.example.test"


def test_any_forbidden_dns_answer_rejects_the_request():
    http = client(FakeResponse(200, b"ok"), addresses=("93.184.216.34", "127.0.0.1"))
    with pytest.raises(SourceError, match="SOURCE_HOST_FORBIDDEN"):
        get(http)
    assert FakeConnection.instances == []


@pytest.mark.parametrize(("response", "code"), [
    (FakeResponse(302, headers={"Location": "https://elsewhere/"}), "SOURCE_REDIRECT_REFUSED"),
    (FakeResponse(200, b"x", {"Content-Encoding": "gzip"}), "SOURCE_ENCODING_REFUSED"),
    (FakeResponse(200, b"x", {"Content-Length": "101"}), "SOURCE_TOO_LARGE"),
    (FakeResponse(200, b"x" * 101), "SOURCE_TOO_LARGE"),
])
def test_response_policy(response, code):
    with pytest.raises(SourceError, match=code):
        get(client(response))


@pytest.mark.parametrize(("status", "code", "permanent"), [
    (403, "SOURCE_GRANT_EXPIRED", False), (404, "SOURCE_OBJECT_MISSING", True),
    (503, "SOURCE_UNREACHABLE", False), (400, "SOURCE_FETCH_FAILED", True),
])
def test_object_fetcher_maps_storage_status(status, code, permanent):
    fetcher = HttpObjectFetcher(client(FakeResponse(status)))
    with pytest.raises(SourceError, match=code) as info:
        fetcher.fetch(FetchTarget("objects.example.test", 443, "/o"), Grant(GRANT_URL, ""), connection(), max_bytes=10)
    assert info.value.permanent is permanent


def test_object_fetcher_sends_grant_headers_only_to_the_target():
    http = client(FakeResponse(200, CONTENT))
    body = HttpObjectFetcher(http).fetch(FetchTarget("objects.example.test", 443, "/o?sig=1"),
                                         Grant(GRANT_URL, "", {"X-Grant": "g"}), connection(), max_bytes=1024)
    method, target, _, headers = FakeConnection.instances[0].sent
    assert body == CONTENT and (method, target) == ("GET", "/o?sig=1") and headers["X-Grant"] == "g"


def test_broker_request_is_signed_and_bound_to_the_job():
    http = client(FakeResponse(200, json.dumps({"url": GRANT_URL, "expires_at": "t"}).encode()))
    grant = HttpGrantBroker(http, lambda cid: b"secret", clock=lambda: 1_700_000_000).request_grant(connection(), binding())
    assert grant.url == GRANT_URL
    method, target, body, headers = FakeConnection.instances[0].sent
    assert (method, target, FakeConnection.instances[0].host) == ("POST", "/grants", "broker.example.test")
    payload = json.loads(body)
    assert {k: payload[k] for k in ("tenant_id", "storage_connection_id", "document_id", "object_id", "operation")} == {
        "tenant_id": "tenant-1", "storage_connection_id": "store-a", "document_id": "doc_X", "object_id": "obj-1",
        "operation": "GET"}
    expected = hmac.new(b"secret", b"1700000000." + body, hashlib.sha256).hexdigest()
    assert headers["X-Tlkdoc-Signature"] == "v1=" + expected == "v1=" + broker_signature(b"secret", "1700000000", body)


@pytest.mark.parametrize(("response", "code"), [
    (FakeResponse(403), "SOURCE_ACCESS_DENIED"), (FakeResponse(404), "SOURCE_OBJECT_MISSING"),
    (FakeResponse(502), "SOURCE_BROKER_UNAVAILABLE"), (FakeResponse(200, b"not json"), "SOURCE_BROKER_INVALID_RESPONSE"),
    (FakeResponse(200, b'{"url": 5}'), "SOURCE_BROKER_INVALID_RESPONSE"),
    (FakeResponse(200, b'{"url": "https://x", "headers": []}'), "SOURCE_BROKER_INVALID_RESPONSE"),
])
def test_broker_failures(response, code):
    with pytest.raises(SourceError, match=code):
        HttpGrantBroker(client(response), lambda cid: b"s").request_grant(connection(), binding())


def test_file_secret_store(tmp_path):
    store = FileSecretStore(tmp_path / "secrets")
    secret = store.create("store-a")
    assert store.load("store-a") == secret.encode()
    with pytest.raises(FileExistsError):
        store.create("store-a")
    with pytest.raises(SourceError, match="STORAGE_SECRET_MISSING"):
        store.load("store-b")


# ---------------------------------------------------------------- store
@pytest.fixture
def store(tmp_path):
    s = SqliteApiStore(tmp_path / "api.sqlite3")
    s.create_application(application_id="app-a", tenant_id="tenant-1", name="a", default_profile="default",
                         allowed_profiles=["default"], rate_per_minute=10, max_queued=10, max_bytes=1024, created_by="t")
    yield s
    s.close()


def document(document_id="doc_01HZZZZZZZZZZZZZZZZZZZZZZZ"):
    return {"document_id": document_id, "tenant_id": "tenant-1", "application_id": "app-a", "idempotency_key": "k1",
            "fingerprint": "f" * 64, "correlation_id": "c", "sha256": SHA, "media_type": "", "byte_length": 0,
            "filename": None, "external_references": {}, "profile": "default"}


def test_connections_round_trip(store):
    store.create_connection(connection_id="store-a", tenant_id="tenant-1", broker_url="https://b.example.test/g",
                            origins=["https://objects.example.test:443"], allow_private_network=False, created_by="t")
    assert store.connection("store-a")["origins"] == ["https://objects.example.test:443"]
    store.set_connection_disabled("store-a", True)
    assert store.connections()[0]["disabled"] is True
    with pytest.raises(LookupError):
        store.set_connection_disabled("missing", True)


def test_submit_with_source_and_mark_fetched(store):
    store.create_connection(connection_id="store-a", tenant_id="tenant-1", broker_url="https://b.example.test/g",
                            origins=["https://objects.example.test:443"], allow_private_network=False, created_by="t")
    doc = document()
    store.submit(doc, source={"connection_id": "store-a", "object_id": "obj-1", "version_id": None})
    assert store.source(doc["document_id"])["fetched_at"] is None
    store.mark_fetched(doc["document_id"], media_type="application/pdf", byte_length=len(CONTENT))
    assert store.source(doc["document_id"])["fetched_at"] is not None
    assert store.document(doc["document_id"])["media_type"] == "application/pdf"


def test_reprocess_idempotency_pending_and_new_runs(store):
    doc = document()
    store.submit(doc)
    with pytest.raises(ValueError, match="PROCESSING_ALREADY_PENDING"):
        store.reprocess(doc["document_id"], idempotency_key="r1", fingerprint="a" * 64, profile="default")
    job = store.claim(lease_seconds=60)
    assert job["profile"] is None
    store.complete(job["job_id"], doc["document_id"], {"status": "FAILED_SAFE", "classification": {"document_type": "UNKNOWN"}})
    first, replayed = store.reprocess(doc["document_id"], idempotency_key="r1", fingerprint="a" * 64, profile="other")
    assert not replayed and store.reprocess(doc["document_id"], idempotency_key="r1", fingerprint="a" * 64,
                                            profile="other") == (first, True)
    with pytest.raises(IdempotencyConflict):
        store.reprocess(doc["document_id"], idempotency_key="r1", fingerprint="b" * 64, profile="other")
    job = store.claim(lease_seconds=60)
    assert job["job_id"] == first and job["profile"] == "other"
    store.complete(job["job_id"], doc["document_id"], {"status": "FAILED_SAFE", "classification": {"document_type": "UNKNOWN"}})
    second, _ = store.reprocess(doc["document_id"], idempotency_key="r2", fingerprint="a" * 64, profile="other")
    assert second != first


def test_application_profiles(store):
    store.set_application_profiles("app-a", ["fast", "default"], "fast")
    app = store.application("app-a")
    assert app["allowed_profiles"] == ["default", "fast"] and app["default_profile"] == "fast"
    with pytest.raises(ValueError, match="DEFAULT_PROFILE_MUST_BE_ALLOWED"):
        store.set_application_profiles("app-a", ["default"], "fast")
    with pytest.raises(LookupError):
        store.set_application_profiles("missing", ["default"], "default")


def test_phase_a_store_gets_the_job_profile_column(tmp_path):
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, status TEXT NOT NULL, "
               "attempts INTEGER NOT NULL DEFAULT 0, lease_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    db.close()
    SqliteApiStore(path).close()
    db = sqlite3.connect(path)
    assert "profile" in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    db.close()
