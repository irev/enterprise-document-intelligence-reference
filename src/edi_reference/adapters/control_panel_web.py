"""Control-panel HTTP(S) server: `tlkdoc serve-panel` (RI-4.11).

Standard library only. Security model:
- binding beyond loopback requires TLS (certificate and key supplied by the operator);
- every route except /healthz, the static UI and /api/login requires a session cookie
  (HttpOnly, SameSite=Strict, Secure under TLS);
- every state-changing request requires the per-session CSRF header and a same-origin
  Origin, and the Host header must be one of the configured hosts;
- roles: VIEWER reads, OPERATOR uploads/processes/benchmarks, ADMIN controls runtime,
  configuration and users; every action is written to the hash-chained audit log;
- responses never carry stack traces, credentials or API keys.
"""

from __future__ import annotations

import ipaddress
import json
import re
import ssl
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from edi_reference.adapters.api_v1_web import ApiHTTPServer
from edi_reference.adapters.api_v1_web import make_handler as make_api_handler
from edi_reference.adapters.lmstudio_control import LmStudioControl, LmStudioError, gpu_status
from edi_reference.adapters.normalizers import reference_normalizers
from edi_reference.adapters.openai_compatible import OpenAICompatibleInvoker
from edi_reference.adapters.runtime_ocr import RuntimeOcrEngine, model_dir_digest
from edi_reference.adapters.sqlite_api_store import SqliteApiStore
from edi_reference.application.api_service import SCOPES, ApiService, issue_key
from edi_reference.application.normalization import NormalizationRegistry
from edi_reference.application.panel_audit import AuditLog, verify_chain
from edi_reference.application.panel_auth import LoginThrottle, Role, Session, SessionManager, UserStore
from edi_reference.application.panel_config import KINDS, MODES, ConfigStore
from edi_reference.application.panel_service import (
    PROVIDER_ID,
    SHA256,
    DocumentStore,
    PanelService,
    detect_media_type,
)
from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE

STATIC = Path(__file__).with_name("control_panel_static")
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/static/style.css": ("style.css", "text/css; charset=utf-8")}
MAX_JSON_BYTES = 1_000_000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
COOKIE = "edi_panel"
SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@dataclass(frozen=True, slots=True)
class PanelSettings:
    host: str
    port: int
    state_dir: Path
    ocr_python: Path
    lms_cli: Path
    llm_port: int
    api_key_env: str | None
    default_profile: Path
    default_ocr: dict
    tls_cert: Path | None = None
    tls_key: Path | None = None
    allowed_hosts: tuple[str, ...] = ()
    api_port: int | None = None
    default_registry: Path | None = None


class HttpError(Exception):
    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status, self.code = status, code


