"""Deterministic in-memory adapters for reference tests."""

from dataclasses import dataclass, field

from edi_reference.application.acquire import AcquisitionEvent
from edi_reference.application.ports import ApplicationPrincipal
from edi_reference.domain.integration import InteractionContext


class AccessDeniedError(PermissionError):
    pass


@dataclass
class StaticApplicationAuthorizer:
    grants: set[tuple[str, str]]

    def authorize(self, principal: ApplicationPrincipal, context: InteractionContext) -> None:
        if principal.application_id != context.application_id:
            raise AccessDeniedError("APPLICATION_CONTEXT_MISMATCH")
        if (principal.application_id, context.tenant_id) not in self.grants:
            raise AccessDeniedError("TENANT_ACCESS_DENIED")


@dataclass
class InMemoryAcquisitionAudit:
    events: list[AcquisitionEvent] = field(default_factory=list)

    def record(self, event: AcquisitionEvent) -> None:
        self.events.append(event)
