"""Resolve and freeze execution configuration for a processing run."""

from edi_reference.application.execution import ProviderRegistry, build_execution_plan
from edi_reference.application.processing_profile import ProcessingProfileRegistry
from edi_reference.domain.execution import CapabilityRequest
from edi_reference.domain.lineage import ProcessingRunBinding
from edi_reference.domain.processing_run import ProcessingRunExecutionSnapshot


def build_processing_run_execution_snapshot(
    binding: ProcessingRunBinding,
    *,
    profiles: ProcessingProfileRegistry,
    providers: ProviderRegistry,
    request: CapabilityRequest,
) -> ProcessingRunExecutionSnapshot:
    profile = profiles.resolve(
        tenant_id=binding.tenant_id,
        application_id=binding.application_id,
    )
    plan = build_execution_plan(
        request,
        policy=profile.execution_policy,
        registry=providers,
    )
    return ProcessingRunExecutionSnapshot(
        binding=binding,
        processing_profile_id=profile.profile_id,
        processing_profile_version=profile.profile_version,
        execution_plan=plan,
    )
