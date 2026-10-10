import copy
import hashlib
import http.client
import json
import sqlite3
import threading

import pytest

from edi_reference.adapters.rop_normalizers import normalize_field
from edi_reference.adapters.rop_runtime import LocalWorkspaceEngine, fetch_internal_source, verify_artifacts
from edi_reference.adapters.rop_store import WorkspaceStore, validate_upload, workstation_lock
from edi_reference.adapters.rop_web import WorkspaceServer, multipart_file
from edi_reference.application.rop import classify, process_document, route_reasons, validate_prediction
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine
from edi_reference.domain.rop import FIELD_LABELS, RoutingPolicy

PNG = b"\x89PNG\r\n\x1a\nsynthetic-test-content"


def ocr(*texts, confidence=.98):
    return OcrResult((OcrPage(1, 1600, 2000, tuple(
        OcrTextLine(text, BoundingBox(.1, .05 + n * .08, .8, .1 + n * .08), confidence)
        for n, text in enumerate(texts))),))


class Engine:
    def __init__(self, result=None, vision=None):
        self.result = result or ocr("Invoice", "Nomor: SYN-001", "Total: Rp 1.250,50")
        self.vision = vision
        self.vision_calls = 0

    def prepare(self, content, media_type):
        return (PNG,)

    def recognize(self, pages):
        return self.result

    def extract_layout(self, pages):
        self.vision_calls += 1
        if self.vision is None:
            raise RuntimeError("offline")
        return copy.deepcopy(self.vision)


def prediction():
    return {"subtype": "Invoice", "fields": {name: {"state": "NOT_PRESENT"} for name in FIELD_LABELS},
            "line_items": []}


def present():
    return {"state": "PRESENT", "raw_value": "1250", "confidence": None,
            "evidence": {"page": 1, "text": "Total 1250", "bbox": [.1, .1, .8, .2]}}


def process(engine):
    return process_document(PNG, "image/png", engine=engine, normalize=normalize_field,
                            progress=lambda *args: None, save_pages=lambda pages: None)


@pytest.mark.parametrize("field,raw,expected", [
    ("total_idr", "Rp 1.234.567,89", {"amount": "1234567.89", "currency": "IDR"}),
    ("document_date", "07/10/2026", "2026-10-07"),
    ("document_date", "2024-02-29", "2024-02-29"),
    ("npwp", "00.000.000.0-000.000", "000000000000000"),
    ("npwp", "0000000000000000", "0000000000000000"),
])
def test_normalization(field, raw, expected):
    assert normalize_field(field, raw) == expected


@pytest.mark.parametrize("field,raw", [("document_date", "29/02/2025"), ("document_date", "1/2/26"),
                                      ("total_idr", "1,234.56"), ("npwp", "00abc0000000000000")])
def test_normalization_rejects_invalid(field, raw):
    with pytest.raises(ValueError):
        normalize_field(field, raw)


def test_fast_path_keeps_evidence_and_never_authorizes():
    engine = Engine()
    result = process(engine)
    assert engine.vision_calls == 0
    assert result["route"] == "OCR" and result["review_required"] is True
    total = result["fields"]["total_idr"]
    assert total["raw_value"] == "Rp 1.250,50"
    assert total["normalized_value"]["amount"] == "1250.50"
    assert total["evidence"]["page"] == 1


def test_unknown_and_conflicting_classification_remain_unknown():
    assert classify(ocr("unrecognized form")) == "UNKNOWN"
    assert classify(ocr("Invoice Receipt")) == "UNKNOWN"


def test_duplicate_field_remains_ambiguous():
    result = process(Engine(ocr("Invoice", "Total: 100", "Total: 200")))
    assert result["fields"]["total_idr"]["state"] == "AMBIGUOUS"


def test_low_quality_routes_locally_and_falls_back_safely():
    engine = Engine(ocr("Invoice", "Total: 100", confidence=.4))
    result = process(engine)
    assert engine.vision_calls == 1
    assert result["route"] == "OCR"
    assert result["warnings"] == ["VISION_UNAVAILABLE_REVIEW_OCR"]


