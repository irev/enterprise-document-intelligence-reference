"""Deterministic provider registry and execution planner."""

from edi_reference.domain.execution import (
    Capability,
    CapabilityRequest,
    DataEgress,
    ProviderHealth,
    ExecutionPlan,
    ExecutionAttempt,
    ExecutionAttemptStatus,
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
            and provider.health is not ProviderHealth.UNAVAILABLE
            and (
                policy.allow_external_egress
                or provider.data_egress is DataEgress.NONE
            )
        ]
        if not eligible:
            raise ExecutionPlanningError(f"NO_ELIGIBLE_PROVIDER:{capability.value}")

        capability_policy = next(
            (item for item in policy.capability_policies if item.capability is capability),
            None,
        )
        if capability_policy is not None:
            rank = {execution_class: index for index, execution_class in enumerate(capability_policy.preference)}
            preferred = [provider for provider in eligible if provider.execution_class in rank]
            if not preferred:
                raise ExecutionPlanningError(f"NO_PREFERRED_PROVIDER:{capability.value}")
            selected = sorted(
                preferred,
                key=lambda item: (
                    rank[item.execution_class],
                    item.health is ProviderHealth.DEGRADED,
                    item.provider_id,
                ),
            )[0]
            selection_reason = "CAPABILITY_POLICY_PREFERENCE"
        else:
            selected = sorted(
                eligible,
                key=lambda item: (item.health is ProviderHealth.DEGRADED, item.provider_id),
            )[0]
            selection_reason = "DETERMINISTIC_ELIGIBLE_PROVIDER"

        steps.append(PlannedStep(
            capability=capability,
            provider_id=selected.provider_id,
            provider_version=selected.provider_version,
            execution_class=selected.execution_class,
            selection_reason=selection_reason,
        ))

    return ExecutionPlan(policy.policy_id, policy.policy_version, tuple(steps))



def select_fallback_step(
    *,
    failed_attempt: ExecutionAttempt,
    request: CapabilityRequest,
    policy: ExecutionPolicy,
    registry: ProviderRegistry,
) -> PlannedStep:
    """Select a policy-authorized fallback after an explicit failed attempt.

    This never widens execution classes or egress permissions. The failed
    provider is excluded so a retry of the same provider is a separate concern.
    """
    if failed_attempt.status is not ExecutionAttemptStatus.FAILED:
        raise ExecutionPlanningError("FALLBACK_REQUIRES_FAILED_ATTEMPT")
    if not policy.allow_fallback:
        raise ExecutionPlanningError("FALLBACK_NOT_ALLOWED")
    if failed_attempt.capability not in request.required:
        raise ExecutionPlanningError("CAPABILITY_NOT_REQUESTED")

    providers = tuple(
        provider for provider in registry.all()
        if provider.provider_id != failed_attempt.provider_id
    )
    plan = build_execution_plan(
        CapabilityRequest(frozenset({failed_attempt.capability})),
        policy=policy,
        registry=ProviderRegistry(providers),
    )
    return plan.steps[0]
