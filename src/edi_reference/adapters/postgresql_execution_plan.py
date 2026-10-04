"""PostgreSQL persistence for immutable processing-run execution snapshots."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.execution import Capability, ExecutionClass, ExecutionPlan, PlannedStep
from edi_reference.domain.lineage import ProcessingRunBinding
from edi_reference.domain.processing_run import ProcessingRunExecutionSnapshot


class PostgreSqlExecutionPlanRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def save(self, snapshot: ProcessingRunExecutionSnapshot) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing.execution_plan
                       (processing_run_id, profile_id, profile_version,
                        policy_id, policy_version)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (
                        snapshot.binding.processing_run_id,
                        snapshot.processing_profile_id,
                        snapshot.processing_profile_version,
                        snapshot.execution_plan.policy_id,
                        snapshot.execution_plan.policy_version,
                    ),
                )
                for ordinal, step in enumerate(snapshot.execution_plan.steps):
                    cursor.execute(
                        """INSERT INTO processing.execution_plan_step
                           (processing_run_id, step_ordinal, capability, provider_id,
                            provider_version, execution_class, selection_reason)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            snapshot.binding.processing_run_id,
                            ordinal,
                            step.capability.value,
                            step.provider_id,
                            step.provider_version,
                            step.execution_class.value,
                            step.selection_reason,
                        ),
                    )

    def get(
        self,
        processing_run_id: str,
        *,
        binding: ProcessingRunBinding,
    ) -> ProcessingRunExecutionSnapshot | None:
        if binding.processing_run_id != processing_run_id:
            raise ValueError("PROCESSING_RUN_BINDING_MISMATCH")
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT profile_id, profile_version, policy_id, policy_version
                       FROM processing.execution_plan
                       WHERE processing_run_id=%s""",
                    (processing_run_id,),
                )
                root = cursor.fetchone()
                if root is None:
                    return None
                cursor.execute(
                    """SELECT capability, provider_id, provider_version,
                              execution_class, selection_reason
                       FROM processing.execution_plan_step
                       WHERE processing_run_id=%s
                       ORDER BY step_ordinal""",
                    (processing_run_id,),
                )
                steps = tuple(
                    PlannedStep(
                        Capability(row[0]),
                        row[1],
                        row[2],
                        ExecutionClass(row[3]),
                        row[4],
                    )
                    for row in cursor.fetchall()
                )
        return ProcessingRunExecutionSnapshot(
            binding,
            root[0],
            root[1],
            ExecutionPlan(root[2], root[3], steps),
        )
