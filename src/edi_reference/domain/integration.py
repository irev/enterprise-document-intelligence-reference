"""Shared-service identity and delivery vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping


@dataclass(frozen=True, slots=True)
class InteractionContext:
    tenant_id: str
    application_id: str
    correlation_id: str
    request_id: str | None = None
    idempotency_key: str | None = None
    external_references: Mapping[str, str] | None = None


class DeliveryStatus(StrEnum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRY_PENDING = "RETRY_PENDING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    delivery_id: str
    message_id: str
    subscription_id: str
    tenant_id: str
    application_id: str
    correlation_id: str
    document_id: str
    result_version: str
    attempt: int
    attempted_at: datetime
    status: DeliveryStatus
    response_status: int | None = None
    next_attempt_at: datetime | None = None
    failure_code: str | None = None
