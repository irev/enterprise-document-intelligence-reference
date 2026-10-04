"""Resolve provider control-plane configuration without exposing secrets."""

from edi_reference.domain.provider_config import ProviderConfiguration, ResolvedProvider
from edi_reference.domain.execution import ProviderCapability


class ProviderConfigurationError(ValueError):
    pass


class ProviderConfigurationSource:
    """Port for reading current trusted provider configuration."""

    def get(self, provider_id: str) -> ProviderConfiguration | None:
        raise NotImplementedError


class ProviderConfigurationRegistry(ProviderConfigurationSource):
    def __init__(self, configurations: tuple[ProviderConfiguration, ...]):
        self._items: dict[str, ProviderConfiguration] = {}
        for item in configurations:
            if item.provider_id in self._items:
                raise ProviderConfigurationError("DUPLICATE_PROVIDER_CONFIGURATION")
            self._items[item.provider_id] = item

    def get(self, provider_id: str) -> ProviderConfiguration | None:
        return self._items.get(provider_id)


def resolve_provider(
    capability: ProviderCapability,
    *,
    configurations: ProviderConfigurationSource,
    tenant_id: str,
    application_id: str,
) -> ResolvedProvider:
    config = configurations.get(capability.provider_id)
    if config is None:
        raise ProviderConfigurationError("PROVIDER_NOT_CONFIGURED")
    if not config.enabled:
        raise ProviderConfigurationError("PROVIDER_DISABLED")
    if config.tenant_allowlist is not None and tenant_id not in config.tenant_allowlist:
        raise ProviderConfigurationError("PROVIDER_NOT_ALLOWED_FOR_TENANT")
    if config.application_allowlist is not None and application_id not in config.application_allowlist:
        raise ProviderConfigurationError("PROVIDER_NOT_ALLOWED_FOR_APPLICATION")
    return ResolvedProvider(capability, config)
