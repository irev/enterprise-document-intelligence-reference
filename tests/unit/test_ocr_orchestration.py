import pytest

from edi_reference.application.execution import ProviderRegistry
from edi_reference.application.ocr_orchestration import execute_ocr_text_extraction
from edi_reference.application.provider_config import ProviderConfigurationError, ProviderConfigurationRegistry
from edi_reference.domain.execution import Capability, DataEgress, ExecutionClass, ExecutionPolicy, ProviderCapability
from edi_reference.domain.invocation import InvocationLimits, InvocationResult
from edi_reference.domain.provider_config import ProviderConfiguration


PROVIDER = ProviderCapability(
    "local-ocr", "1", ExecutionClass.OCR,
    frozenset({Capability.TEXT_EXTRACTION}), DataEgress.NONE,
)
POLICY = ExecutionPolicy("local-ocr-only", "1", frozenset({ExecutionClass.OCR}), False)
LIMITS = InvocationLimits(5, 1024, 1024)


class Invoker:
    def __init__(self):
        self.calls = 0

    def invoke(self, request, limits):
        self.calls += 1
        return InvocationResult(request.provider_id, request.provider_version, b"recognized")


def configuration(*, enabled=True):
    return ProviderConfiguration(
        "local-ocr", "cfg-1", enabled, "trusted-local", "paddle",
        tenant_allowlist=frozenset({"tenant-a"}),
        application_allowlist=frozenset({("tenant-a", "app-a")}),
    )


def execute(invoker, config):
    return execute_ocr_text_extraction(
        b"%PDF-synthetic",
        attempt_id="attempt-1", tenant_id="tenant-a", application_id="app-a",
        policy=POLICY, providers=ProviderRegistry((PROVIDER,)),
        configurations=ProviderConfigurationRegistry((config,)),
        limits=LIMITS, invokers={"local-ocr": invoker},
    )


def test_ocr_orchestration_plans_authorizes_then_invokes():
    invoker = Invoker()
    assert execute(invoker, configuration()).output_bytes == b"recognized"
    assert invoker.calls == 1


def test_ocr_orchestration_does_not_invoke_disabled_provider():
    invoker = Invoker()
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_DISABLED"):
        execute(invoker, configuration(enabled=False))
    assert invoker.calls == 0


def test_ocr_orchestration_requires_registered_invoker():
    with pytest.raises(ValueError, match="PROVIDER_INVOKER_NOT_REGISTERED"):
        execute_ocr_text_extraction(
            b"doc", attempt_id="attempt-1", tenant_id="tenant-a", application_id="app-a",
            policy=POLICY, providers=ProviderRegistry((PROVIDER,)),
            configurations=ProviderConfigurationRegistry((configuration(),)),
            limits=LIMITS, invokers={},
        )
