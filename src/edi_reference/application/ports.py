"""Application ports for shared-service acquisition."""

from dataclasses import dataclass
from typing import Protocol

from edi_reference.domain.integration import InteractionContext
from edi_reference.domain.source import SourceReference


@dataclass(frozen=True, slots=True)
class ApplicationPrincipal:
    application_id: str


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    content: bytes
    declared_media_type: str | None = None
    filename: str | None = None
    external_version: str | None = None
    etag: str | None = None
    connector_version: str | None = None


class ApplicationAuthorizer(Protocol):
    def authorize(self, principal: ApplicationPrincipal, context: InteractionContext) -> None: ...


class SourceAcquirer(Protocol):
    def acquire(self, source: SourceReference, context: InteractionContext) -> AcquiredSource: ...


class AcquisitionAuditSink(Protocol):
    def record(self, event: object) -> None: ...