def test_valid_vision_prediction_with_evidence():
    value = prediction()
    value["fields"]["total_idr"] = present()
    result = process(Engine(ocr("Invoice", confidence=.4), value))
    assert result["route"] == "VISION"
    assert result["fields"]["total_idr"]["normalized_value"]["amount"] == "1250"


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(authorization="APPROVED"),
    lambda p: p["fields"]["total_idr"].update(confidence=float("nan")),
    lambda p: p["fields"]["total_idr"]["evidence"].update(page=2),
    lambda p: p["fields"]["total_idr"]["evidence"].update(bbox=[.8, .1, .2, .5]),
    lambda p: p["fields"]["total_idr"].pop("evidence"),
])
def test_untrusted_prediction_rejected(mutation):
    value = prediction()
    value["fields"]["total_idr"] = present()
    mutation(value)
    with pytest.raises(ValueError, match="INVALID_PREDICTION"):
        validate_prediction(value, 1)


def test_spatial_layout_routes_to_vision():
    lines = tuple(OcrTextLine("cell", BoundingBox(x, y, x + .1, y + .02), .99)
                  for y in (.1, .2) for x in (.1, .4, .7))
    result = OcrResult((OcrPage(1, 1500, 2000, lines),))
    assert "TABULAR_LAYOUT" in route_reasons(result, RoutingPolicy())


def test_mime_validation():
    assert validate_upload(PNG, "image/png") == "image/png"
    for data, mime in [(PNG, "image/jpeg"), (b"<script>", "application/pdf"), (b"", "image/png")]:
        with pytest.raises(ValueError):
            validate_upload(data, mime)


def test_multipart_preserves_binary_and_rejects_multiple():
    part = b'--sample\r\nContent-Disposition: form-data; name="file"; filename="test.png"\r\nContent-Type: image/png\r\n\r\n' + PNG + b'\r\n'
    assert multipart_file(part + b"--sample--\r\n", "multipart/form-data; boundary=sample") == ("test.png", "image/png", PNG)
    with pytest.raises(ValueError):
        multipart_file(part + part + b"--sample--\r\n", "multipart/form-data; boundary=sample")


@pytest.mark.parametrize("url", ["https://example.com/a", "https://127.0.0.1/a", "https://169.254.169.254/a",
                                  "https://8.8.8.8/a", "http://10.1.2.3/a", "https://user:secret@10.1.2.3/a"])
def test_source_rejects_before_network(url, monkeypatch):
    monkeypatch.setattr(http.client, "HTTPSConnection", lambda *a, **k: pytest.fail("network must not be contacted"))
    with pytest.raises(ValueError):
        fetch_internal_source(url, ("10.1.2.3", "8.8.8.8", "127.0.0.1", "169.254.169.254"))


def test_internal_source_never_follows_redirect(monkeypatch):
    class Response:
        status = 302

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    with pytest.raises(ValueError, match="SOURCE_FETCH_FAILED"):
        fetch_internal_source("https://10.1.2.3/test?token=synthetic", ("10.1.2.3",))


