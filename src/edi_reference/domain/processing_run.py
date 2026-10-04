"""Immutable processing-run execution snapshot."""

from dataclasses import dataclass

from edi_reference.domain.execution import ExecutionPlan
from edi_reference.domain.lineage import ProcessingRunBinding


@dataclass(frozen=True, slots=True)
class ProcessingRunExecutionSnapshot:
    """Resolved processing configuration frozen for one processing run."""

    binding: ProcessingRunBinding
    processing_profile_id: str
    processing_profile_version: str
    execution_plan: ExecutionPlan

    def __post_init__(self) -> None:
        if not self.processing_profile_id or not self.processing_profile_version:
            raise ValueError("PROCESSING_PROFILE_SNAPSHOT_REQUIRED")
        if not self.execution_plan.policy_id or not self.execution_plan.policy_version:
            raise ValueError("EXECUTION_POLICY_SNAPSHOT_REQUIRED")
        capabilities = [step.capability for step in self.execution_plan.steps]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("DUPLICATE_EXECUTION_PLAN_CAPABILITY")
