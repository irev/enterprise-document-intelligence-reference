"""Source observation lineage and retry/refetch semantics."""

from typing import Protocol

from edi_reference.domain.ingestion import Clock, IdGenerator
from edi_reference.domain.lineage import ProcessingRunBinding, RefetchOutcome, SourceObservation
from edi_reference.domain.source import SourceChangedError


class ObservationAccessDenied(PermissionError):
    pass


class ObservationRepository(Protocol):
    def get(self, observation_id: str) -> SourceObservation | None: ...
    def save(self, observation: SourceObservation) -> None: ...
    def find_by_scope_document_digest(
        self, tenant_id: str, application_id: str, document_id: str, sha256: str
    ) -> SourceObservation | None: ...


class ProcessingRunRepository(Protocol):
    def save(self, binding: ProcessingRunBinding) -> None: ...


def require_observation_scope(
    observation: SourceObservation, *, tenant_id: str, application_id: str
) -> None:
    if observation.tenant_id != tenant_id or observation.application_id != application_id:
        raise ObservationAccessDenied("OBSERVATION_ACCESS_DENIED")


def bind_processing_run(
    observation: SourceObservation,
    *,
    tenant_id: str,
    application_id: str,
    repository: ProcessingRunRepository,
    clock: Clock,
    ids: IdGenerator,
) -> ProcessingRunBinding:
    require_observation_scope(observation, tenant_id=tenant_id, application_id=application_id)
    binding = ProcessingRunBinding(
        processing_run_id=ids.new_id(),
        document_id=observation.document_id,
        tenant_id=tenant_id,
        application_id=application_id,
        observation_id=observation.observation_id,
        observation_sha256=observation.sha256,
        created_at=clock.now(),
    )
    repository.save(binding)
    return binding


def verify_reprocess_observation(
    observation: SourceObservation,
    *,
    tenant_id: str,
    application_id: str,
    reacquired_sha256: str,
) -> None:
    require_observation_scope(observation, tenant_id=tenant_id, application_id=application_id)
    if observation.sha256.lower() != reacquired_sha256.lower():
        raise SourceChangedError("SOURCE_CHANGED")


def register_refetch(
    current: SourceObservation,
    *,
    tenant_id: str,
    application_id: str,
    sha256: str,
    byte_length: int,
    detected_media_type: str,
    external_version: str | None,
    repository: ObservationRepository,
    clock: Clock,
    ids: IdGenerator,
) -> tuple[RefetchOutcome, SourceObservation]:
    require_observation_scope(current, tenant_id=tenant_id, application_id=application_id)
    if current.sha256.lower() == sha256.lower():
        return RefetchOutcome.UNCHANGED, current

    existing = repository.find_by_scope_document_digest(
        tenant_id, application_id, current.document_id, sha256.lower()
    )
    if existing is not None:
        return RefetchOutcome.CHANGED, existing

    observation = SourceObservation(
        observation_id=ids.new_id(),
        document_id=current.document_id,
        tenant_id=tenant_id,
        application_id=application_id,
        sha256=sha256.lower(),
        byte_length=byte_length,
        detected_media_type=detected_media_type,
        observed_at=clock.now(),
        external_version=external_version,
    )
    repository.save(observation)
    return RefetchOutcome.CHANGED, observation
