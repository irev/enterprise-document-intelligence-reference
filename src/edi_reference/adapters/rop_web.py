"""Authenticated loopback operator UI; not the shared-service REST contract."""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.parser import BytesParser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from edi_reference.adapters.rop_normalizers import normalize_field
from edi_reference.adapters.rop_runtime import LocalWorkspaceEngine, fetch_internal_source
from edi_reference.adapters.rop_store import MAX_FILE_BYTES, WorkspaceStore, workstation_lock
from edi_reference.application.rop import process_document
from edi_reference.domain.rop import WorkspaceEngine

LOG = logging.getLogger("edi.workspace")
STATIC = Path(__file__).with_name("rop_static")
TERMINAL = {"REVIEW_REQUIRED", "FAILED", "INTERRUPTED"}


def multipart_file(body: bytes, content_type: str) -> tuple[str, str, bytes]:
    if "\r" in content_type or "\n" in content_type:
        raise ValueError("INVALID_UPLOAD")
    message = BytesParser(policy=policy.default).parsebytes(
        ("Content-Type: " + content_type + "\r\nMIME-Version: 1.0\r\n\r\n").encode("ascii") + body)
    if message.get_content_type() != "multipart/form-data" or not message.is_multipart() or message.defects:
        raise ValueError("INVALID_UPLOAD")
    parts = list(message.iter_parts())
    if len(parts) != 1:
        raise ValueError("ONE_FILE_PER_REQUEST")
    part = parts[0]
    if (part.defects or part.is_multipart() or part.get_content_disposition() != "form-data" or
            part.get_param("name", header="content-disposition") != "file" or
            part.get("Content-Transfer-Encoding") is not None):
        raise ValueError("INVALID_UPLOAD")
    name, data = part.get_filename(), part.get_payload(decode=True)
    if not name or not isinstance(data, bytes):
        raise ValueError("INVALID_UPLOAD")
    return name, part.get_content_type(), data


class WorkspaceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, store: WorkspaceStore, engine: WorkspaceEngine, token: str,
                 actor: str, allowed_hosts: tuple[str, ...] = ()):
        if len(token) < 32 or not token.isascii() or not actor.strip() or len(actor) > 100:
            raise ValueError("STRONG_TOKEN_AND_ACTOR_REQUIRED")
        self.store, self.engine, self.token, self.actor = store, engine, token, actor
        self.allowed_hosts = allowed_hosts
        self.session = secrets.token_urlsafe(32)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="edi-workspace")
        self.slots = threading.BoundedSemaphore(10)
        self.requests = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), WorkspaceHandler)

    def process_request(self, request, client_address):
        if not self.requests.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.requests.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.requests.release()

    def submit(self, name: str, media: str, data: bytes, parent: str | None = None) -> str:
        if not self.slots.acquire(blocking=False):
            raise ValueError("QUEUE_FULL")
        try:
            identifier = self.store.create(name, media, data, parent)
            self.executor.submit(self.process, identifier)
            return identifier
        except Exception:
            self.slots.release()
            raise

    def process(self, identifier: str) -> None:
        try:
            data, media = self.store.content(identifier)
            result = process_document(
                data, media, engine=self.engine, normalize=normalize_field,
                progress=lambda stage, percent: self.store.progress(identifier, stage, percent),
                save_pages=lambda pages: self.store.pages(identifier, pages))
            result["result_version"] = identifier
            result["source_sha256"] = self.store.get(identifier)["digest"]
            self.store.complete(identifier, result)
        except Exception as exc:
            LOG.error("Processing failed document=%s exception=%s", identifier, type(exc).__name__)
            self.store.progress(identifier, "FAILED", 0)
        finally:
            self.slots.release()

    def server_close(self):
        super().server_close()
        self.executor.shutdown(wait=True)


