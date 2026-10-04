import pytest

from edi_reference.application.planned_provider import authorize_planned_provider, invoke_planned_provider
from edi_reference.application.provider_config import ProviderConfigurationError, ProviderConfigurationRegistry
from edi_reference.domain.execution import Capability, DataEgress, ExecutionClass, ExecutionPolicy, PlannedStep, ProviderCapability
from edi_reference.domain.invocation import InvocationLimits, InvocationResult
from edi_reference.domain.provider_config import ProviderConfiguration


PROVIDER = ProviderCapability(
    "local-model", "1", ExecutionClass.LOCAL_MODEL,
    frozenset({Capability.CLASSIFICATION}), DataEgress.NONE,
)
STEP = PlannedStep(
    Capability.CLASSIFICATION, "local-model", "1",
    ExecutionClass.LOCAL_MODEL, "TEST",
)


def config(**changes):
    values = dict(
        provider_id="local-model", config_version="1", enabled=True,
        deployment_zone="trusted-local", engine_ref="model",
    )
    values.update(changes)
    return ProviderConfiguration(**values)


def test_planned_provider_must_resolve_for_tenant_and_application():
    result = authorize_planned_provider(
        STEP, provider=PROVIDER,
        configurations=ProviderConfigurationRegistry((config(
            tenant_allowlist=frozenset({"tenant-a"}),
            application_allowlist=frozenset({"app-a"}),
        ),)),
        tenant_id="tenant-a", application_id="app-a",
    )
    assert result.capability is PROVIDER


def test_disabled_provider_cannot_execute_stale_plan():
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_DISABLED"):
        authorize_planned_provider(
            STEP, provider=PROVIDER,
            configurations=ProviderConfigurationRegistry((config(enabled=False),)),
            tenant_id="tenant-a", application_id="app-a",
        )


def test_provider_removed_from_tenant_allowlist_cannot_execute_stale_plan():
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_NOT_ALLOWED_FOR_TENANT"):
        authorize_planned_provider(
            STEP, provider=PROVIDER,
            configurations=ProviderConfigurationRegistry((config(
                tenant_allowlist=frozenset({"tenant-b"}),
            ),)),
            tenant_id="tenant-a", application_id="app-a",
        )


def test_plan_and_provider_identity_must_match():
    stale = PlannedStep(
        Capability.CLASSIFICATION, "local-model", "old",
        ExecutionClass.LOCAL_MODEL, "TEST",
    )
    with pytest.raises(ValueError, match="PLANNED_PROVIDER_VERSION_MISMATCH"):
        authorize_planned_provider(
            stale, provider=PROVIDER,
            configurations=ProviderConfigurationRegistry((config(),)),
            tenant_id="tenant-a", application_id="app-a",
        )



class Invoker:
    def __init__(self):
        self.called = False

    def invoke(self, request, limits):
        self.called = True
        return InvocationResult(request.provider_id, request.provider_version, b"ok")


def test_planned_invocation_authorizes_before_calling_provider():
    invoker = Invoker()
    result = invoke_planned_provider(
        STEP, attempt_id="attempt-1", input_bytes=b"document",
        provider=PROVIDER,
        configurations=ProviderConfigurationRegistry((config(
            tenant_allowlist=frozenset({"tenant-a"}),
            application_allowlist=frozenset({"app-a"}),
        ),)),
        tenant_id="tenant-a", application_id="app-a",
        policy=ExecutionPolicy("local", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False),
        limits=InvocationLimits(10, 1024, 1024),
        invoker=invoker,
    )
    assert result.output_bytes == b"ok"
    assert invoker.called


def test_disabled_provider_is_blocked_before_invocation():
    invoker = Invoker()
    with pytest.raises(ProviderConfigurationError, match="PROVIDER_DISABLED"):
        invoke_planned_provider(
            STEP, attempt_id="attempt-1", input_bytes=b"document",
            provider=PROVIDER,
            configurations=ProviderConfigurationRegistry((config(enabled=False),)),
            tenant_id="tenant-a", application_id="app-a",
            policy=ExecutionPolicy("local", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False),
            limits=InvocationLimits(10, 1024, 1024),
            invoker=invoker,
        )
    assert not invoker.called
