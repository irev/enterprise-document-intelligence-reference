import pytest

from edi_reference.application.execution import ExecutionPlanningError, ProviderRegistry, build_execution_plan, select_fallback_step
from edi_reference.domain.execution import (
    Capability, CapabilityExecutionPolicy, CapabilityRequest, DataEgress, ExecutionClass,
    ExecutionAttempt, ExecutionAttemptStatus, ExecutionPolicy, ProviderCapability, ProviderHealth,
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


def test_capability_preference_can_choose_local_before_remote():
    policy = ExecutionPolicy(
        "prefer-local", "1",
        frozenset({ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL}),
        True, True,
        (CapabilityExecutionPolicy(
            Capability.CLASSIFICATION,
            (ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL),
        ),),
    )
    plan = build_execution_plan(
        CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
        policy=policy,
        registry=ProviderRegistry((REMOTE, LOCAL)),
    )
    assert plan.steps[0].provider_id == "local-model-a"
    assert plan.steps[0].selection_reason == "CAPABILITY_POLICY_PREFERENCE"


def test_unavailable_preferred_provider_can_fall_to_next_allowed_class():
    unavailable_local = ProviderCapability(
        "local-model-down", "1", ExecutionClass.LOCAL_MODEL,
        frozenset({Capability.CLASSIFICATION}), DataEgress.NONE,
        ProviderHealth.UNAVAILABLE,
    )
    policy = ExecutionPolicy(
        "hybrid-fallback", "1",
        frozenset({ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL}),
        True, True,
        (CapabilityExecutionPolicy(
            Capability.CLASSIFICATION,
            (ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL),
        ),),
    )
    plan = build_execution_plan(
        CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
        policy=policy,
        registry=ProviderRegistry((unavailable_local, REMOTE)),
    )
    assert plan.steps[0].provider_id == "remote-model-a"


def test_local_only_policy_still_fails_when_local_provider_unavailable():
    unavailable_local = ProviderCapability(
        "local-model-down", "1", ExecutionClass.LOCAL_MODEL,
        frozenset({Capability.CLASSIFICATION}), DataEgress.NONE,
        ProviderHealth.UNAVAILABLE,
    )
    with pytest.raises(ExecutionPlanningError, match="NO_ELIGIBLE_PROVIDER:CLASSIFICATION"):
        build_execution_plan(
            CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
            policy=ExecutionPolicy("local-only", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False, True),
            registry=ProviderRegistry((unavailable_local, REMOTE)),
        )


def test_capability_preference_cannot_widen_allowed_execution_classes():
    with pytest.raises(ValueError, match="CAPABILITY_PREFERENCE_NOT_ALLOWED"):
        ExecutionPolicy(
            "bad", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False, True,
            (CapabilityExecutionPolicy(
                Capability.CLASSIFICATION,
                (ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL),
            ),),
        )


def test_runtime_fallback_requires_explicit_failed_attempt_and_policy():
    failed = ExecutionAttempt(
        "attempt-1", Capability.CLASSIFICATION, "local-model-a", "1",
        ExecutionClass.LOCAL_MODEL, ExecutionAttemptStatus.FAILED, "PROVIDER_FAILED",
    )
    policy = ExecutionPolicy(
        "hybrid", "1",
        frozenset({ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL}),
        True, True,
        (CapabilityExecutionPolicy(
            Capability.CLASSIFICATION,
            (ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL),
        ),),
    )
    step = select_fallback_step(
        failed_attempt=failed,
        request=CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
        policy=policy,
        registry=ProviderRegistry((LOCAL, REMOTE)),
    )
    assert step.provider_id == "remote-model-a"


def test_runtime_fallback_cannot_bypass_local_only_policy():
    failed = ExecutionAttempt(
        "attempt-1", Capability.CLASSIFICATION, "local-model-a", "1",
        ExecutionClass.LOCAL_MODEL, ExecutionAttemptStatus.FAILED, "PROVIDER_FAILED",
    )
    with pytest.raises(ExecutionPlanningError, match="NO_ELIGIBLE_PROVIDER"):
        select_fallback_step(
            failed_attempt=failed,
            request=CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
            policy=ExecutionPolicy(
                "local-only", "1", frozenset({ExecutionClass.LOCAL_MODEL}), False, True
            ),
            registry=ProviderRegistry((LOCAL, REMOTE)),
        )


def test_runtime_fallback_requires_policy_permission():
    failed = ExecutionAttempt(
        "attempt-1", Capability.CLASSIFICATION, "local-model-a", "1",
        ExecutionClass.LOCAL_MODEL, ExecutionAttemptStatus.FAILED, "PROVIDER_FAILED",
    )
    with pytest.raises(ExecutionPlanningError, match="FALLBACK_NOT_ALLOWED"):
        select_fallback_step(
            failed_attempt=failed,
            request=CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
            policy=ExecutionPolicy(
                "no-fallback", "1",
                frozenset({ExecutionClass.LOCAL_MODEL, ExecutionClass.REMOTE_MODEL}),
                True, False,
            ),
            registry=ProviderRegistry((LOCAL, REMOTE)),
        )