def test_model_artifacts_must_match_all_files(tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "weights.bin").write_bytes(b"synthetic")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"weights.bin": hashlib.sha256(b"synthetic").hexdigest()}))
    verify_artifacts(root, manifest)
    (root / "weights.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="MODEL_DIGEST_MISMATCH"):
        verify_artifacts(root, manifest)


def test_cloud_vision_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr("edi_reference.adapters.rop_runtime.verify_artifacts", lambda *args: None)
    with pytest.raises(ValueError):
        LocalWorkspaceEngine({"python": __file__, "detection": {"directory": ".", "manifest": "."},
                              "recognition": {"directory": ".", "manifest": "."},
                              "vision": {"host": "8.8.8.8", "port": 443, "model": "synthetic"}})


def test_review_conflict_and_immutability(tmp_path):
    store = WorkspaceStore(tmp_path / "data.sqlite3")
    identifier = store.create("synthetic.png", "image/png", PNG)
    result = process(Engine())
    store.complete(identifier, result)
    store.review(identifier, 0, {"total_idr": "100"}, "synthetic-operator")
    with pytest.raises(ValueError, match="REVIEW_CONFLICT"):
        store.review(identifier, 0, {"total_idr": "999"}, "synthetic-operator")
    stored = store.get(identifier)
    assert stored["result"] == result and stored["review_version"] == 1
    with pytest.raises(sqlite3.IntegrityError, match="IMMUTABLE_RESULT"):
        with store.connect() as db:
            db.execute("UPDATE documents SET result='{}' WHERE id=?", (identifier,))
    child = store.create("synthetic.png", "image/png", PNG, identifier)
    assert child != identifier and store.get(child)["parent_id"] == identifier


def test_second_process_lock_is_rejected(tmp_path):
    with workstation_lock(tmp_path / "workspace.lock"):
        with pytest.raises(OSError):
            with workstation_lock(tmp_path / "workspace.lock"):
                pytest.fail("duplicate lock acquired")


@pytest.fixture
def server(tmp_path):
    server = WorkspaceServer(0, WorkspaceStore(tmp_path / "data.sqlite3"), Engine(), "x" * 32, "synthetic-operator")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(server, method, path, body=None, *, authenticated=True, origin=True, host=None, content_type="application/json"):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    headers = {"Content-Type": content_type}
    if authenticated:
        headers["Cookie"] = "edi_session=" + server.session
    if origin:
        headers.update(Origin=f"http://127.0.0.1:{server.server_address[1]}", **{"X-Workspace-Request": "1"})
    if host:
        headers["Host"] = host
    connection.request(method, path, body, headers)
    response = connection.getresponse()
    status, payload, response_headers = response.status, response.read(), dict(response.getheaders())
    connection.close()
    return status, payload, response_headers


def test_http_security_boundaries(server):
    assert request(server, "GET", "/workspace/documents", authenticated=False)[0] == 401
    assert request(server, "GET", "/workspace/documents", host="attacker.invalid")[0] == 403
    assert request(server, "POST", "/workspace/session", b'{"token":"bad"}', authenticated=False)[0] == 401
    assert request(server, "POST", "/workspace/session", b"{}", origin=False)[0] == 403
    status, _, headers = request(server, "POST", "/workspace/session", json.dumps({"token": "x" * 32}), authenticated=False)
    assert status == 200 and "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]


def test_http_upload_process_review_sse(server):
    body = b'--sample\r\nContent-Disposition: form-data; name="file"; filename="synthetic.png"\r\nContent-Type: image/png\r\n\r\n' + PNG + b'\r\n--sample--\r\n'
    status, payload, _ = request(server, "POST", "/workspace/documents", body, content_type="multipart/form-data; boundary=sample")
    assert status == 202
    identifier = json.loads(payload)["id"]
    server.executor.shutdown(wait=True)
    status, data, _ = request(server, "GET", f"/workspace/documents/{identifier}")
    assert status == 200 and json.loads(data)["stage"] == "REVIEW_REQUIRED"
    status, events, headers = request(server, "GET", f"/workspace/documents/{identifier}/events")
    assert status == 200 and b"REVIEW_REQUIRED" in events and headers["Content-Type"] == "text/event-stream"
    status, _, _ = request(server, "POST", f"/workspace/documents/{identifier}/review",
                           json.dumps({"expected_version": 0, "values": {"total_idr": "500"}}))
    assert status == 200
    assert request(server, "POST", f"/workspace/documents/{identifier}/review",
                   json.dumps({"expected_version": 0, "values": {"total_idr": "999"}}))[0] == 409
    assert server.store.get(identifier)["result"]["fields"]["total_idr"]["raw_value"] == "Rp 1.250,50"


def test_static_frontend_is_local_only(server):
    for path, expected in [("/", b"Workspace"), ("/app.js", b"EventSource"), ("/style.css", b".split")]:
        status, data, headers = request(server, "GET", path, authenticated=False)
        assert status == 200 and expected in data
        assert b"https://" not in data and b"http://" not in data
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
