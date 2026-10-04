"""Deterministic validation evaluation primitives."""

from dataclasses import dataclass
from typing import Protocol

from edi_reference.domain.processing_result import ProcessingResult
from edi_reference.domain.validation import (
    FindingSeverity,
    ValidationFinding,
    ValidationResult,
    ValidationStatus,
)


class ValidationRule(Protocol):
    def evaluate(self, result: ProcessingResult) -> tuple[ValidationFinding, ...]: ...


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    validation_version: str
    rules: tuple[ValidationRule, ...]

    def __post_init__(self) -> None:
        if not self.validation_version:
            raise ValueError("VALIDATION_VERSION_REQUIRED")


def evaluate_validation(
    result: ProcessingResult,
    policy: ValidationPolicy,
) -> ValidationResult:
    findings = tuple(
        finding
        for rule in policy.rules
        for finding in rule.evaluate(result)
    )
    status = _status_for(findings)
    return ValidationResult(
        result.result_id,
        result.result_version,
        policy.validation_version,
        status,
        findings,
    )


def _status_for(findings: tuple[ValidationFinding, ...]) -> ValidationStatus:
    severities = {finding.severity for finding in findings}
    if FindingSeverity.BLOCKING in severities:
        return ValidationStatus.INVALID
    if FindingSeverity.ERROR in severities or FindingSeverity.WARNING in severities:
        return ValidationStatus.REVIEW_REQUIRED
    return ValidationStatus.VALID
