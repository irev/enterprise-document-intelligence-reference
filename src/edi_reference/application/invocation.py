"""Fail-closed provider invocation boundary."""

from typing import Protocol

from edi_reference.domain.execution import DataEgress, ExecutionPolicy, ProviderCapability
from edi_reference.domain.invocation import (
    InvocationFailureCode,
    InvocationLimits,
    InvocationRequest,
    InvocationResult,
)


class ProviderInvocationError(RuntimeError):
    def __init__(self, code: InvocationFailureCode):
        super().__init__(code.value)
        self.code = code


class ProviderInvoker(Protocol):
    def invoke(self, request: InvocationRequest, limits: InvocationLimits) -> InvocationResult: ...


def invoke_provider(
    request: InvocationRequest,
    *,
    provider: ProviderCapability,
    policy: ExecutionPolicy,
    limits: InvocationLimits,
    invoker: ProviderInvoker,
) -> InvocationResult:
    if request.provider_id != provider.provider_id or request.provider_version != provider.provider_version:
        raise ProviderInvocationError(InvocationFailureCode.INVALID_PROVIDER_RESPONSE)
    if request.execution_class is not provider.execution_class:
        raise ProviderInvocationError(InvocationFailureCode.INVALID_PROVIDER_RESPONSE)
    if request.capability not in provider.capabilities:
        raise ProviderInvocationError(InvocationFailureCode.INVALID_PROVIDER_RESPONSE)
    if provider.execution_class not in policy.allowed_execution_classes:
        raise ProviderInvocationError(InvocationFailureCode.EGRESS_NOT_ALLOWED)
    if provider.data_egress is not DataEgress.NONE and not policy.allow_external_egress:
        raise ProviderInvocationError(InvocationFailureCode.EGRESS_NOT_ALLOWED)
    if len(request.input_bytes) > limits.max_input_bytes:
        raise ProviderInvocationError(InvocationFailureCode.RESOURCE_LIMIT_EXCEEDED)

    try:
        result = invoker.invoke(request, limits)
    except ProviderInvocationError:
        raise
    except TimeoutError:
        raise ProviderInvocationError(InvocationFailureCode.PROVIDER_TIMEOUT) from None
    except Exception:
        raise ProviderInvocationError(InvocationFailureCode.PROVIDER_FAILED) from None

    if result.provider_id != provider.provider_id or result.provider_version != provider.provider_version:
        raise ProviderInvocationError(InvocationFailureCode.INVALID_PROVIDER_RESPONSE)
    if len(result.output_bytes) > limits.max_output_bytes:
        raise ProviderInvocationError(InvocationFailureCode.RESOURCE_LIMIT_EXCEEDED)
    return result
