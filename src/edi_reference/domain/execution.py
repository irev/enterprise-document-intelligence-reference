"""Provider-neutral execution policy vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    TEXT_EXTRACTION = "TEXT_EXTRACTION"
    LAYOUT = "LAYOUT"
    CLASSIFICATION = "CLASSIFICATION"
    FIELD_EXTRACTION = "FIELD_EXTRACTION"
    VALIDATION = "VALIDATION"


class ExecutionClass(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    OCR = "OCR"
    LOCAL_MODEL = "LOCAL_MODEL"
    REMOTE_MODEL = "REMOTE_MODEL"
    HUMAN = "HUMAN"


class DataEgress(StrEnum):
    NONE = "NONE"
    APPROVED_EXTERNAL = "APPROVED_EXTERNAL"


class ProviderHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    provider_id: str
    provider_version: str
    execution_class: ExecutionClass
    capabilities: frozenset[Capability]
    data_egress: DataEgress
    health: ProviderHealth = ProviderHealth.HEALTHY

    def __post_init__(self) -> None:
        if not self.provider_id or not self.provider_version or not self.capabilities:
            raise ValueError("INVALID_PROVIDER_CAPABILITY")


@dataclass(frozen=True, slots=True)
class CapabilityExecutionPolicy:
    capability: Capability
    preference: tuple[ExecutionClass, ...]

    def __post_init__(self) -> None:
        if not self.preference or len(set(self.preference)) != len(self.preference):
            raise ValueError("INVALID_CAPABILITY_PREFERENCE")


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    policy_id: str
    policy_version: str
    allowed_execution_classes: frozenset[ExecutionClass]
    allow_external_egress: bool
    allow_fallback: bool = False
    capability_policies: tuple[CapabilityExecutionPolicy, ...] = ()

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_version or not self.allowed_execution_classes:
            raise ValueError("INVALID_EXECUTION_POLICY")
        capabilities = [item.capability for item in self.capability_policies]
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("DUPLICATE_CAPABILITY_POLICY")
        for item in self.capability_policies:
            if any(value not in self.allowed_execution_classes for value in item.preference):
                raise ValueError("CAPABILITY_PREFERENCE_NOT_ALLOWED")


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    required: frozenset[Capability]


@dataclass(frozen=True, slots=True)
class PlannedStep:
    capability: Capability
    provider_id: str
    provider_version: str
    execution_class: ExecutionClass
    selection_reason: str


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    policy_id: str
    policy_version: str
    steps: tuple[PlannedStep, ...]


class ExecutionAttemptStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    attempt_id: str
    capability: Capability
    provider_id: str
    provider_version: str
    execution_class: ExecutionClass
    status: ExecutionAttemptStatus
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.status is ExecutionAttemptStatus.SUCCEEDED and self.failure_code is not None:
            raise ValueError("SUCCESS_CANNOT_HAVE_FAILURE_CODE")
        if self.status is ExecutionAttemptStatus.FAILED and not self.failure_code:
            raise ValueError("FAILED_ATTEMPT_REQUIRES_FAILURE_CODE")
