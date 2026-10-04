"""Transactional outbox vocabulary for durable processing dispatch."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    DEAD_LETTER = "DEAD_LETTER"


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    message_id: str
    tenant_id: str
    application_id: str
    correlation_id: str
    aggregate_id: str
    message_type: str
    payload_ref: str
    created_at: datetime
    observation_id: str | None = None
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    published_at: datetime | None = None
    last_error_code: str | None = None
