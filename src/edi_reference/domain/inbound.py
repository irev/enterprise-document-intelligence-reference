"""Durable inbound lifecycle vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class InboundStatus(StrEnum):
    RECEIVED = "RECEIVED"
    ACQUIRING = "ACQUIRING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class InboundRecord:
    inbound_id: str
    tenant_id: str
    application_id: str
    correlation_id: str
    request_id: str
    idempotency_key: str
    request_fingerprint: str
    source_method: str
    status: InboundStatus
    received_at: datetime
    updated_at: datetime
    observation_sha256: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingDispatch:
    dispatch_id: str
    inbound_id: str
    tenant_id: str
    application_id: str
    correlation_id: str
    observation_sha256: str
    created_at: datetime
