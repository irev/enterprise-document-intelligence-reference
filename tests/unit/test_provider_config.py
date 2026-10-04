import pytest

from edi_reference.application.provider_config import (
    ProviderConfigurationError, ProviderConfigurationRegistry, resolve_provider,
)
from edi_reference.domain.execution import (
    Capability, DataEgress, ExecutionClass, ProviderCapability,
)
from edi_reference.domain.provider_config import ProviderConfiguration


PROVIDER = ProviderCapability(
    "local-model", "1", ExecutionClass.LOCAL_MODEL,
    frozenset({Capability.CLASSIFICATION}), DataEgress.NONE,
)


def config(**changes):
    values = dict(
        provider_id="local-model", config_version="3", enabled=True,
        deployment_zone="trusted-local", engine_ref="document-model-v2",
        secret_ref=None, endpoint_ref="local-inference",
        tenant_allowlist=None, application_allowlist=None,
    )
    values.update(changes)
    return ProviderConfiguration(**values)


def test_enabled_provider_resolves_for_application():
    result = resolve_provider(
        PROVIDER, configurations=ProviderConfigurationRegistry((config(),)),
        tenant_id="tenant-a", application_id="app-a",
    )
    assert result.configuration.engine_ref == "document-model-v2"


def test_disabled_provider_is_not_resolved():
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_DISABLED"):
        resolve_provider(
            PROVIDER, configurations=ProviderConfigurationRegistry((config(enabled=False),)),
            tenant_id="tenant-a", application_id="app-a",
        )


def test_tenant_and_application_allowlists_are_enforced():
    restricted = config(
        tenant_allowlist=frozenset({"tenant-a"}),
        application_allowlist=frozenset({("tenant-a", "app-a")}),
    )
    registry = ProviderConfigurationRegistry((restricted,))
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_NOT_ALLOWED_FOR_TENANT"):
        resolve_provider(PROVIDER, configurations=registry, tenant_id="tenant-b", application_id="app-a")
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_NOT_ALLOWED_FOR_APPLICATION"):
        resolve_provider(PROVIDER, configurations=registry, tenant_id="tenant-a", application_id="app-b")


def test_duplicate_provider_configuration_is_rejected():
    with pytest.raises(ProviderConfigurationError, match="DUPLICATE_PROVIDER_CONFIGURATION"):
        ProviderConfigurationRegistry((config(), config()))


def test_explicit_empty_allowlist_denies_every_tenant():
    registry = ProviderConfigurationRegistry((config(tenant_allowlist=frozenset()),))
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_NOT_ALLOWED_FOR_TENANT"):
        resolve_provider(PROVIDER, configurations=registry, tenant_id="tenant-a", application_id="app-a")


def test_explicit_empty_allowlist_denies_every_application():
    registry = ProviderConfigurationRegistry((config(application_allowlist=frozenset()),))
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_NOT_ALLOWED_FOR_APPLICATION"):
        resolve_provider(PROVIDER, configurations=registry, tenant_id="tenant-a", application_id="app-a")
