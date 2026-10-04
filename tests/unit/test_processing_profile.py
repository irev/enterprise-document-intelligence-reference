import pytest

from edi_reference.application.processing_profile import (
    ProcessingProfileError,
    ProcessingProfileRegistry,
)
from edi_reference.domain.execution import ExecutionClass, ExecutionPolicy
from edi_reference.domain.processing_profile import ProcessingProfile, ProcessingProfileBinding


def profile(profile_id: str, version: str = "1") -> ProcessingProfile:
    return ProcessingProfile(
        profile_id,
        version,
        ExecutionPolicy(
            f"{profile_id}-policy",
            version,
            frozenset({ExecutionClass.DETERMINISTIC, ExecutionClass.LOCAL_MODEL}),
            allow_external_egress=False,
        ),
    )


def test_application_binding_overrides_tenant_default():
    tenant_default = profile("tenant-default")
    app_specific = profile("app-specific")
    registry = ProcessingProfileRegistry(
        (tenant_default, app_specific),
        (
            ProcessingProfileBinding("tenant-1", None, "tenant-default", "1"),
            ProcessingProfileBinding("tenant-1", "app-1", "app-specific", "1"),
        ),
    )

    assert registry.resolve(tenant_id="tenant-1", application_id="app-1") == app_specific
    assert registry.resolve(tenant_id="tenant-1", application_id="app-2") == tenant_default


def test_profile_resolution_does_not_cross_tenant_boundary():
    registry = ProcessingProfileRegistry(
        (profile("tenant-one"),),
        (ProcessingProfileBinding("tenant-1", None, "tenant-one", "1"),),
    )

    with pytest.raises(ProcessingProfileError, match="PROCESSING_PROFILE_NOT_BOUND"):
        registry.resolve(tenant_id="tenant-2", application_id="app-1")


def test_binding_requires_registered_exact_profile_version():
    with pytest.raises(ProcessingProfileError, match="PROCESSING_PROFILE_NOT_FOUND"):
        ProcessingProfileRegistry(
            (profile("profile-a", "1"),),
            (ProcessingProfileBinding("tenant-1", None, "profile-a", "2"),),
        )


def test_duplicate_scope_binding_is_rejected():
    item = ProcessingProfileBinding("tenant-1", "app-1", "profile-a", "1")
    with pytest.raises(ProcessingProfileError, match="DUPLICATE_PROCESSING_PROFILE_BINDING"):
        ProcessingProfileRegistry((profile("profile-a"),), (item, item))
