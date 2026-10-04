from datetime import UTC, datetime

from edi_reference.application.validation import ValidationPolicy, evaluate_validation
from edi_reference.domain.classification import ClassificationPrediction
from edi_reference.domain.processing_result import ProcessingResult
from edi_reference.domain.validation import (
    FindingSeverity,
    ValidationFinding,
    ValidationStatus,
)


class Rule:
    def __init__(self, *findings):
        self.findings = findings

    def evaluate(self, result):
        return self.findings


def result():
    return ProcessingResult(
        "result-1", "1", "run-1", "document-1", "tenant-1", "app-1",
        "observation-1", "a" * 64, "2.0",
        ClassificationPrediction("INVOICE", 0.9, "classifier", "1", "1", ()),
        (), datetime(2026, 10, 4, tzinfo=UTC),
    )


def finding(severity):
    return ValidationFinding("RULE_CODE", severity, "RULE_ENGINE", "1")


def test_no_findings_is_valid():
    validation = evaluate_validation(result(), ValidationPolicy("1", ()))
    assert validation.status is ValidationStatus.VALID


def test_info_findings_remain_valid():
    validation = evaluate_validation(
        result(), ValidationPolicy("1", (Rule(finding(FindingSeverity.INFO)),))
    )
    assert validation.status is ValidationStatus.VALID


def test_warning_or_error_requires_review():
    for severity in (FindingSeverity.WARNING, FindingSeverity.ERROR):
        validation = evaluate_validation(
            result(), ValidationPolicy("1", (Rule(finding(severity)),))
        )
        assert validation.status is ValidationStatus.REVIEW_REQUIRED


def test_blocking_finding_is_invalid():
    validation = evaluate_validation(
        result(), ValidationPolicy("1", (Rule(finding(FindingSeverity.BLOCKING)),))
    )
    assert validation.status is ValidationStatus.INVALID
