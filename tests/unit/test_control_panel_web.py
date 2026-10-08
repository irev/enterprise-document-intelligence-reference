import http.client
import json
import socket
import threading
from pathlib import Path

import pytest

from edi_reference.adapters.control_panel_web import PanelSettings, create_server
from edi_reference.application.panel_auth import Role, UserStore

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "synthetic-Pass-123"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def panel(tmp_path):
    port = free_port()
    users = UserStore(tmp_path / "users.json", iterations=1000)
    users.upsert("admin", PASSWORD, Role.ADMIN)
    users.upsert("op", PASSWORD, Role.OPERATOR)
    users.upsert("viewer", PASSWORD, Role.VIEWER)
    settings = PanelSettings(
        host="127.0.0.1", port=port, state_dir=tmp_path, ocr_python=tmp_path / "missing-python",
        lms_cli=tmp_path / "missing-lms", llm_port=12340, api_key_env=None,
        default_profile=ROOT / "deploy/classification-profiles/title-rules-id-en.json",
        default_ocr={"det_name": "d", "det_dir": str(tmp_path), "rec_name": "r", "rec_dir": str(tmp_path)},
        default_registry=ROOT / "deploy/classification-profiles/extraction-registry-business-documents.json",
    )
    server, app = create_server(settings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Client(port), app
    server.shutdown()
    server.server_close()


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None
        self.csrf = None

    def request(self, method, path, body=None, *, raw=None, headers=None, csrf=True, origin=True, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if self.cookie:
            h["Cookie"] = self.cookie
        if method == "POST":
            if origin:
                h["Origin"] = f"http://127.0.0.1:{self.port}"
            if csrf and self.csrf:
                h["X-CSRF-Token"] = self.csrf
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if payload is not None:
            h["Content-Type"] = "application/octet-stream" if raw is not None else "application/json"
        h.update(headers or {})
        connection.request(method, path, body=payload, headers=h)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        try:
            parsed = json.loads(data)
        except ValueError:
            parsed = data
        return response.status, parsed, response

    def login(self, username):
        status, body, response = self.request("POST", "/api/login", {"username": username, "password": PASSWORD})
        assert status == 200, body
        self.cookie = response.getheader("Set-Cookie").split(";")[0]
        self.csrf = body["csrf"]
        return response


def test_static_ui_and_security_headers(panel):
    client, _ = panel
    status, body, response = client.request("GET", "/")
    assert status == 200 and b"Panel Kontrol tlkdoc" in body
    csp = response.getheader("Content-Security-Policy")
    assert "default-src 'self'" in csp and "unsafe-inline" not in csp
    assert response.getheader("X-Frame-Options") == "DENY"
    assert client.request("GET", "/healthz")[1] == {"ok": True}


def test_api_requires_login_and_rejects_foreign_host(panel):
    client, _ = panel
    assert client.request("GET", "/api/documents")[0] == 401
    assert client.request("GET", "/api/me", host="evil.example")[0] == 421


def test_login_sets_strict_httponly_cookie_and_audits(panel):
    client, app = panel
    assert client.request("POST", "/api/login", {"username": "admin", "password": "wrong-Pass-123"})[0] == 401
    cookie = client.login("admin").getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    actions = [(r["action"], r["outcome"]) for r in app.audit.tail()]
    assert ("auth.login", "OK") in actions and ("auth.login", "DENIED") in actions


def test_login_lockout_after_repeated_failures(panel):
    client, _ = panel
    for _ in range(5):
        client.request("POST", "/api/login", {"username": "op", "password": "wrong-Pass-123"})
    assert client.request("POST", "/api/login", {"username": "op", "password": PASSWORD})[0] == 429


def test_mutations_require_csrf_and_same_origin(panel):
    client, _ = panel
    client.login("op")
    pdf = b"%PDF-1.7 synthetic"
    assert client.request("POST", "/api/documents?filename=a.pdf", raw=pdf, csrf=False)[1]["error"] == "CSRF_REJECTED"
    assert client.request("POST", "/api/documents?filename=a.pdf", raw=pdf, origin=False)[1]["error"] == "ORIGIN_REJECTED"
    status, meta, _ = client.request("POST", "/api/documents?filename=a.pdf", raw=pdf)
    assert status == 201 and meta["media_type"] == "application/pdf"


def test_roles_are_enforced(panel):
    client, _ = panel
    client.login("viewer")
    assert client.request("GET", "/api/documents")[0] == 200
    assert client.request("POST", "/api/documents?filename=a.pdf", raw=b"%PDF-1.7")[1]["error"] == "ROLE_REQUIRED_OPERATOR"
    client.login("op")
    assert client.request("POST", "/api/config/pipeline", {"content": {}})[1]["error"] == "ROLE_REQUIRED_ADMIN"
    assert client.request("GET", "/api/audit")[0] == 403
    assert client.request("POST", "/api/runtime/lmstudio", {"action": "start"})[0] == 403


def test_document_label_download_and_job_validation(panel):
    client, _ = panel
    client.login("op")
    meta = client.request("POST", "/api/documents?filename=..%2F..%2Fx.pdf", raw=b"%PDF-1.7 synthetic")[1]
    doc = meta["document_id"]
    assert meta["filenames"] == ["x.pdf"]  # path components stripped
    assert client.request("POST", f"/api/documents/{doc}/label", {"label": "INVOICE"})[0] == 200
    assert client.request("POST", f"/api/documents/{doc}/label", {"label": "MADE_UP"})[1]["error"] == "LABEL_NOT_IN_TAXONOMY"
    status, body, response = client.request("GET", f"/api/documents/{doc}/content")
    assert status == 200 and body == b"%PDF-1.7 synthetic"
    assert response.getheader("Content-Security-Policy") == "sandbox"
    assert response.getheader("Content-Disposition").startswith("attachment")
    assert client.request("GET", "/api/documents/../../etc")[0] == 404
    assert client.request("POST", "/api/jobs", {"kind": "benchmark", "document_ids": [doc], "mode": "llm"})[1]["error"] == "INVALID_BENCHMARK"
    assert client.request("POST", "/api/jobs", {"kind": "process", "document_ids": ["0" * 64]})[0] == 404
    assert client.request("POST", "/api/documents?filename=a.exe", raw=b"MZ")[1]["error"] == "UNSUPPORTED_MEDIA_TYPE"


def test_config_versioning_and_pin_protection_through_api(panel):
    client, _ = panel
    client.login("admin")
    current = client.request("GET", "/api/config/pipeline")[1]
    assert current["active_version"] == 1
    content = dict(current["active"]["content"], max_pages=5)
    content["ocr"] = dict(content["ocr"], det_digest="f" * 64)  # typed-in pin must be ignored
    status, saved, _ = client.request("POST", "/api/config/pipeline", {"content": content, "comment": "five pages"})
    assert status == 201 and saved["version"] == 2
    active = client.request("GET", "/api/config/pipeline")[1]["active"]["content"]
    assert active["max_pages"] == 5 and "det_digest" not in active["ocr"]
    assert client.request("POST", "/api/config/pipeline", {"content": dict(content, max_pages=0)})[1]["error"] == "INVALID_MAX_PAGES"
    assert client.request("POST", "/api/config/pipeline/activate", {"version": 1})[0] == 200
    assert client.request("GET", "/api/config/pipeline")[1]["active_version"] == 1
    assert client.request("GET", "/api/config/unknown")[0] == 404


def test_admin_user_management_revokes_sessions_and_audit_is_intact(panel):
    admin, app = panel
    admin.login("admin")
    op = Client(admin.port)
    op.login("op")
    assert op.request("GET", "/api/documents")[0] == 200
    assert admin.request("POST", "/api/users", {"username": "op", "disabled": True})[0] == 200
    assert op.request("GET", "/api/documents")[0] == 401  # session revoked
    assert admin.request("POST", "/api/users", {"username": "new", "role": "VIEWER", "password": "short"})[1]["error"] == "PASSWORD_TOO_WEAK"
    audit = admin.request("GET", "/api/audit")[1]
    assert audit["intact"] is True
    assert all("password" not in json.dumps(r).lower().replace("password_changed", "") for r in audit["records"])
    users = {u["username"]: u for u in admin.request("GET", "/api/users")[1]["users"]}
    assert users["op"]["disabled"] is True and "password_hash" not in json.dumps(users)


def test_logout_invalidates_session(panel):
    client, _ = panel
    client.login("viewer")
    assert client.request("POST", "/api/logout", {})[0] == 200
    assert client.request("GET", "/api/me")[0] == 401


def test_non_loopback_bind_requires_tls(tmp_path):
    settings = PanelSettings(host="0.0.0.0", port=free_port(), state_dir=tmp_path, ocr_python=tmp_path, lms_cli=tmp_path,
                             llm_port=1, api_key_env=None, default_profile=ROOT / "deploy/classification-profiles/title-rules-id-en.json",
                             default_ocr={})
    with pytest.raises(ValueError, match="TLS_REQUIRED_FOR_NON_LOOPBACK_BIND"):
        create_server(settings)


def test_server_refuses_to_start_without_users(tmp_path):
    settings = PanelSettings(host="127.0.0.1", port=free_port(), state_dir=tmp_path, ocr_python=tmp_path, lms_cli=tmp_path,
                             llm_port=12340, api_key_env=None,
                             default_profile=ROOT / "deploy/classification-profiles/title-rules-id-en.json",
                             default_ocr={"det_name": "d", "det_dir": "/d", "rec_name": "r", "rec_dir": "/r"})
    with pytest.raises(ValueError, match="NO_PANEL_USERS"):
        create_server(settings)


def test_admin_manages_api_applications_and_keys(panel):
    client, app = panel
    client.login("op")
    assert client.request("POST", "/api/apps", {"application_id": "app-x", "tenant_id": "t-1"})[0] == 403
    client.login("admin")
    assert client.request("POST", "/api/apps", {"application_id": "Bad Id", "tenant_id": "t-1"})[1]["error"] == "INVALID_APPLICATION_OR_TENANT_ID"
    assert client.request("POST", "/api/apps", {"application_id": "app-x", "tenant_id": "t-1", "rate_per_minute": 30})[0] == 201
    assert client.request("POST", "/api/apps", {"application_id": "app-x", "tenant_id": "t-1"})[1]["error"] == "APPLICATION_EXISTS"
    status, key, _ = client.request("POST", "/api/apps/app-x/keys", {"scopes": ["documents:write", "results:read"]})
    assert status == 201 and key["token"].startswith(f"tlk_{key['key_id']}.")
    listing = client.request("GET", "/api/apps")[1]
    assert key["token"].split(".")[1] not in json.dumps(listing)  # only the hash is stored
    assert listing["applications"][0]["keys"][0]["scopes"] == ["documents:write", "results:read"]
    assert client.request("POST", "/api/apps/app-x/keys", {"scopes": ["root"]})[0] == 400
    assert client.request("POST", f"/api/keys/{key['key_id']}/revoke", {})[0] == 200
    assert client.request("POST", f"/api/keys/{key['key_id']}/revoke", {})[0] == 404
    assert key["token"].split(".")[1] not in (app.audit.path.read_text(encoding="utf-8"))


def test_api_port_must_differ_from_panel_port(tmp_path):
    port = free_port()
    UserStore(tmp_path / "users.json", iterations=1000).upsert("admin", PASSWORD, Role.ADMIN)
    settings = PanelSettings(host="127.0.0.1", port=port, state_dir=tmp_path, ocr_python=tmp_path, lms_cli=tmp_path,
                             llm_port=12340, api_key_env=None,
                             default_profile=ROOT / "deploy/classification-profiles/title-rules-id-en.json",
                             default_ocr={"det_name": "d", "det_dir": "/d", "rec_name": "r", "rec_dir": "/r"}, api_port=port)
    with pytest.raises(ValueError, match="API_PORT_MUST_DIFFER_FROM_PANEL_PORT"):
        create_server(settings)


def test_registry_categories_must_exist_in_the_active_taxonomy(panel):
    client, _ = panel
    client.login("admin")
    current = client.request("GET", "/api/config/extraction_registry")[1]["active"]["content"]
    bad = dict(current, categories=dict(current["categories"], MADE_UP_REPORT=current["common_schema"] | {"schema_id": "made-up"}))
    status, body, _ = client.request("POST", "/api/config/extraction_registry", {"content": bad, "comment": "test"})
    assert status == 400 and body["error"].startswith("CATEGORY_NOT_IN_TAXONOMY:MADE_UP_REPORT")
