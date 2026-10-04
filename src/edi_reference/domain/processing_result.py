"""Immutable completed machine-result aggregate."""

from dataclasses import dataclass
from datetime import datetime

from edi_reference.domain.classification import ClassificationPrediction
from edi_reference.domain.normalization import NormalizedField


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """One immutable machine result produced by one processing run."""

    result_id: str
    result_version: str
    processing_run_id: str
    document_id: str
    tenant_id: str
    application_id: str
    observation_id: str
    observation_sha256: str
    schema_version: str
    classification: ClassificationPrediction
    fields: tuple[NormalizedField, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        identities = (
            self.result_id,
            self.result_version,
            self.processing_run_id,
            self.document_id,
            self.tenant_id,
            self.application_id,
            self.observation_id,
            self.schema_version,
        )
        if any(not value for value in identities):
            raise ValueError("PROCESSING_RESULT_IDENTITY_REQUIRED")
        if len(self.observation_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.observation_sha256
        ):
            raise ValueError("INVALID_PROCESSING_RESULT_DIGEST")

        field_names: set[str] = set()
        evidence = list(self.classification.evidence)
        for field in self.fields:
            if field.field_name in field_names:
                raise ValueError("DUPLICATE_RESULT_FIELD_NAME")
            field_names.add(field.field_name)
            evidence.extend(field.extracted.evidence)

        for reference in evidence:
            if reference.observation_id != self.observation_id:
                raise ValueError("RESULT_EVIDENCE_OBSERVATION_MISMATCH")
            if reference.observation_sha256.lower() != self.observation_sha256:
                raise ValueError("RESULT_EVIDENCE_DIGEST_MISMATCH")