class Panel:
    """Composition root: wires stores, adapters and the service."""

    def __init__(self, settings: PanelSettings) -> None:
        self.settings = settings
        state = settings.state_dir
        self.users = UserStore(state / "users.json")
        self.sessions = SessionManager()
        self.throttle = LoginThrottle()
        self.audit = AuditLog(state / "audit.jsonl")
        self.config = ConfigStore(state / "config")
        self.store = DocumentStore(state / "documents")
        self.lms = LmStudioControl(settings.lms_cli, port=settings.llm_port)
        self._seed_config()
        self.service = PanelService(
            store=self.store, config=self.config,
            ocr=lambda cfg: RuntimeOcrEngine(python=settings.ocr_python, ocr=cfg),
            invoker_factory=lambda model: OpenAICompatibleInvoker(
                provider_id=PROVIDER_ID, model=model, port=self._pipeline_port(), api_key_env=settings.api_key_env),
            models=self.lms, runs_dir=state / "benchmarks",
            on_event=lambda actor, action, **kw: self.audit.record(actor, action, **kw),
        )
        self.api_store = SqliteApiStore(state / "api.sqlite3")
        self.api = ApiService(
            store=self.api_store, panel=self.service,
            registry=NormalizationRegistry(reference_normalizers()),
            normalizers={"money": ("money.id-ID.IDR", "1"), "date": ("date.iso-8601", "1"),
                         "identifier": ("identifier.trimmed", "1")},
            on_event=lambda actor, action, **kw: self.audit.record(actor, action, **kw),
        )
        self.api_server: ApiHTTPServer | None = None

    def _pipeline_port(self) -> int:
        return int(self.config.active("pipeline")["llm"]["port"])

    def _seed_config(self) -> None:
        self.config.seed("title_rules", json.loads(self.settings.default_profile.read_text(encoding="utf-8")))
        self.config.seed("extraction_schema", {"schema_id": "business-document-header", "version": "1", "fields": [
            {"field_name": name, "value_type": value_type} for name, value_type in (
                ("document_number", "identifier"), ("document_date", "date"), ("issuer_name", "string"),
                ("recipient_name", "string"), ("total_amount", "money"), ("tax_id", "tax_id"))]})
        self.config.seed("pipeline", {"classification_mode": "rules", "max_pages": 3,
                                      "llm": {"host": "127.0.0.1", "port": self.settings.llm_port,
                                              "model": "google/gemma-4-e2b"},
                                      "ocr": self.settings.default_ocr})
        if self.settings.default_registry is not None and self.settings.default_registry.is_file():
            self.config.seed("extraction_registry", json.loads(self.settings.default_registry.read_text(encoding="utf-8")))

    def taxonomy_types(self) -> list[str]:
        rules = self.config.active("title_rules")["rules"]
        return sorted({rule["document_type"] for rule in rules}) + [UNKNOWN_DOCUMENT_TYPE]


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    if handler.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
        raise HttpError(415, "JSON_REQUIRED")
    length = _length(handler, MAX_JSON_BYTES)
    try:
        body = json.loads(handler.rfile.read(length) or b"{}")
    except ValueError:
        raise HttpError(400, "INVALID_JSON") from None
    if not isinstance(body, dict):
        raise HttpError(400, "INVALID_JSON")
    return body


def _length(handler: BaseHTTPRequestHandler, limit: int) -> int:
    raw = handler.headers.get("Content-Length", "0")
    if not raw.isdecimal() or int(raw) > limit:
        raise HttpError(413, "BODY_TOO_LARGE")
    return int(raw)


