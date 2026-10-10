"""Reference grant broker and object server for development and tests (ADR-0001). NOT a production component.

One HTTPS listener plays both tenant roles:

- ``POST /grants``: verifies the HMAC-signed, job-bound request from tlkdoc and
  answers with a short-lived, exact-object read URL;
- ``GET /objects/<object_id>?exp=…&sig=…``: serves that object while the URL is
  valid and its signature matches.

Objects are files under ``--root``; an object id is a relative path that must
stay inside it. ``version_id`` is accepted and ignored (files have no versions).

Example (self-signed certificate, loopback only)::

    tlkdoc storage add store-dev --tenant tenant-dev --broker-url https://localhost:9443/grants \\
        --origin https://localhost:9443 --allow-private-network
    python scripts/reference_grant_broker.py --root ./objects --connection-id store-dev \\
        --secret-file .edi/panel/storage-secrets/store-dev.key --cert dev.crt --key dev.key

The worker verifies the certificate, so the self-signed CA must be trusted by
the Python process (for example through ``SSL_CERT_FILE``).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import ssl
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from edi_reference.adapters.restricted_http import broker_signature

MAX_SKEW_SECONDS = 300
GRANT_SECONDS = 120
MAX_REQUEST_BYTES = 16 * 1024


def verify_broker_request(secret: bytes, timestamp: str | None, signature: str | None, body: bytes, *,
                          now: float, max_skew: int = MAX_SKEW_SECONDS) -> bool:
    if not timestamp or not timestamp.isdecimal() or not signature or not signature.startswith("v1="):
        return False
    if abs(now - int(timestamp)) > max_skew:
        return False
    return hmac.compare_digest(signature[3:], broker_signature(secret, timestamp, body))


def resolve_object(root: Path, object_id: str) -> Path | None:
    """The file for an object id, or None when it is missing or would escape the root."""
    if not object_id or ".." in object_id.split("/") or object_id.startswith("/") or "\\" in object_id or ":" in object_id:
        return None
    root = root.resolve()
    path = (root / object_id).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    return path


def object_signature(key: bytes, object_id: str, expires: int) -> str:
    return hmac.new(key, f"{object_id}\n{expires}".encode(), hashlib.sha256).hexdigest()


def object_url_valid(key: bytes, object_id: str, expires: str | None, signature: str | None, *, now: float) -> bool:
    if not expires or not expires.isdecimal() or not signature or int(expires) < now:
        return False
    return hmac.compare_digest(signature, object_signature(key, object_id, int(expires)))


class NonceCache:
    """Rejects a replayed broker request inside the timestamp window."""

    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def first_use(self, nonce: str, now: float) -> bool:
        with self._lock:
            self._seen = {n: t for n, t in self._seen.items() if now - t <= 2 * MAX_SKEW_SECONDS}
            if nonce in self._seen:
                return False
            self._seen[nonce] = now
            return True


def make_handler(*, root: Path, connection_id: str, secret: bytes, public_origin: str,
                 url_key: bytes | None = None, clock=time.time):
    url_key = url_key or secrets.token_bytes(32)
    nonces = NonceCache()

    class Handler(BaseHTTPRequestHandler):
        server_version = "reference-grant-broker"
        sys_version = ""

        def log_message(self, *args) -> None:  # grant URLs carry signatures; do not log request lines
            pass

        def _send(self, status: int, body: bytes = b"", content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != "/grants":
                return self._send(404)
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or int(length) > MAX_REQUEST_BYTES:
                return self._send(413)
            body = self.rfile.read(int(length))
            now = clock()
            if not verify_broker_request(secret, self.headers.get("X-Tlkdoc-Timestamp"),
                                         self.headers.get("X-Tlkdoc-Signature"), body, now=now):
                return self._send(401)
            try:
                request = json.loads(body)
                object_id, nonce = str(request["object_id"]), str(request["nonce"])
                if request["storage_connection_id"] != connection_id or request["operation"] != "GET":
                    return self._send(403)
            except (ValueError, KeyError, TypeError):
                return self._send(400)
            if not nonces.first_use(nonce, now):
                return self._send(401)
            if resolve_object(root, object_id) is None:
                return self._send(404)
            expires = int(now) + GRANT_SECONDS
            url = (f"{public_origin}/objects/{quote(object_id, safe='/')}"
                   f"?exp={expires}&sig={object_signature(url_key, object_id, expires)}")
            expires_at = datetime.fromtimestamp(expires, UTC).isoformat().replace("+00:00", "Z")
            self._send(200, json.dumps({"url": url, "expires_at": expires_at}).encode())

        def do_GET(self) -> None:  # noqa: N802
            parts = urlsplit(self.path)
            if not parts.path.startswith("/objects/"):
                return self._send(404)
            object_id = unquote(parts.path[len("/objects/"):])
            query = parse_qs(parts.query)
            if not object_url_valid(url_key, object_id, (query.get("exp") or [None])[0],
                                    (query.get("sig") or [None])[0], now=clock()):
                return self._send(403)
            path = resolve_object(root, object_id)
            if path is None:
                return self._send(404)
            self._send(200, path.read_bytes(), "application/octet-stream")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True, help="directory holding the objects")
    parser.add_argument("--connection-id", required=True)
    parser.add_argument("--secret-file", type=Path, required=True, help="broker secret printed by `tlkdoc storage add`")
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--public-origin", help="origin placed in grant URLs (default https://localhost:<port>)")
    args = parser.parse_args(argv)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.cert, args.key)
    handler = make_handler(root=args.root, connection_id=args.connection_id,
                           secret=args.secret_file.read_text(encoding="ascii").strip().encode(),
                           public_origin=args.public_origin or f"https://localhost:{args.port}")
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"reference grant broker on https://{args.bind}:{args.port}/grants (development only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
