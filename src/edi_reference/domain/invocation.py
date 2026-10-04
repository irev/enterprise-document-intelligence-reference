"""Provider invocation boundary vocabulary."""

from dataclasses import dataclass
from enum import StrEnum

from edi_reference.domain.execution import Capability, ExecutionClass


class InvocationFailureCode(StrEnum):
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    INVALID_PROVIDER_RESPONSE = "INVALID_PROVIDER_RESPONSE"
    EGRESS_NOT_ALLOWED = "EGRESS_NOT_ALLOWED"
    PROVIDER_FAILED = "PROVIDER_FAILED"


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    timeout_seconds: int
    max_input_bytes: int
    max_output_bytes: int

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0 or self.max_input_bytes <= 0 or self.max_output_bytes <= 0:
            raise ValueError("INVALID_INVOCATION_LIMITS")


@dataclass(frozen=True, slots=True)
class InvocationRequest:
    attempt_id: str
    capability: Capability
    provider_id: str
    provider_version: str
    execution_class: ExecutionClass
    input_bytes: bytes

    def __post_init__(self) -> None:
        if not self.attempt_id or not self.provider_id or not self.provider_version:
            raise ValueError("INVALID_INVOCATION_REQUEST")


@dataclass(frozen=True, slots=True)
class InvocationResult:
    provider_id: str
    provider_version: str
    output_bytes: bytes
    media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        if not self.provider_id or not self.provider_version or not self.media_type:
            raise ValueError("INVALID_INVOCATION_RESULT")
