"""Tenant-owned storage references and just-in-time fetch policy (ADR-0001, RI-6.0 phase B).

Pure policy and orchestration; network I/O happens behind the `GrantBroker` and
`ObjectFetcher` ports. Grants (bearer URLs and headers) are passed by value to
the fetcher and never stored, logged or returned (blueprint SEC-007).
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

OBJECT_ID = re.compile(r"[A-Za-z0-9._:/=+-]{1,512}")
VERSION_ID = re.compile(r"[A-Za-z0-9._:=+-]{1,256}")
CONNECTION_ID = re.compile(r"[a-z][a-z0-9-]{1,62}")


class SourceError(Exception):
    """Stable, non-secret failure. `permanent` failures produce a FAILED_SAFE result; others are retried."""

    def __init__(self, code: str, *, permanent: bool) -> None:
        super().__init__(code)
        self.code, self.permanent = code, permanent


@dataclass(frozen=True, slots=True)
class Origin:
    host: str
    port: int

    @classmethod
    def parse(cls, text: str) -> "Origin":
        parts = urlsplit(text)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.path not in ("", "/") \
                or parts.query or parts.fragment:
            raise ValueError("INVALID_STORAGE_ORIGIN")
        return cls(parts.hostname.lower(), parts.port or 443)

    def __str__(self) -> str:
        return f"https://{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class StorageConnection:
    connection_id: str
    tenant_id: str
    broker_url: str
    origins: tuple[Origin, ...]
    allow_private_network: bool = False
    disabled: bool = False

    def __post_init__(self) -> None:
        if not CONNECTION_ID.fullmatch(self.connection_id) or not self.origins:
            raise ValueError("INVALID_STORAGE_CONNECTION")
        Origin.parse(_origin_part(self.broker_url))


def _origin_part(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


@dataclass(frozen=True, slots=True)
class SourceReference:
    connection_id: str
    object_id: str
    sha256: str
    version_id: str | None = None

    def __post_init__(self) -> None:
        if not CONNECTION_ID.fullmatch(self.connection_id):
            raise ValueError("INVALID_STORAGE_CONNECTION_ID")
        if not OBJECT_ID.fullmatch(self.object_id) or ".." in self.object_id:
            raise ValueError("INVALID_OBJECT_ID")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("SHA256_REQUIRED")
        if self.version_id is not None and not VERSION_ID.fullmatch(self.version_id):
            raise ValueError("INVALID_VERSION_ID")


@dataclass(frozen=True, slots=True)
class GrantBinding:
    """What the broker authorizes: exactly one object, one version, one read, for one document."""

    tenant_id: str
    connection_id: str
    document_id: str
    object_id: str
    version_id: str | None
    operation: str = "GET"


@dataclass(frozen=True, slots=True)
class Grant:
    url: str
    expires_at: str
    headers: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:  # never print the bearer URL or headers
        return f"Grant(expires_at={self.expires_at!r}, url=<redacted>, headers=<{len(self.headers)} redacted>)"


@dataclass(frozen=True, slots=True)
class FetchTarget:
    host: str
    port: int
    target: str  # path + query, sent verbatim


class GrantBroker(Protocol):
    def request_grant(self, connection: StorageConnection, binding: GrantBinding) -> Grant: ...


class ObjectFetcher(Protocol):
    def fetch(self, target: FetchTarget, grant: Grant, connection: StorageConnection, *, max_bytes: int) -> bytes: ...


FORBIDDEN_HEADER = re.compile(r"(?i)^(host|content-length|transfer-encoding|connection|cookie|te|upgrade)$")


def validate_grant(grant: Grant, connection: StorageConnection) -> FetchTarget:
    """The grant must point to a registered origin over HTTPS, without credentials in the URL."""
    if not isinstance(grant.url, str) or len(grant.url) > 8192 or any(ord(c) < 33 for c in grant.url):
        raise SourceError("SOURCE_BROKER_INVALID_RESPONSE", permanent=True)
    parts = urlsplit(grant.url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise SourceError("SOURCE_HOST_FORBIDDEN", permanent=True)
    origin = Origin(parts.hostname.lower(), parts.port or 443)
    if origin not in connection.origins:
        raise SourceError("SOURCE_HOST_FORBIDDEN", permanent=True)
    for name, value in grant.headers.items():
        if FORBIDDEN_HEADER.fullmatch(name) or "\r" in name + value or "\n" in name + value:
            raise SourceError("SOURCE_BROKER_INVALID_RESPONSE", permanent=True)
    return FetchTarget(origin.host, origin.port, (parts.path or "/") + (f"?{parts.query}" if parts.query else ""))


def check_address(address: str, *, allow_private_network: bool) -> None:
    """Reject destinations an application must never reach by default (blueprint NET-003/004)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:  # e.g. a scoped IPv6 literal such as fe80::1%eth0
        raise SourceError("SOURCE_HOST_FORBIDDEN", permanent=True) from None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # ::1 sits inside the IPv6 reserved block; treat it as loopback like 127.0.0.1.
    always_forbidden = not ip.is_loopback and (ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved or (
        isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("169.254.0.0/16")))
    if always_forbidden:
        # link-local covers cloud metadata endpoints; never allowed, even for private connections
        raise SourceError("SOURCE_HOST_FORBIDDEN", permanent=True)
    if (ip.is_private or ip.is_loopback or not ip.is_global) and not allow_private_network:
        raise SourceError("SOURCE_HOST_FORBIDDEN", permanent=True)


def fetch_verified(reference: SourceReference, binding: GrantBinding, connection: StorageConnection, *,
                   broker: GrantBroker, fetcher: ObjectFetcher, max_bytes: int) -> bytes:
    """Grant → fetch → verify, refreshing an expired grant once. The grant never leaves this frame."""
    if connection.disabled:
        raise SourceError("STORAGE_CONNECTION_DISABLED", permanent=True)
    if binding.tenant_id != connection.tenant_id:
        raise SourceError("SOURCE_ACCESS_DENIED", permanent=True)
    for attempt in (1, 2):
        grant = broker.request_grant(connection, binding)
        target = validate_grant(grant, connection)
        try:
            content = fetcher.fetch(target, grant, connection, max_bytes=max_bytes)
        except SourceError as exc:
            if exc.code == "SOURCE_GRANT_EXPIRED":
                if attempt == 1:
                    continue
                raise SourceError("SOURCE_GRANT_EXPIRED", permanent=True) from None
            raise
        finally:
            del grant
        if hashlib.sha256(content).hexdigest() != reference.sha256:
            raise SourceError("SOURCE_CHECKSUM_MISMATCH", permanent=True)
        return content
    raise SourceError("SOURCE_GRANT_EXPIRED", permanent=True)
