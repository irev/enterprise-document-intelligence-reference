"""Source acquisition and observation domain model."""

from dataclasses import dataclass
from enum import StrEnum


class AcquisitionMethod(StrEnum):
    UPLOAD = "UPLOAD"
    SIGNED_URL = "SIGNED_URL"
    CONNECTOR = "CONNECTOR"


class ProcessingIntent(StrEnum):
    REPROCESS = "REPROCESS"
    REFETCH = "REFETCH"
    REFETCH_AND_REPROCESS = "REFETCH_AND_REPROCESS"


@dataclass(frozen=True, slots=True)
class SourceReference:
    method: AcquisitionMethod
    resource_locator: str | None = None
    connector_id: str | None = None
    external_version: str | None = None
    expected_sha256: str | None = None


class SourceChangedError(ValueError):
    """Reacquired bytes do not match the targeted observation."""


def verify_reprocess_source(*, expected_sha256: str, actual_sha256: str) -> None:
    if expected_sha256.lower() != actual_sha256.lower():
        raise SourceChangedError("SOURCE_CHANGED")
