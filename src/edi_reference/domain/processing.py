"""Reliable processing-consumer vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ProcessingClaimStatus(StrEnum):
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ProcessingClaim:
    message_id: str
    processing_run_id: str
    tenant_id: str
    application_id: str
    observation_sha256: str
    status: ProcessingClaimStatus
    claimed_at: datetime
    lease_until: datetime
    completed_at: datetime | None = None
    failure_code: str | None = None
