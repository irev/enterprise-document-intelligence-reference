"""Durable source-acquisition lineage."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from edi_reference.domain.source import AcquisitionMethod


class AcquisitionStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    REJECTED = "REJECTED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SourceAcquisition:
    acquisition_id: str
    document_id: str
    tenant_id: str
    application_id: str
    method: AcquisitionMethod
    status: AcquisitionStatus
    acquired_at: datetime
    observation_id: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.status is AcquisitionStatus.ACQUIRED and not self.observation_id:
            raise ValueError("ACQUIRED_REQUIRES_OBSERVATION")
        if self.status is not AcquisitionStatus.ACQUIRED and self.observation_id is not None:
            raise ValueError("NON_ACQUIRED_CANNOT_REFERENCE_OBSERVATION")
