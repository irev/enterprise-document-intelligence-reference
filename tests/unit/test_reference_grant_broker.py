import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from edi_reference.adapters.restricted_http import broker_signature
from scripts.reference_grant_broker import (
    make_handler,
    object_signature,
    object_url_valid,
    resolve_object,
    verify_broker_request,
)

SECRET = b"synthetic-broker-secret"
NOW = 1_800_000_000


def test_request_signature_and_clock_skew():
    body = b'{"x": 1}'
    signature = "v1=" + broker_signature(SECRET, str(NOW), body)
    assert verify_broker_request(SECRET, str(NOW), signature, body, now=NOW + 299)
    assert not verify_broker_request(SECRET, str(NOW), signature, body, now=NOW + 301)
    assert not verify_broker_request(SECRET, str(NOW), signature, b'{"x": 2}', now=NOW)
    assert not verify_broker_request(b"other", str(NOW), signature, body, now=NOW)
    assert not verify_broker_request(SECRET, None, signature, body, now=NOW)


@pytest.mark.parametrize("object_id", ["../secret.txt", "a/../../secret.txt", "/etc/passwd", "a\\b", "C:x", "", "missing"])
def test_object_ids_cannot_escape_the_root(tmp_path, object_id):
    (tmp_path / "secret.txt").write_text("x")
    root = tmp_path / "objects"
    root.mkdir()
    assert resolve_object(root, object_id) is None


def test_object_url_signature_and_expiry():
    key = b"k" * 32
    sig = object_signature(key, "a/b.pdf", NOW + 60)
    assert object_url_valid(key, "a/b.pdf", str(NOW + 60), sig, now=NOW)
    assert not object_url_valid(key, "a/b.pdf", str(NOW + 60), sig, now=NOW + 61)
    assert not object_url_valid(key, "a/c.pdf", str(NOW + 60), sig, now=NOW)


@pytest.fixture
def broker(tmp_path):
    root = tmp_path / "objects"
    (root / "inv").mkdir(parents=True)
    (root / "inv" / "1.pdf").write_bytes(b"%PDF-1.4 synthetic")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(
        root=root, connection_id="store-dev", secret=SECRET, public_origin="https://localhost:9443", clock=lambda: NOW))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def call(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, data


def grant_request(port, *, nonce="n1", object_id="inv/1.pdf", connection="store-dev", secret=SECRET):
    body = json.dumps({"tenant_id": "tenant-dev", "storage_connection_id": connection, "document_id": "doc_X",
                       "object_id": object_id, "version_id": None, "operation": "GET", "nonce": nonce}).encode()
    headers = {"Content-Type": "application/json", "X-Tlkdoc-Timestamp": str(NOW),
               "X-Tlkdoc-Signature": "v1=" + broker_signature(secret, str(NOW), body)}
    return call(port, "POST", "/grants", body, headers)


def test_grant_then_fetch_the_exact_object(broker):
    status, data = grant_request(broker)
    assert status == 200
    url = urlsplit(json.loads(data)["url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "localhost:9443", "/objects/inv/1.pdf")
    assert call(broker, "GET", f"{url.path}?{url.query}") == (200, b"%PDF-1.4 synthetic")
    assert call(broker, "GET", f"/objects/inv/2.pdf?{url.query}")[0] == 403  # signature is bound to the object


def test_broker_rejections(broker):
    assert grant_request(broker, secret=b"wrong")[0] == 401
    assert grant_request(broker, nonce="n2")[0] == 200
    assert grant_request(broker, nonce="n2")[0] == 401  # replay
    assert grant_request(broker, nonce="n3", connection="store-other")[0] == 403
    assert grant_request(broker, nonce="n4", object_id="../escape")[0] == 404
    assert call(broker, "GET", "/objects/inv/1.pdf")[0] == 403
