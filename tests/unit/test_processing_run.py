from datetime import UTC, datetime

import pytest

from edi_reference.application.execution import ProviderRegistry
from edi_reference.application.processing_profile import ProcessingProfileRegistry
from edi_reference.application.processing_run import build_processing_run_execution_snapshot
from edi_reference.domain.execution import (
    Capability,
    CapabilityRequest,
    DataEgress,
    ExecutionClass,
    ExecutionPolicy,
    ProviderCapability,
)
from edi_reference.domain.lineage import ProcessingRunBinding
from edi_reference.domain.processing_profile import ProcessingProfile, ProcessingProfileBinding
from edi_reference.domain.processing_run import ProcessingRunExecutionSnapshot


def binding(*, tenant_id="tenant-1", application_id="app-1"):
    return ProcessingRunBinding(
        "run-1",
        "doc-1",
        tenant_id,
        application_id,
        "obs-1",
        "a" * 64,
        datetime(2026, 10, 4, tzinfo=UTC),
    )


def profile(profile_id: str, policy_id: str) -> ProcessingProfile:
    return ProcessingProfile(
        profile_id,
        "3",
        ExecutionPolicy(
            policy_id,
            "7",
            frozenset({ExecutionClass.LOCAL_MODEL}),
            allow_external_egress=False,
        ),
    )


PROVIDERS = ProviderRegistry(
    (
        ProviderCapability(
            "local-model",
            "11",
            ExecutionClass.LOCAL_MODEL,
            frozenset({Capability.CLASSIFICATION, Capability.FIELD_EXTRACTION}),
            DataEgress.NONE,
        ),
    )
)


def test_run_snapshot_freezes_resolved_profile_policy_and_provider_versions():
    selected = profile("profile-a", "policy-a")
    profiles = ProcessingProfileRegistry(
        (selected,),
        (ProcessingProfileBinding("tenant-1", None, "profile-a", "3"),),
    )

    snapshot = build_processing_run_execution_snapshot(
        binding(),
        profiles=profiles,
        providers=PROVIDERS,
        request=CapabilityRequest(
            frozenset({Capability.CLASSIFICATION, Capability.FIELD_EXTRACTION})
        ),
    )

    assert snapshot.processing_profile_id == "profile-a"
    assert snapshot.processing_profile_version == "3"
    assert snapshot.execution_plan.policy_id == "policy-a"
    assert snapshot.execution_plan.policy_version == "7"
    assert {step.provider_version for step in snapshot.execution_plan.steps} == {"11"}
    assert snapshot.binding.processing_run_id == "run-1"


def test_application_profile_override_is_frozen_for_that_run():
    tenant_default = profile("tenant-default", "policy-default")
    app_specific = profile("app-specific", "policy-app")
    profiles = ProcessingProfileRegistry(
        (tenant_default, app_specific),
        (
            ProcessingProfileBinding("tenant-1", None, "tenant-default", "3"),
            ProcessingProfileBinding("tenant-1", "app-1", "app-specific", "3"),
        ),
    )

    snapshot = build_processing_run_execution_snapshot(
        binding(),
        profiles=profiles,
        providers=PROVIDERS,
        request=CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
    )

    assert snapshot.processing_profile_id == "app-specific"
    assert snapshot.execution_plan.policy_id == "policy-app"


def test_unbound_run_scope_fails_closed():
    profiles = ProcessingProfileRegistry(
        (profile("tenant-one", "policy-one"),),
        (ProcessingProfileBinding("tenant-1", None, "tenant-one", "3"),),
    )

    with pytest.raises(ValueError, match="PROCESSING_PROFILE_NOT_BOUND"):
        build_processing_run_execution_snapshot(
            binding(tenant_id="tenant-2"),
            profiles=profiles,
            providers=PROVIDERS,
            request=CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
        )


def test_snapshot_rejects_duplicate_capability_steps():
    base = build_processing_run_execution_snapshot(
        binding(),
        profiles=ProcessingProfileRegistry(
            (profile("profile-a", "policy-a"),),
            (ProcessingProfileBinding("tenant-1", None, "profile-a", "3"),),
        ),
        providers=PROVIDERS,
        request=CapabilityRequest(frozenset({Capability.CLASSIFICATION})),
    )
    step = base.execution_plan.steps[0]
    with pytest.raises(ValueError, match="DUPLICATE_EXECUTION_PLAN_CAPABILITY"):
        ProcessingRunExecutionSnapshot(
            base.binding,
            base.processing_profile_id,
            base.processing_profile_version,
            type(base.execution_plan)(
                base.execution_plan.policy_id,
                base.execution_plan.policy_version,
                (step, step),
            ),
        )
