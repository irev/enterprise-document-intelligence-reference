"""Deterministic validation result vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class ValidationStatus(StrEnum):
    VALID = "VALID"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    code: str
    severity: FindingSeverity
    source: str
    rule_version: str | None = None
    message: str | None = None
    documents: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.code or not self.source:
            raise ValueError("VALIDATION_FINDING_IDENTITY_REQUIRED")


@dataclass(frozen=True, slots=True)
class ValidationResult:
    result_id: str
    result_version: str
    validation_version: str
    status: ValidationStatus
    findings: tuple[ValidationFinding, ...]

    def __post_init__(self) -> None:
        if not self.result_id or not self.result_version or not self.validation_version:
            raise ValueError("VALIDATION_RESULT_IDENTITY_REQUIRED")
