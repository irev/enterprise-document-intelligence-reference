"""Resolve a planned step through control-plane authorization before invocation."""

from edi_reference.application.provider_config import (
    ProviderConfigurationSource,
    resolve_provider,
)
from edi_reference.domain.execution import ExecutionPolicy, PlannedStep, ProviderCapability
from edi_reference.domain.provider_config import ResolvedProvider
from edi_reference.domain.invocation import InvocationLimits, InvocationRequest, InvocationResult
from edi_reference.application.invocation import ProviderInvoker, invoke_provider


def authorize_planned_provider(
    step: PlannedStep,
    *,
    provider: ProviderCapability,
    configurations: ProviderConfigurationSource,
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



def invoke_planned_provider(
    step: PlannedStep,
    *,
    attempt_id: str,
    input_bytes: bytes,
    provider: ProviderCapability,
    configurations: ProviderConfigurationSource,
    tenant_id: str,
    application_id: str,
    policy: ExecutionPolicy,
    limits: InvocationLimits,
    invoker: ProviderInvoker,
) -> InvocationResult:
    """Authorize current control-plane state and invoke exactly the planned step."""
    authorize_planned_provider(
        step,
        provider=provider,
        configurations=configurations,
        tenant_id=tenant_id,
        application_id=application_id,
    )
    request = InvocationRequest(
        attempt_id=attempt_id,
        capability=step.capability,
        provider_id=step.provider_id,
        provider_version=step.provider_version,
        execution_class=step.execution_class,
        input_bytes=input_bytes,
    )
    return invoke_provider(
        request,
        provider=provider,
        policy=policy,
        limits=limits,
        invoker=invoker,
    )
