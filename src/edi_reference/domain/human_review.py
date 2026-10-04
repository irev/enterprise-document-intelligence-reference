"""Immutable human-review provenance linked to a machine result version."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ReviewActionType(StrEnum):
    CONFIRM = "CONFIRM"
    CORRECT = "CORRECT"
    MARK_NOT_PRESENT = "MARK_NOT_PRESENT"
    MARK_ILLEGIBLE = "MARK_ILLEGIBLE"
    RECLASSIFY = "RECLASSIFY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True, slots=True)
class ReviewAction:
    action: ReviewActionType
    field: str | None = None
    value: Any = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class HumanReview:
    review_id: str
    review_version: int
    result_id: str
    result_version: str
    actor_id: str
    actions: tuple[ReviewAction, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.review_id or not self.result_id or not self.result_version or not self.actor_id:
            raise ValueError("HUMAN_REVIEW_IDENTITY_REQUIRED")
        if self.review_version < 0:
            raise ValueError("HUMAN_REVIEW_VERSION_INVALID")
        if not self.actions:
            raise ValueError("HUMAN_REVIEW_ACTION_REQUIRED")
