"""Durable source-observation and processing lineage."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RefetchOutcome(StrEnum):
    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"


@dataclass(frozen=True, slots=True)
class ScopedObservation:
    observation_id: str
    document_id: str
    tenant_id: str
    application_id: str
    sha256: str
    byte_length: int
    detected_media_type: str
    observed_at: datetime
    external_version: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingRunBinding:
    processing_run_id: str
    document_id: str
    tenant_id: str
    application_id: str
    observation_id: str
    observation_sha256: str
    created_at: datetime
