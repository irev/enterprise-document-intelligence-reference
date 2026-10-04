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


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    provider_id: str
    provider_version: str
    execution_class: ExecutionClass
    capabilities: frozenset[Capability]
    data_egress: DataEgress

    def __post_init__(self) -> None:
        if not self.provider_id or not self.provider_version or not self.capabilities:
            raise ValueError("INVALID_PROVIDER_CAPABILITY")


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    policy_id: str
    policy_version: str
    allowed_execution_classes: frozenset[ExecutionClass]
    allow_external_egress: bool
    allow_fallback: bool = False

    def __post_init__(self) -> None:
        if not self.policy_id or not self.policy_version or not self.allowed_execution_classes:
            raise ValueError("INVALID_EXECUTION_POLICY")


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    required: frozenset[Capability]


@dataclass(frozen=True, slots=True)
class PlannedStep:
    capability: Capability
    provider_id: str
    provider_version: str
    execution_class: ExecutionClass


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    policy_id: str
    policy_version: str
    steps: tuple[PlannedStep, ...]
