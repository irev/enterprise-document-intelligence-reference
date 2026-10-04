"""Application-level OCR orchestration through planning and current authorization."""

from edi_reference.application.execution import ProviderRegistry, build_execution_plan
from edi_reference.application.planned_provider import invoke_planned_provider
from edi_reference.application.provider_config import ProviderConfigurationRegistry
from edi_reference.domain.execution import Capability, CapabilityRequest, ExecutionPolicy
from edi_reference.domain.invocation import InvocationLimits, InvocationResult
from edi_reference.application.invocation import ProviderInvoker


def execute_ocr_text_extraction(
    document_bytes: bytes,
    *,
    attempt_id: str,
    tenant_id: str,
    application_id: str,
    policy: ExecutionPolicy,
    providers: ProviderRegistry,
    configurations: ProviderConfigurationRegistry,
    limits: InvocationLimits,
    invokers: dict[str, ProviderInvoker],
) -> InvocationResult:
    """Plan and execute TEXT_EXTRACTION without bypassing current authorization."""
    plan = build_execution_plan(
        CapabilityRequest(frozenset({Capability.TEXT_EXTRACTION})),
        policy=policy,
        registry=providers,
    )
    step = plan.steps[0]
    provider = next(
        (item for item in providers.all() if item.provider_id == step.provider_id),
        None,
    )
    if provider is None:
        raise ValueError("PLANNED_PROVIDER_NOT_REGISTERED")
    invoker = invokers.get(step.provider_id)
    if invoker is None:
        raise ValueError("PROVIDER_INVOKER_NOT_REGISTERED")
    return invoke_planned_provider(
        step,
        attempt_id=attempt_id,
        input_bytes=document_bytes,
        provider=provider,
        configurations=configurations,
        tenant_id=tenant_id,
        application_id=application_id,
        policy=policy,
        limits=limits,
        invoker=invoker,
    )
