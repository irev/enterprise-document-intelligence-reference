"""v1 data-plane HTTP(S) listener (RI-6.0, phase A).

Separate listener from the control panel (decision D1) so machine credentials
and human sessions never share a port. Standard library only. Every request is
authenticated by API key, authorized by scope and ownership, rate limited per
application and written to the audit log. Errors are RFC 9457 problem+json
with a stable code; internals are never returned.
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from edi_reference.application.api_service import ApiError, ApiPrincipal, ApiService, new_id
from edi_reference.application.panel_audit import AuditLog

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
STATIC = {"/v1/openapi.json": "openapi-v1.json", "/v1/result-v1.schema.json": "result-v1.schema.json"}
DOCUMENT_STATUSES = {"RECEIVED", "ACCEPTED", "PROCESSING", "COMPLETED", "FAILED_SAFE", "REJECTED", "UNSUPPORTED"}
UPLOAD_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/tiff"}
DOC = r"(doc_[0-9A-Z]{26})"


def document_view(row: dict) -> dict:
    links = {"self": f"/v1/documents/{row['document_id']}"}
    if row["latest_result_version"]:
        links["latest_result"] = f"/v1/documents/{row['document_id']}/results/{row['latest_result_version']}"
    return {"document_id": row["document_id"], "status": row["status"], "status_code": row["status_code"],
            "correlation_id": row["correlation_id"], "processing_profile": row["profile"], "filename": row["filename"],
            "media_type": row["media_type"], "sha256": row["sha256"], "external_references": row["external_references"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "latest_result_version": row["latest_result_version"], "links": links}


def make_handler(service: ApiService, audit: AuditLog, *, port: int, tls: bool, allowed_hosts: tuple[str, ...] = ()):
    hosts = set(allowed_hosts) | {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "tlkdoc-api"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, *args) -> None:  # audited instead
            pass

        def _send(self, status: int, payload, *, content_type: str = "application/json", headers: dict | None = None) -> None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("X-Request-Id", self.request_id)
            if tls:
                self.send_header("Strict-Transport-Security", "max-age=31536000")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _problem(self, error: ApiError) -> None:
            slug = error.code.lower().replace("_", "-")
            headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
            self._send(error.status, {"type": f"https://tlkdoc.local/problems/{slug}", "title": error.title,
                                      "status": error.status, "code": error.code, "request_id": self.request_id},
                       content_type="application/problem+json", headers=headers)

        def _dispatch(self, method: str) -> None:
            self.request_id = new_id("req")
            principal: ApiPrincipal | None = None
            path = urlsplit(self.path).path
            outcome, target = 500, None
            try:
                if self.headers.get("Host") not in hosts:
                    raise ApiError(421, "HOST_NOT_ALLOWED", "Host not allowed")
                if method == "GET" and path == "/v1/health":
                    outcome = 200
                    self._send(200, {"status": "ok"})
                    return
                if method == "GET" and path in STATIC:
                    outcome = 200
                    self._send(200, (CONTRACTS / STATIC[path]).read_bytes())
                    return
                for candidate, pattern, function in ROUTES:
                    match = pattern.fullmatch(path) if candidate == method else None
                    if match:
                        principal = service.authenticate(self.headers.get("Authorization"))
                        target = match.group(1) if match.groups() else None
                        outcome = function(self, principal, *match.groups())
                        return
                raise ApiError(404, "NOT_FOUND", "Not found")
            except ApiError as error:
                outcome = error.status
                self._drain()
                self._problem(error)
            except Exception:  # noqa: BLE001 - never leak internals
                outcome = 500
                self._drain()
                self._problem(ApiError(500, "INTERNAL_ERROR", "Internal error"))
            finally:
                if principal is not None or outcome in (401, 403):
                    audit.record(f"app:{principal.application_id}" if principal else "anonymous",
                                 f"api.{method.lower()}", target=target, outcome=str(outcome), client=self.client_address[0],
                                 key_id=principal.key_id if principal else None, path=path[:200], request_id=self.request_id)

        def _drain(self) -> None:
            # Keep the connection usable when an error is raised before the body was read.
            if getattr(self, "_body_read", True) is False and self.headers.get("Content-Length", "0").isdecimal():
                remaining = int(self.headers["Content-Length"])
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 1 << 16))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._body_read = False
            self._dispatch("POST")

        # ------------------------------------------------------------ routes
        def submit(self, principal: ApiPrincipal) -> int:
            principal.require("documents:write")
            content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type == "application/json":
                raise ApiError(400, "SOURCE_METHOD_NOT_AVAILABLE", "URL submission is not available yet; upload the bytes")
            if content_type not in UPLOAD_TYPES:
                raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Unsupported media type")
            length = self.headers.get("Content-Length")
            if length is None or not length.isdecimal():
                raise ApiError(411, "LENGTH_REQUIRED", "Content-Length required")
            limit = min(int(principal.application["max_bytes"]), 50 * 1024 * 1024)
            if int(length) > limit:
                raise ApiError(413, "DOCUMENT_TOO_LARGE", "Document too large")
            content = self.rfile.read(int(length))
            self._body_read = True
            document, replayed = service.submit_upload(
                principal, content, idempotency_key=self.headers.get("Idempotency-Key"),
                correlation_id=self.headers.get("X-Correlation-Id"), filename=self.headers.get("X-Filename"),
                profile=self.headers.get("X-Processing-Profile"),
                external_references=self.headers.get_all("X-External-Reference") or [])
            view = document_view(document)
            status = 200 if replayed else 202
            self._send(status, view, headers={"Location": view["links"]["self"]})
            return status

        def list_documents(self, principal: ApiPrincipal) -> int:
            principal.require("documents:read")
            query = parse_qs(urlsplit(self.path).query)
            def one(name: str) -> str | None:
                values = query.get(name)
                return values[0] if values else None

            status = one("status")
            if status is not None and status not in DOCUMENT_STATUSES:
                raise ApiError(400, "INVALID_STATUS", "Invalid status filter")
            reference = one("external_reference")
            pair = None
            if reference is not None:
                match = re.fullmatch(r"([A-Za-z0-9_.-]{1,50})=(.{1,200})", reference)
                if match is None:
                    raise ApiError(400, "INVALID_EXTERNAL_REFERENCE", "Use key=value")
                pair = (match.group(1), match.group(2))
            try:
                limit = int(one("limit") or 50)
            except ValueError:
                raise ApiError(400, "INVALID_LIMIT", "Invalid limit") from None
            if not 1 <= limit <= 200:
                raise ApiError(400, "INVALID_LIMIT", "Invalid limit")
            cursor = one("cursor")
            if cursor is not None:
                service.owned_document(principal, cursor)
            created_after = one("created_after")
            if created_after is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[0-9:.]+Z", created_after):
                raise ApiError(400, "INVALID_CREATED_AFTER", "Use an ISO-8601 UTC timestamp")
            scope_app = None if "documents:read:tenant" in principal.scopes else principal.application_id
            rows = service.store.documents(principal.tenant_id, scope_app, status=status, created_after=created_after,  # type: ignore[attr-defined]
                                           external_reference=pair, limit=limit, cursor=cursor)
            self._send(200, {"documents": [document_view(r) for r in rows],
                             "next_cursor": rows[-1]["document_id"] if len(rows) == limit else None})
            return 200

        def get_document(self, principal: ApiPrincipal, document_id: str) -> int:
            principal.require("documents:read")
            self._send(200, document_view(service.owned_document(principal, document_id)))
            return 200

        def list_results(self, principal: ApiPrincipal, document_id: str) -> int:
            principal.require("results:read")
            service.owned_document(principal, document_id)
            rows = service.store.results(document_id)  # type: ignore[attr-defined]
            self._send(200, {"results": [dict(r, review_status="NOT_REVIEWED") for r in rows]})
            return 200

        def get_result(self, principal: ApiPrincipal, document_id: str, version: str) -> int:
            principal.require("results:read")
            service.owned_document(principal, document_id)
            body = service.store.result(document_id, None if version == "latest" else int(version))  # type: ignore[attr-defined]
            if body is None:
                raise ApiError(404, "RESULT_NOT_FOUND", "Result not found")
            self._send(200, body, headers={"ETag": f'"{body["result_id"]}"'})
            return 200

        def taxonomy(self, principal: ApiPrincipal) -> int:
            principal.require("documents:read")
            self._send(200, service.taxonomy())
            return 200

        def field_schema(self, principal: ApiPrincipal, document_type: str) -> int:
            principal.require("documents:read")
            self._send(200, service.field_schema(document_type))
            return 200

    H = Handler
    ROUTES = [(method, re.compile(pattern), function) for method, pattern, function in (
        ("POST", "/v1/documents", H.submit),
        ("GET", "/v1/documents", H.list_documents),
        ("GET", f"/v1/documents/{DOC}", H.get_document),
        ("GET", f"/v1/documents/{DOC}/results", H.list_results),
        ("GET", f"/v1/documents/{DOC}/results/([1-9][0-9]{{0,5}}|latest)", H.get_result),
        ("GET", "/v1/taxonomy", H.taxonomy),
        ("GET", r"/v1/schemas/([A-Z][A-Z0-9_]{1,63})", H.field_schema),
    )]
    return Handler


class ApiHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64
