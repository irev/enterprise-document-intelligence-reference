"""Tenant/application binding for versioned processing profiles."""

from dataclasses import dataclass

from edi_reference.domain.execution import ExecutionPolicy


@dataclass(frozen=True, slots=True)
class ProcessingProfile:
    profile_id: str
    profile_version: str
    execution_policy: ExecutionPolicy

    def __post_init__(self) -> None:
        if not self.profile_id or not self.profile_version:
            raise ValueError("INVALID_PROCESSING_PROFILE")


@dataclass(frozen=True, slots=True)
class ProcessingProfileBinding:
    tenant_id: str
    application_id: str | None
    profile_id: str
    profile_version: str

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.profile_id or not self.profile_version:
            raise ValueError("INVALID_PROCESSING_PROFILE_BINDING")
        if self.application_id is not None and not self.application_id:
            raise ValueError("INVALID_PROCESSING_PROFILE_BINDING")
