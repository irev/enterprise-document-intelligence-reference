import pytest

from edi_reference.application.invocation import ProviderInvocationError, invoke_provider
from edi_reference.domain.execution import (
    Capability, DataEgress, ExecutionClass, ExecutionPolicy, ProviderCapability,
)
from edi_reference.domain.invocation import (
    InvocationFailureCode, InvocationLimits, InvocationRequest, InvocationResult,
)


LOCAL = ProviderCapability(
    "local-a", "1", ExecutionClass.LOCAL_MODEL,
    frozenset({Capability.CLASSIFICATION}), DataEgress.NONE,
)
REMOTE = ProviderCapability(
    "remote-a", "1", ExecutionClass.REMOTE_MODEL,
    frozenset({Capability.CLASSIFICATION}), DataEgress.APPROVED_EXTERNAL,
)
LIMITS = InvocationLimits(30, 1024, 1024)


class Invoker:
    def __init__(self, *, error=None, output=b"ok"):
        self.error = error
        self.output = output

    def invoke(self, request, limits):
        if self.error:
            raise self.error
        return InvocationResult(request.provider_id, request.provider_version, self.output)


def request(provider=LOCAL):
    return InvocationRequest(
        "attempt-1", Capability.CLASSIFICATION, provider.provider_id,
        provider.provider_version, provider.execution_class, b"document",
    )


def test_local_invocation_succeeds_without_external_egress():
    result = invoke_provider(
        request(), provider=LOCAL,
        policy=ExecutionPolicy("local", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False),
        limits=LIMITS, invoker=Invoker(),
    )
    assert result.output_bytes == b"ok"


def test_remote_invocation_is_blocked_before_adapter_when_egress_forbidden():
    with pytest.raises(ProviderInvocationError) as caught:
        invoke_provider(
            request(REMOTE), provider=REMOTE,
            policy=ExecutionPolicy("remote-disabled", "1", frozenset({ExecutionClass.REMOTE_MODEL}), False),
            limits=LIMITS, invoker=Invoker(),
        )
    assert caught.value.code is InvocationFailureCode.EGRESS_NOT_ALLOWED


def test_provider_exception_is_sanitized():
    with pytest.raises(ProviderInvocationError) as caught:
        invoke_provider(
            request(), provider=LOCAL,
            policy=ExecutionPolicy("local", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False),
            limits=LIMITS, invoker=Invoker(error=RuntimeError("secret provider detail")),
        )
    assert caught.value.code is InvocationFailureCode.PROVIDER_FAILED
    assert "secret provider detail" not in str(caught.value)


def test_timeout_has_stable_failure_code():
    with pytest.raises(ProviderInvocationError) as caught:
        invoke_provider(
            request(), provider=LOCAL,
            policy=ExecutionPolicy("local", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False),
            limits=LIMITS, invoker=Invoker(error=TimeoutError()),
        )
    assert caught.value.code is InvocationFailureCode.PROVIDER_TIMEOUT


def test_input_and_output_limits_are_enforced():
    policy = ExecutionPolicy("local", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False)
    too_large = InvocationRequest(
        "attempt-1", Capability.CLASSIFICATION, "local-a", "1",
        ExecutionClass.LOCAL_MODEL, b"x" * 1025,
    )
    with pytest.raises(ProviderInvocationError) as caught:
        invoke_provider(too_large, provider=LOCAL, policy=policy, limits=LIMITS, invoker=Invoker())
    assert caught.value.code is InvocationFailureCode.RESOURCE_LIMIT_EXCEEDED

    with pytest.raises(ProviderInvocationError) as caught:
        invoke_provider(
            request(), provider=LOCAL, policy=policy, limits=LIMITS,
            invoker=Invoker(output=b"x" * 1025),
        )
    assert caught.value.code is InvocationFailureCode.RESOURCE_LIMIT_EXCEEDED