def make_handler(panel: Panel):
    settings = panel.settings
    tls = settings.tls_cert is not None
    scheme = "https" if tls else "http"
    hosts = set(settings.allowed_hosts) | {f"127.0.0.1:{settings.port}", f"localhost:{settings.port}"}
    if settings.host not in ("127.0.0.1", "0.0.0.0", "::"):
        hosts.add(f"{settings.host}:{settings.port}")
    origins = {f"{scheme}://{host}" for host in hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "tlkdoc-panel"
        sys_version = ""

        def log_message(self, *args) -> None:  # access is audited instead
            pass

        # ------------------------------------------------------------ plumbing
        def _headers(self, status: int, content_type: str, length: int, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            extra = dict(extra or {})
            self.send_header("Content-Security-Policy", extra.pop(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"))
            if tls:
                self.send_header("Strict-Transport-Security", "max-age=31536000")
            for key, value in extra.items():
                self.send_header(key, value)
            self.end_headers()

        def _send_json(self, value, status: int = 200, extra: dict | None = None) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self._headers(status, "application/json; charset=utf-8", len(body), extra)
            self.wfile.write(body)

        def _client(self) -> str:
            return self.client_address[0]

        def _session(self) -> Session | None:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookie.get(COOKIE)
            return panel.sessions.get(morsel.value if morsel else None)

        def _require(self, role: Role, *, mutating: bool) -> Session:
            session = self._session()
            if session is None:
                raise HttpError(401, "LOGIN_REQUIRED")
            if mutating:
                if self.headers.get("X-CSRF-Token") != session.csrf:
                    raise HttpError(403, "CSRF_REJECTED")
                if self.headers.get("Origin") not in origins:
                    raise HttpError(403, "ORIGIN_REJECTED")
            if session.role < role:
                raise HttpError(403, "ROLE_REQUIRED_" + role.name)
            return session

        def _audit(self, session: Session | None, action: str, **kw) -> None:
            panel.audit.record(session.username if session else "anonymous", action, client=self._client(), **kw)

        def _dispatch(self, method: str) -> None:
            if self.headers.get("Host") not in hosts:
                self._send_json({"error": "HOST_NOT_ALLOWED"}, 421)
                return
            url = urlsplit(self.path)
            try:
                if method == "GET" and url.path in STATIC_FILES:
                    name, content_type = STATIC_FILES[url.path]
                    body = (STATIC / name).read_bytes()
                    self._headers(200, content_type, len(body))
                    self.wfile.write(body)
                    return
                if url.path == "/healthz":
                    self._send_json({"ok": True})
                    return
                function, args = route(method, url.path)
                if function is None:
                    raise HttpError(404, "NOT_FOUND")
                function(self, url, args)
            except HttpError as exc:
                self._send_json({"error": exc.code}, exc.status)
            except LookupError as exc:
                self._send_json({"error": str(exc) or "NOT_FOUND"}, 404)
            except (ValueError, LmStudioError) as exc:
                self._send_json({"error": str(exc) or "INVALID_REQUEST"}, 400)
            except Exception:  # noqa: BLE001 - never leak internals
                self._send_json({"error": "INTERNAL_ERROR"}, 500)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        # ------------------------------------------------------------ auth
        def login(self, url, args) -> None:
            if self.headers.get("Origin") not in origins:
                raise HttpError(403, "ORIGIN_REJECTED")
            body = _json_body(self)
            username = str(body.get("username", ""))[:64]
            password = str(body.get("password", ""))[:256]
            keys = ("user:" + username, "ip:" + self._client())
            if panel.throttle.blocked(*keys):
                panel.audit.record(username or "anonymous", "auth.login", outcome="LOCKED", client=self._client())
                raise HttpError(429, "TOO_MANY_ATTEMPTS")
            user = panel.users.verify(username, password)
            if user is None:
                panel.throttle.failure(*keys)
                panel.audit.record(username or "anonymous", "auth.login", outcome="DENIED", client=self._client())
                raise HttpError(401, "INVALID_CREDENTIALS")
            panel.throttle.success(*keys)
            session = panel.sessions.create(user)
            panel.audit.record(user.username, "auth.login", client=self._client())
            cookie = f"{COOKIE}={session.token}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if tls else "")
            self._send_json({"username": user.username, "role": user.role.name, "csrf": session.csrf},
                            extra={"Set-Cookie": cookie})

        def logout(self, url, args) -> None:
            session = self._require(Role.VIEWER, mutating=True)
            panel.sessions.revoke(session.token)
            self._audit(session, "auth.logout")
            self._send_json({"ok": True}, extra={"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})

        def me(self, url, args) -> None:
            session = self._require(Role.VIEWER, mutating=False)
            self._send_json({"username": session.username, "role": session.role.name, "csrf": session.csrf,
                             "types": panel.taxonomy_types(), "modes": list(MODES)})

        # ------------------------------------------------------------ runtime
        def runtime(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            pipeline = panel.config.active("pipeline")
            lms: dict = {"cli_found": panel.lms.available()}
            if lms["cli_found"]:
                try:
                    lms.update(panel.lms.status())
                    lms["models"] = panel.lms.models()
                except LmStudioError as exc:
                    lms["error"] = str(exc)
            ocr = pipeline["ocr"]
            pins = {}
            for prefix in ("det", "rec"):
                pinned = ocr.get(f"{prefix}_digest")
                try:
                    actual = model_dir_digest(Path(ocr[f"{prefix}_dir"]))
                    pins[prefix] = "PINNED_OK" if pinned == actual else ("MISMATCH" if pinned else "NOT_PINNED")
                except (OSError, ValueError):
                    pins[prefix] = "MISSING"
            self._send_json({"lmstudio": lms, "gpu": gpu_status(),
                             "ocr": {"runtime_found": settings.ocr_python.is_file(), "det": ocr["det_name"],
                                     "rec": ocr["rec_name"], "pins": pins},
                             "pipeline": {"model": pipeline["llm"]["model"], "mode": pipeline["classification_mode"],
                                          "max_pages": pipeline["max_pages"]},
                             "jobs": {"queued": sum(j["status"] == "QUEUED" for j in panel.service.jobs()),
                                      "running": sum(j["status"] == "RUNNING" for j in panel.service.jobs())},
                             "tls": tls})

        def runtime_lmstudio(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            body = _json_body(self)
            action = body.get("action")
            if action == "start":
                panel.lms.start()
            elif action == "stop":
                panel.lms.stop()
            elif action == "load":
                panel.lms.load(str(body.get("model", "")))
            elif action == "unload":
                panel.lms.unload_all()
            else:
                raise HttpError(400, "UNKNOWN_ACTION")
            self._audit(session, "runtime.lmstudio." + action, target=body.get("model"))
            self._send_json({"ok": True})

        # ------------------------------------------------------------ documents
        def documents(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            self._send_json({"documents": panel.store.list_documents()})

        def upload(self, url, args) -> None:
            session = self._require(Role.OPERATOR, mutating=True)
            length = _length(self, MAX_UPLOAD_BYTES)
            filename = parse_qs(url.query).get("filename", ["document"])[0]
            meta = panel.store.put(self.rfile.read(length), filename, uploaded_by=session.username)
            self._audit(session, "document.upload", target=meta["document_id"], media_type=meta["media_type"],
                        byte_length=meta["byte_length"])
            self._send_json(meta, 201)

        def import_folder(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            body = _json_body(self)
            folder = Path(str(body.get("folder", ""))).expanduser()
            if not folder.is_dir():
                raise HttpError(400, "FOLDER_NOT_FOUND")
            pattern = folder.rglob("*") if body.get("recursive") else folder.iterdir()
            imported: list[str] = []
            skipped = 0
            for path in sorted(pattern):
                if len(imported) >= 1000:
                    break
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES or path.name.startswith("~$"):
                    continue
                try:
                    content = path.read_bytes()
                    detect_media_type(content)
                    imported.append(panel.store.put(content, path.name, uploaded_by=session.username)["document_id"])
                except (OSError, ValueError):
                    skipped += 1
            self._audit(session, "document.import_folder", imported=len(imported), skipped=skipped)
            self._send_json({"imported": len(imported), "skipped": skipped})

        def document(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            document_id = _document_id(args[0])
            results = panel.store.results(document_id)
            self._send_json({"meta": panel.store.meta(document_id), "results": [
                {key: r.get(key) for key in ("version", "status", "document_type", "classification_source",
                                             "completed_at", "fields_present", "llm_model", "processed_by", "config",
                                             "error_code")} for r in results]})

        def document_result(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            document_id = _document_id(args[0])
            version = int(args[1])
            for result in panel.store.results(document_id):
                if result["version"] == version:
                    self._send_json(result)
                    return
            raise HttpError(404, "RESULT_NOT_FOUND")

        def document_content(self, url, args) -> None:
            session = self._require(Role.VIEWER, mutating=False)
            document_id = _document_id(args[0])
            meta = panel.store.meta(document_id)
            body = panel.store.content(document_id)
            self._audit(session, "document.download", target=document_id)
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", meta["filenames"][0])[:120] or "document"
            # Untrusted content: always a sandboxed download, never rendered in the panel origin.
            self._headers(200, meta["media_type"], len(body), {
                "Content-Disposition": f'attachment; filename="{safe}"', "Content-Security-Policy": "sandbox"})
            self.wfile.write(body)

        def document_label(self, url, args) -> None:
            session = self._require(Role.OPERATOR, mutating=True)
            document_id = _document_id(args[0])
            label = _json_body(self).get("label") or None
            if label is not None and label not in panel.taxonomy_types():
                raise HttpError(400, "LABEL_NOT_IN_TAXONOMY")
            panel.store.set_label(document_id, label)
            self._audit(session, "document.label", target=document_id, label=label)
            self._send_json({"ok": True})

        # ------------------------------------------------------------ jobs
        def jobs(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            self._send_json({"jobs": panel.service.jobs()})

        def job(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            self._send_json(panel.service.job(args[0]).view(full=True))

        def submit_job(self, url, args) -> None:
            session = self._require(Role.OPERATOR, mutating=True)
            body = _json_body(self)
            ids = [_document_id(str(i)) for i in body.get("document_ids", [])][:1000]
            if not ids:
                raise HttpError(400, "DOCUMENTS_REQUIRED")
            for document_id in ids:
                panel.store.meta(document_id)
            kind = body.get("kind")
            if kind == "process":
                params = {"document_ids": ids, "use_llm": bool(body.get("use_llm", True))}
            elif kind == "benchmark":
                models = [str(m) for m in body.get("models", [])][:10]
                mode = body.get("mode")
                if mode not in MODES or (mode != "rules" and not models):
                    raise HttpError(400, "INVALID_BENCHMARK")
                installed = {m["key"] for m in panel.lms.models()} if models else set()
                if any(m not in installed for m in models):
                    raise HttpError(400, "MODEL_NOT_INSTALLED")
                params = {"document_ids": ids, "models": models, "mode": mode}
            else:
                raise HttpError(400, "UNKNOWN_JOB_KIND")
            job = panel.service.submit(kind, session.username, params)
            self._audit(session, f"job.{kind}.submitted", target=job.job_id, documents=len(ids))
            self._send_json(job.view(), 202)

        def cancel_job(self, url, args) -> None:
            session = self._require(Role.OPERATOR, mutating=True)
            panel.service.cancel(args[0])
            self._audit(session, "job.cancel", target=args[0])
            self._send_json({"ok": True})

        def benchmarks(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            self._send_json({"runs": panel.service.benchmark_runs()})

        def benchmark(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            self._send_json(panel.service.benchmark_run(args[0]))

        # ------------------------------------------------------------ config
        def config(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            kind = _kind(args[0])
            self._send_json({"kind": kind, "active_version": panel.config.active_version(kind),
                             "active": panel.config.get(kind), "versions": panel.config.versions(kind)})

        def config_version(self, url, args) -> None:
            self._require(Role.VIEWER, mutating=False)
            self._send_json(panel.config.get(_kind(args[0]), int(args[1])))

        def config_save(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            kind = _kind(args[0])
            body = _json_body(self)
            content = body.get("content")
            if not isinstance(content, dict):
                raise HttpError(400, "CONTENT_REQUIRED")
            if kind == "pipeline":
                # Pins are only produced by the pin action, never typed in.
                current = panel.config.active("pipeline")["ocr"]
                for prefix in ("det", "rec"):
                    content.setdefault("ocr", {}).pop(f"{prefix}_digest", None)
                    if content["ocr"].get(f"{prefix}_dir") == current.get(f"{prefix}_dir") and current.get(f"{prefix}_digest"):
                        content["ocr"][f"{prefix}_digest"] = current[f"{prefix}_digest"]
            if kind == "extraction_registry":
                # A category schema for a type the active taxonomy cannot predict is a mistake.
                unknown = sorted(set(content.get("categories", {})) - set(panel.taxonomy_types()))
                if unknown:
                    raise HttpError(400, "CATEGORY_NOT_IN_TAXONOMY:" + ",".join(unknown)[:200])
            version = panel.config.save(kind, content, author=session.username, comment=str(body.get("comment", "")))
            self._audit(session, "config.save", target=f"{kind}@{version}")
            self._send_json({"version": version}, 201)

        def config_activate(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            kind = _kind(args[0])
            version = int(_json_body(self).get("version", 0))
            panel.config.activate(kind, version)
            self._audit(session, "config.activate", target=f"{kind}@{version}")
            self._send_json({"ok": True})

        def pin_ocr(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            content = json.loads(json.dumps(panel.config.active("pipeline")))
            for prefix in ("det", "rec"):
                content["ocr"][f"{prefix}_digest"] = model_dir_digest(Path(content["ocr"][f"{prefix}_dir"]))
            version = panel.config.save("pipeline", content, author=session.username, comment="pin OCR model digests")
            self._audit(session, "config.pin_ocr", target=f"pipeline@{version}")
            self._send_json({"version": version}, 201)

        # ------------------------------------------------------------ applications (data-plane API)
        def apps(self, url, args) -> None:
            self._require(Role.ADMIN, mutating=False)
            self._send_json({"applications": panel.api_store.applications(), "scopes": list(SCOPES),
                             "profiles": ["default"], "api_port": settings.api_port})

        def app_create(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            body = _json_body(self)
            application_id = str(body.get("application_id", ""))
            tenant_id = str(body.get("tenant_id", ""))
            ident = re.compile(r"[a-z][a-z0-9-]{1,62}")
            if not ident.fullmatch(application_id) or not ident.fullmatch(tenant_id):
                raise HttpError(400, "INVALID_APPLICATION_OR_TENANT_ID")
            name = str(body.get("name", ""))[:100] or application_id
            try:
                limits = {key: int(body.get(key, default)) for key, default in
                          (("rate_per_minute", 60), ("max_queued", 100), ("max_bytes", 50 * 1024 * 1024))}
            except (TypeError, ValueError):
                raise HttpError(400, "INVALID_LIMITS") from None
            if not (1 <= limits["rate_per_minute"] <= 10_000 and 1 <= limits["max_queued"] <= 100_000
                    and 1 <= limits["max_bytes"] <= 50 * 1024 * 1024):
                raise HttpError(400, "INVALID_LIMITS")
            if panel.api_store.application(application_id) is not None:
                raise HttpError(409, "APPLICATION_EXISTS")
            panel.api_store.create_application(application_id=application_id, tenant_id=tenant_id, name=name,
                                               default_profile="default", allowed_profiles=["default"],
                                               created_by=session.username, **limits)
            self._audit(session, "app.create", target=application_id, tenant=tenant_id)
            self._send_json({"ok": True}, 201)

        def app_key(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            scopes = [str(s) for s in _json_body(self).get("scopes", [])]
            key_id, token = issue_key(panel.api_store, args[0], scopes, created_by=session.username)
            self._audit(session, "app.key.create", target=args[0], key_id=key_id, scopes=scopes)
            # Returned exactly once; only the SHA-256 of the secret is stored.
            self._send_json({"key_id": key_id, "token": token}, 201)

        def app_key_revoke(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            panel.api_store.revoke_key(args[0])
            self._audit(session, "app.key.revoke", target=args[0])
            self._send_json({"ok": True})

        def app_disable(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            disabled = _json_body(self).get("disabled")
            if not isinstance(disabled, bool):
                raise HttpError(400, "DISABLED_FLAG_REQUIRED")
            panel.api_store.set_application_disabled(args[0], disabled)
            self._audit(session, "app.disable" if disabled else "app.enable", target=args[0])
            self._send_json({"ok": True})

        # ------------------------------------------------------------ admin
        def audit(self, url, args) -> None:
            self._require(Role.ADMIN, mutating=False)
            intact, broken = verify_chain(panel.audit.path)
            self._send_json({"intact": intact, "broken_line": broken, "records": panel.audit.tail(300)})

        def users(self, url, args) -> None:
            self._require(Role.ADMIN, mutating=False)
            self._send_json({"users": [{"username": u.username, "role": u.role.name, "disabled": u.disabled}
                                       for u in panel.users.all_users()]})

        def user_save(self, url, args) -> None:
            session = self._require(Role.ADMIN, mutating=True)
            body = _json_body(self)
            username = str(body.get("username", ""))
            role = Role[body["role"]] if body.get("role") in Role.__members__ else None
            password = body.get("password") or None
            disabled = body.get("disabled") if isinstance(body.get("disabled"), bool) else None
            panel.users.upsert(username, password, role, disabled=disabled)
            panel.sessions.revoke_user(username)
            self._audit(session, "user.save", target=username, role=role.name if role else None,
                        password_changed=password is not None, disabled=disabled)
            self._send_json({"ok": True})

    def _kind(value: str) -> str:
        if value not in KINDS:
            raise HttpError(404, "UNKNOWN_CONFIG_KIND")
        return value

    H = Handler
    ID, NUM, NAME = r"([0-9a-f]{64})", r"([0-9]{1,6})", r"([a-z_]{1,40})"
    ROUTES = [(method, re.compile(pattern), function) for method, pattern, function in (
        ("POST", "/api/login", H.login), ("POST", "/api/logout", H.logout), ("GET", "/api/me", H.me),
        ("GET", "/api/runtime", H.runtime), ("POST", "/api/runtime/lmstudio", H.runtime_lmstudio),
        ("GET", "/api/documents", H.documents), ("POST", "/api/documents", H.upload),
        ("POST", "/api/documents/import", H.import_folder),
        ("GET", f"/api/documents/{ID}", H.document),
        ("GET", f"/api/documents/{ID}/results/{NUM}", H.document_result),
        ("GET", f"/api/documents/{ID}/content", H.document_content),
        ("POST", f"/api/documents/{ID}/label", H.document_label),
        ("GET", "/api/jobs", H.jobs), ("POST", "/api/jobs", H.submit_job),
        ("GET", r"/api/jobs/([0-9a-f]{12})", H.job), ("POST", r"/api/jobs/([0-9a-f]{12})/cancel", H.cancel_job),
        ("GET", "/api/benchmarks", H.benchmarks), ("GET", r"/api/benchmarks/([0-9a-f]{12})", H.benchmark),
        ("POST", "/api/config/pipeline/pin-ocr", H.pin_ocr),
        ("GET", f"/api/config/{NAME}", H.config), ("GET", f"/api/config/{NAME}/versions/{NUM}", H.config_version),
        ("POST", f"/api/config/{NAME}", H.config_save), ("POST", f"/api/config/{NAME}/activate", H.config_activate),
        ("GET", "/api/audit", H.audit), ("GET", "/api/users", H.users), ("POST", "/api/users", H.user_save),
        ("GET", "/api/apps", H.apps), ("POST", "/api/apps", H.app_create),
        ("POST", r"/api/apps/([a-z][a-z0-9-]{1,62})/keys", H.app_key),
        ("POST", r"/api/apps/([a-z][a-z0-9-]{1,62})/disable", H.app_disable),
        ("POST", r"/api/keys/(k[0-9A-Z]{16})/revoke", H.app_key_revoke),
    )]

    def route(method: str, path: str):
        for candidate, pattern, function in ROUTES:
            if candidate == method:
                match = pattern.fullmatch(path)
                if match:
                    return function, list(match.groups())
        return None, []

    return Handler


def _document_id(value: str) -> str:
    if not SHA256.fullmatch(value):
        raise HttpError(400, "INVALID_DOCUMENT_ID")
    return value


class PanelHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def create_server(settings: PanelSettings) -> tuple[PanelHTTPServer, Panel]:
    address = ipaddress.ip_address(settings.host)
    if not address.is_loopback and (settings.tls_cert is None or settings.tls_key is None):
        raise ValueError("TLS_REQUIRED_FOR_NON_LOOPBACK_BIND")
    panel = Panel(settings)
    if not panel.users.all_users():
        raise ValueError("NO_PANEL_USERS: create an admin with `tlkdoc panel-user add <name> --role ADMIN`")
    if settings.api_port is not None and settings.api_port == settings.port:
        raise ValueError("API_PORT_MUST_DIFFER_FROM_PANEL_PORT")
    server = PanelHTTPServer((settings.host, settings.port), make_handler(panel))
    context = None
    if settings.tls_cert is not None and settings.tls_key is not None:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(settings.tls_cert), str(settings.tls_key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
    if settings.api_port is not None:
        api_hosts = tuple(host.rsplit(":", 1)[0] + f":{settings.api_port}" for host in settings.allowed_hosts)
        if settings.host not in ("127.0.0.1", "0.0.0.0", "::"):
            api_hosts += (f"{settings.host}:{settings.api_port}",)
        api = ApiHTTPServer((settings.host, settings.api_port), make_api_handler(
            panel.api, panel.audit, port=settings.api_port, tls=context is not None, allowed_hosts=api_hosts))
        if context is not None:
            api.socket = context.wrap_socket(api.socket, server_side=True)
        panel.api_server = api
        panel.api.start()
    return server, panel


