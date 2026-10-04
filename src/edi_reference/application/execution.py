"""Deterministic provider registry and execution planner."""

from edi_reference.domain.execution import (
    Capability,
    CapabilityRequest,
    DataEgress,
    ExecutionPlan,
    ExecutionPolicy,
    PlannedStep,
    ProviderCapability,
)


class ExecutionPlanningError(ValueError):
    pass


class ProviderRegistry:
    def __init__(self, providers: tuple[ProviderCapability, ...]):
        self._providers: dict[str, ProviderCapability] = {}
        for provider in providers:
            if provider.provider_id in self._providers:
                raise ValueError("DUPLICATE_PROVIDER_ID")
            self._providers[provider.provider_id] = provider

    def all(self) -> tuple[ProviderCapability, ...]:
        return tuple(self._providers.values())


def build_execution_plan(
    request: CapabilityRequest,
    *,
    policy: ExecutionPolicy,
    registry: ProviderRegistry,
) -> ExecutionPlan:
    steps: list[PlannedStep] = []
    providers = registry.all()

    for capability in sorted(request.required, key=lambda item: item.value):
        eligible = [
            provider for provider in providers
            if capability in provider.capabilities
            and provider.execution_class in policy.allowed_execution_classes
            and (
                policy.allow_external_egress
                or provider.data_egress is DataEgress.NONE
            )
        ]
        if not eligible:
            raise ExecutionPlanningError(f"NO_ELIGIBLE_PROVIDER:{capability.value}")

        # Registry order is not policy. Stable lexical selection makes this
        # reference deterministic until an explicit preference policy is added.
        selected = sorted(eligible, key=lambda item: item.provider_id)[0]
        steps.append(PlannedStep(
            capability=capability,
            provider_id=selected.provider_id,
            provider_version=selected.provider_version,
            execution_class=selected.execution_class,
        ))

    return ExecutionPlan(policy.policy_id, policy.policy_version, tuple(steps))
