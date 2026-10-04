import pytest

from edi_reference.application.execution import ExecutionPlanningError, ProviderRegistry, build_execution_plan
from edi_reference.domain.execution import (
    Capability, CapabilityRequest, DataEgress, ExecutionClass,
    ExecutionPolicy, ProviderCapability,
)


LOCAL = ProviderCapability(
    "local-model-a", "1", ExecutionClass.LOCAL_MODEL,
    frozenset({Capability.CLASSIFICATION, Capability.FIELD_EXTRACTION}),
    DataEgress.NONE,
)
REMOTE = ProviderCapability(
    "remote-model-a", "1", ExecutionClass.REMOTE_MODEL,
    frozenset({Capability.CLASSIFICATION, Capability.FIELD_EXTRACTION}),
    DataEgress.APPROVED_EXTERNAL,
)
OCR = ProviderCapability(
    "local-ocr", "1", ExecutionClass.OCR,
    frozenset({Capability.TEXT_EXTRACTION}), DataEgress.NONE,
)


def test_local_only_policy_never_selects_remote_provider():
    plan = build_execution_plan(
        CapabilityRequest(frozenset({Capability.CLASSIFICATION, Capability.FIELD_EXTRACTION})),
        policy=ExecutionPolicy("local-only", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False),
        registry=ProviderRegistry((REMOTE, LOCAL)),
    )
    assert {step.provider_id for step in plan.steps} == {"local-model-a"}


def test_no_local_provider_fails_closed_instead_of_cloud_fallback():
    with pytest.raises(ExecutionPlanningError, match="NO_ELIGIBLE_PROVIDER:CLASSIFICATION"):
        build_execution_plan(
            CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
            policy=ExecutionPolicy("local-only", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False, True),
            registry=ProviderRegistry((REMOTE,)),
        )


def test_external_egress_requires_explicit_permission():
    with pytest.raises(ExecutionPlanningError):
        build_execution_plan(
            CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
            policy=ExecutionPolicy("remote-class", "1", frozenset({ExecutionClass.REMOTE_MODEL}), False),
            registry=ProviderRegistry((REMOTE,)),
        )


def test_capabilities_can_use_different_execution_classes():
    plan = build_execution_plan(
        CapabilityRequest(frozenset({Capability.TEXT_EXTRACTION, Capability.CLASSIFICATION})),
        policy=ExecutionPolicy(
            "hybrid", "1",
            frozenset({ExecutionClass.OCR, ExecutionClass.LOCAL_MODEL}),
            False,
        ),
        registry=ProviderRegistry((OCR, LOCAL)),
    )
    assert {(step.capability, step.execution_class) for step in plan.steps} == {
        (Capability.TEXT_EXTRACTION, ExecutionClass.OCR),
        (Capability.CLASSIFICATION, ExecutionClass.LOCAL_MODEL),
    }