class WorkspaceHandler(BaseHTTPRequestHandler):
    server: WorkspaceServer
    server_version = "edi-workspace"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # Never put URLs, uploaded names, cookies, or extracted content in request logs.
        pass

    def _reply(self, status: int, value, media: str = "application/json", cookie: str | None = None):
        data = value if isinstance(value, bytes) else json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            entry = cookie.get("edi_session")
            return entry is not None and hmac.compare_digest(entry.value, self.server.session)
        except (ValueError, TypeError):
            return False

    def _body(self, maximum: int) -> bytes:
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdecimal():
            raise ValueError("INVALID_LENGTH")
        size = int(lengths[0])
        if not 0 < size <= maximum:
            raise ValueError("REQUEST_TOO_LARGE")
        body = self.rfile.read(size)
        if len(body) != size:
            raise ValueError("INCOMPLETE_REQUEST")
        return body

    def _dispatch(self, method: str):
        host = f"127.0.0.1:{self.server.server_address[1]}"
        if self.headers.get("Host") != host:
            self._reply(403, {"error": "HOST_FORBIDDEN"})
            return
        if method == "POST" and (self.headers.get("Origin") != f"http://{host}" or
                                  self.headers.get("X-Workspace-Request") != "1"):
            self._reply(403, {"error": "ORIGIN_FORBIDDEN"})
            return
        if method == "GET" and self.path in {"/", "/app.js", "/style.css"}:
            name, media = {"/": ("index.html", "text/html; charset=utf-8"),
                           "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                           "/style.css": ("style.css", "text/css; charset=utf-8")}[self.path]
            self._reply(200, (STATIC / name).read_bytes(), media)
            return
        if method == "POST" and self.path == "/workspace/session":
            request = json.loads(self._body(4096))
            token = request.get("token") if isinstance(request, dict) else None
            if not isinstance(token, str) or not token.isascii() or not hmac.compare_digest(token, self.server.token):
                self._reply(401, {"error": "LOGIN_REQUIRED"})
                return
            self._reply(200, {"actor": self.server.actor}, cookie=f"edi_session={self.server.session}; HttpOnly; SameSite=Strict; Path=/")
            return
        if not self._authorized():
            self._reply(401, {"error": "LOGIN_REQUIRED"})
            return
        if method == "GET" and self.path == "/workspace/documents":
            self._reply(200, {"documents": self.server.store.list(), "actor": self.server.actor})
            return
        if method == "GET" and self.path == "/workspace/events":
            self._events(None)
            return
        if method == "POST" and self.path == "/workspace/documents":
            name, media, data = multipart_file(self._body(MAX_FILE_BYTES + 65536), self.headers.get("Content-Type", ""))
            self._reply(202, {"id": self.server.submit(name, media, data)})
            return
        if method == "POST" and self.path == "/workspace/source":
            request = json.loads(self._body(16384))
            if not isinstance(request, dict) or not isinstance(request.get("name"), str):
                raise ValueError("INVALID_REQUEST")
            data, media = fetch_internal_source(request.get("url"), self.server.allowed_hosts)
            self._reply(202, {"id": self.server.submit(request["name"], media, data)})
            return
        match = re.fullmatch(r"/workspace/documents/([a-f0-9]{32})(?:/(events|review|reprocess|pages/[0-9]+))?", self.path)
        if match:
            identifier, action = match.groups()
            document = self.server.store.get(identifier)
            if method == "GET" and action is None:
                self._reply(200, document)
                return
            if method == "GET" and action == "events":
                self._events(identifier)
                return
            if method == "GET" and action and action.startswith("pages/"):
                data, media = self.server.store.content(identifier, int(action.split("/")[1]))
                self._reply(200, data, media)
                return
            if method == "POST" and action == "review":
                request = json.loads(self._body(16384))
                if not isinstance(request, dict):
                    raise ValueError("INVALID_REQUEST")
                version = self.server.store.review(identifier, request.get("expected_version"),
                                                   request.get("values"), self.server.actor)
                self._reply(200, {"review_version": version})
                return
            if method == "POST" and action == "reprocess":
                if document["stage"] not in TERMINAL:
                    raise ValueError("PROCESSING_ACTIVE")
                data, media = self.server.store.content(identifier)
                self._reply(202, {"id": self.server.submit(document["name"], media, data, identifier)})
                return
        self._reply(404, {"error": "NOT_FOUND"})

    def _events(self, identifier: str | None):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        for _ in range(25):
            document = self.server.store.get(identifier) if identifier else None
            payload = json.dumps({"stage": document["stage"], "progress": document["progress"]}
                                 if document else {"documents": self.server.store.list()})
            self.wfile.write(f"data: {payload}\n\n".encode())
            self.wfile.flush()
            if document and document["stage"] in TERMINAL:
                break
            time.sleep(1)

    def _handle(self, method: str):
        try:
            self._dispatch(method)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except KeyError:
            self._reply(404, {"error": "NOT_FOUND"})
        except (ValueError, UnicodeError) as exc:
            code = str(exc)
            allowed = {"REVIEW_CONFLICT", "QUEUE_FULL", "FILE_TYPE_INVALID", "FILE_SIZE_INVALID", "SOURCE_HOST_FORBIDDEN"}
            self._reply(409 if code == "REVIEW_CONFLICT" else 400,
                        {"error": code if code in allowed else "INVALID_REQUEST"})
        except Exception as exc:
            LOG.error("Request failed exception=%s", type(exc).__name__)
            self._reply(500, {"error": "SERVICE_UNAVAILABLE"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


def main():
    parser = argparse.ArgumentParser(description="Local document operator workspace")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=Path(".edi/workspace"))
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    engine = LocalWorkspaceEngine(config)
    with workstation_lock(args.data / "workspace.lock"):
        store = WorkspaceStore(args.data / "workspace.sqlite3")
        server = WorkspaceServer(args.port, store, engine, os.environ.get("EDI_WORKSPACE_TOKEN", ""),
                                 config["actor"], tuple(config.get("storage_hosts", [])))
        store.recover()
        print(f"Workspace: http://127.0.0.1:{server.server_address[1]}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
