"""Restricted HTTPS client, grant broker client and object fetcher (ADR-0001).

- DNS is resolved once; every returned address is checked, and the socket is
  opened to the checked address (pinned) while TLS verifies the certificate for
  the hostname. A rebinding DNS answer cannot redirect the connection.
- HTTPS only, redirects refused, connect and total timeouts, bounded body.
- Grant URLs and headers are used for one request and never logged.

This complements, and does not replace, deny-by-default egress at the host or
network layer (blueprint NET-003).
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import os
import secrets
import socket
import ssl
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from edi_reference.application.source_fetch import (
    FetchTarget,
    Grant,
    GrantBinding,
    SourceError,
    StorageConnection,
    check_address,
)

Resolver = Callable[[str, int], list[str]]


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SourceError("SOURCE_UNREACHABLE", permanent=False) from None
    return sorted({str(info[4][0]) for info in infos})


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, context: ssl.SSLContext, timeout: float) -> None:
        super().__init__(host, port, context=context, timeout=timeout)
        self._address = address
        self._ssl_context = context

    def connect(self) -> None:
        raw = socket.create_connection((self._address, self.port), timeout=self.timeout)
        self.sock = self._ssl_context.wrap_socket(raw, server_hostname=self.host)


ConnectionFactory = Callable[[str, int, str, ssl.SSLContext, float], http.client.HTTPSConnection]


class RestrictedHttps:
    def __init__(self, *, resolver: Resolver = system_resolver, context: ssl.SSLContext | None = None,
                 connection_factory: ConnectionFactory = _PinnedHTTPSConnection, connect_timeout: float = 10.0,
                 total_timeout: float = 120.0) -> None:
        self._resolve = resolver
        self._context = context or ssl.create_default_context()
        self._connect = connection_factory
        self._connect_timeout, self._total_timeout = connect_timeout, total_timeout

    def request(self, method: str, host: str, port: int, target: str, *, allow_private_network: bool,
                headers: dict[str, str], body: bytes | None, max_bytes: int) -> tuple[int, bytes]:
        addresses = self._resolve(host, port)
        if not addresses:
            raise SourceError("SOURCE_UNREACHABLE", permanent=False)
        for address in addresses:  # every answer must be acceptable, not just the first
            check_address(address, allow_private_network=allow_private_network)
        connection = self._connect(host, port, addresses[0], self._context, self._connect_timeout)
        started = time.monotonic()
        try:
            connection.request(method, target, body=body, headers=dict(headers, **{"Accept-Encoding": "identity"}))
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise SourceError("SOURCE_REDIRECT_REFUSED", permanent=True)
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise SourceError("SOURCE_ENCODING_REFUSED", permanent=True)
            declared = response.getheader("Content-Length")
            if declared is not None and (not declared.isdecimal() or int(declared) > max_bytes):
                raise SourceError("SOURCE_TOO_LARGE", permanent=True)
            chunks, size = [], 0
            while True:
                if time.monotonic() - started > self._total_timeout:
                    raise SourceError("SOURCE_TIMEOUT", permanent=False)
                chunk = response.read(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise SourceError("SOURCE_TOO_LARGE", permanent=True)
            return response.status, b"".join(chunks)
        except SourceError:
            raise
        except ssl.SSLCertVerificationError:
            raise SourceError("SOURCE_TLS_VERIFICATION_FAILED", permanent=True) from None
        except (OSError, http.client.HTTPException):
            raise SourceError("SOURCE_UNREACHABLE", permanent=False) from None
        finally:
            connection.close()


class HttpObjectFetcher:
    """GET exactly the granted object; storage status codes become stable source errors."""

    def __init__(self, client: RestrictedHttps) -> None:
        self._client = client

    def fetch(self, target: FetchTarget, grant: Grant, connection: StorageConnection, *, max_bytes: int) -> bytes:
        status, body = self._client.request("GET", target.host, target.port, target.target,
                                            allow_private_network=connection.allow_private_network,
                                            headers=dict(grant.headers), body=None, max_bytes=max_bytes)
        if status == 200:
            return body
        if status in (401, 403):
            # Providers rarely distinguish expiry from denial; one refresh is attempted by the caller.
            raise SourceError("SOURCE_GRANT_EXPIRED", permanent=False)
        if status in (404, 410):
            raise SourceError("SOURCE_OBJECT_MISSING", permanent=True)
        if status >= 500 or status == 429:
            raise SourceError("SOURCE_UNREACHABLE", permanent=False)
        raise SourceError("SOURCE_FETCH_FAILED", permanent=True)


def broker_signature(secret: bytes, timestamp: str, body: bytes) -> str:
    return hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


class HttpGrantBroker:
    """Asks the tenant's broker for a per-object read grant with an HMAC-signed, job-bound request."""

    MAX_RESPONSE = 64 * 1024

    def __init__(self, client: RestrictedHttps, secret_loader: Callable[[str], bytes],
                 clock: Callable[[], float] = time.time) -> None:
        self._client, self._secret, self._clock = client, secret_loader, clock

    def request_grant(self, connection: StorageConnection, binding: GrantBinding) -> Grant:
        parts = urlsplit(connection.broker_url)
        body = json.dumps({"tenant_id": binding.tenant_id, "storage_connection_id": binding.connection_id,
                           "document_id": binding.document_id, "object_id": binding.object_id,
                           "version_id": binding.version_id, "operation": binding.operation,
                           "nonce": secrets.token_hex(16)}, sort_keys=True).encode()
        timestamp = str(int(self._clock()))
        headers = {"Content-Type": "application/json", "X-Tlkdoc-Timestamp": timestamp,
                   "X-Tlkdoc-Signature": "v1=" + broker_signature(self._secret(connection.connection_id), timestamp, body)}
        status, raw = self._client.request("POST", parts.hostname or "", parts.port or 443,
                                           (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
                                           allow_private_network=connection.allow_private_network, headers=headers,
                                           body=body, max_bytes=self.MAX_RESPONSE)
        if status in (401, 403):
            raise SourceError("SOURCE_ACCESS_DENIED", permanent=True)
        if status == 404:
            raise SourceError("SOURCE_OBJECT_MISSING", permanent=True)
        if status != 200:
            raise SourceError("SOURCE_BROKER_UNAVAILABLE", permanent=False)
        try:
            payload = json.loads(raw)
            headers_out = payload.get("headers")
            headers_out = {} if headers_out is None else headers_out
            if not isinstance(payload["url"], str) or not isinstance(headers_out, dict) or len(headers_out) > 20:
                raise ValueError
            return Grant(payload["url"], str(payload.get("expires_at", "")),
                         {str(k): str(v) for k, v in headers_out.items()})
        except (ValueError, KeyError, TypeError):
            raise SourceError("SOURCE_BROKER_INVALID_RESPONSE", permanent=True) from None


class FileSecretStore:
    """Broker secrets as files under the state directory; never in the database or logs.

    A secrets manager or KMS is the production requirement (blueprint §6); this is the
    reference-implementation stand-in, readable only by the service account.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def create(self, connection_id: str) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(32)
        path = self.root / f"{connection_id}.key"
        with open(path, "x", encoding="ascii") as stream:
            stream.write(secret)
        if os.name != "nt":
            os.chmod(path, 0o600)
        return secret

    def load(self, connection_id: str) -> bytes:
        try:
            return (self.root / f"{connection_id}.key").read_text(encoding="ascii").strip().encode()
        except OSError:
            raise SourceError("STORAGE_SECRET_MISSING", permanent=False) from None
