"""Deterministic source-ingestion domain types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from edi_reference.domain.integration import InteractionContext


class SourceDisposition(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"


class SourceRejectionCode(StrEnum):
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    DOCUMENT_TOO_LARGE = "DOCUMENT_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    CONTENT_TYPE_MISMATCH = "CONTENT_TYPE_MISMATCH"


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    max_bytes: int
    allowed_media_types: frozenset[str]


@dataclass(frozen=True, slots=True)
class SourceSubmission:
    content: bytes
    declared_media_type: str | None
    filename: str | None
    context: InteractionContext


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    algorithm: str
    digest: str
    byte_length: int
    detected_media_type: str


@dataclass(frozen=True, slots=True)
class IngestionReceipt:
    disposition: SourceDisposition
    received_at: datetime
    source: SourceIdentity | None = None
    rejection_code: SourceRejectionCode | None = None


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...
