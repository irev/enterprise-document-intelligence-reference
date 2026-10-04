"""Small RI-0 domain vocabulary.

These types intentionally model observable platform state only. They do not
model payment approval, accounting posting, or customer workflow authority.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class Capability(StrEnum):
    CORE = "CORE"
    REVIEW = "REVIEW"
    BUNDLE = "BUNDLE"
    POLICY = "POLICY"
    EVENTS = "EVENTS"
    SEGMENTATION = "SEGMENTATION"
    DATASET = "DATASET"
    API = "API"


class ProcessingStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class ConformanceStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class ObservableResult:
    """Provider-neutral output exposed to conformance evaluation."""

    status: ProcessingStatus
    payload: Mapping[str, Any]
