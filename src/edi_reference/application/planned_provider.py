"""Resolve a planned step through control-plane authorization before invocation."""

from edi_reference.application.provider_config import (
    ProviderConfigurationRegistry,
    resolve_provider,
)
from edi_reference.domain.execution import PlannedStep, ProviderCapability
from edi_reference.domain.provider_config import ResolvedProvider


def authorize_planned_provider(
    step: PlannedStep,
    *,
    provider: ProviderCapability,
    configurations: ProviderConfigurationRegistry,
    tenant_id: str,
    application_id: str,
) -> ResolvedProvider:
    if step.provider_id != provider.provider_id:
        raise ValueError("PLANNED_PROVIDER_ID_MISMATCH")
    if step.provider_version != provider.provider_version:
        raise ValueError("PLANNED_PROVIDER_VERSION_MISMATCH")
    if step.execution_class is not provider.execution_class:
        raise ValueError("PLANNED_EXECUTION_CLASS_MISMATCH")
    if step.capability not in provider.capabilities:
        raise ValueError("PLANNED_CAPABILITY_NOT_SUPPORTED")
    return resolve_provider(
        provider,
        configurations=configurations,
        tenant_id=tenant_id,
        application_id=application_id,
    )
