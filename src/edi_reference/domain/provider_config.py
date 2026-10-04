"""Provider control-plane configuration vocabulary."""

from dataclasses import dataclass

from edi_reference.domain.execution import ProviderCapability


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    provider_id: str
    config_version: str
    enabled: bool
    deployment_zone: str
    engine_ref: str
    secret_ref: str | None = None
    endpoint_ref: str | None = None
    tenant_allowlist: frozenset[str] = frozenset()
    application_allowlist: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.provider_id or not self.config_version:
            raise ValueError("INVALID_PROVIDER_CONFIGURATION")
        if not self.deployment_zone or not self.engine_ref:
            raise ValueError("INVALID_PROVIDER_CONFIGURATION")
        if self.secret_ref is not None and not self.secret_ref:
            raise ValueError("INVALID_SECRET_REFERENCE")
        if self.endpoint_ref is not None and not self.endpoint_ref:
            raise ValueError("INVALID_ENDPOINT_REFERENCE")


@dataclass(frozen=True, slots=True)
class ResolvedProvider:
    capability: ProviderCapability
    configuration: ProviderConfiguration
