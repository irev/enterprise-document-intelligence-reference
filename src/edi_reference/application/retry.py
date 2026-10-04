"""Explicit retry/refetch orchestration over durable source lineage."""

from dataclasses import dataclass
from enum import StrEnum

from edi_reference.application.lineage import (
    ObservationRepository,
    ProcessingRunRepository,
    bind_processing_run,
    register_refetch,
    verify_reprocess_observation,
)
from edi_reference.domain.ingestion import Clock, IdGenerator
from edi_reference.domain.lineage import ProcessingRunBinding, RefetchOutcome, SourceObservation
from edi_reference.domain.source import ProcessingIntent


class RetryAction(StrEnum):
    NO_PROCESSING = "NO_PROCESSING"
    PROCESS_EXISTING = "PROCESS_EXISTING"
    PROCESS_REFETCHED = "PROCESS_REFETCHED"


@dataclass(frozen=True, slots=True)
class RetryResult:
    intent: ProcessingIntent
    action: RetryAction
    observation: SourceObservation
    refetch_outcome: RefetchOutcome | None = None
    processing_run: ProcessingRunBinding | None = None


def orchestrate_retry(
    *,
    intent: ProcessingIntent,
    current: SourceObservation,
    tenant_id: str,
    application_id: str,
    observation_repository: ObservationRepository,
    processing_repository: ProcessingRunRepository,
    clock: Clock,
    ids: IdGenerator,
    reacquired_sha256: str | None = None,
    byte_length: int | None = None,
    detected_media_type: str | None = None,
    external_version: str | None = None,
) -> RetryResult:
    if intent is ProcessingIntent.REPROCESS:
        if reacquired_sha256 is None:
            raise ValueError("REPROCESS_REQUIRES_DIGEST")
        verify_reprocess_observation(
            current, tenant_id=tenant_id, application_id=application_id,
            reacquired_sha256=reacquired_sha256,
        )
        run = bind_processing_run(
            current, tenant_id=tenant_id, application_id=application_id,
            repository=processing_repository, clock=clock, ids=ids,
        )
        return RetryResult(intent, RetryAction.PROCESS_EXISTING, current, processing_run=run)

    if reacquired_sha256 is None or byte_length is None or detected_media_type is None:
        raise ValueError("REFETCH_REQUIRES_ACQUIRED_SOURCE")

    outcome, observation = register_refetch(
        current, tenant_id=tenant_id, application_id=application_id,
        sha256=reacquired_sha256, byte_length=byte_length,
        detected_media_type=detected_media_type, external_version=external_version,
        repository=observation_repository, clock=clock, ids=ids,
    )

    if intent is ProcessingIntent.REFETCH:
        return RetryResult(intent, RetryAction.NO_PROCESSING, observation, outcome)

    if intent is ProcessingIntent.REFETCH_AND_REPROCESS:
        run = bind_processing_run(
            observation, tenant_id=tenant_id, application_id=application_id,
            repository=processing_repository, clock=clock, ids=ids,
        )
        return RetryResult(
            intent, RetryAction.PROCESS_REFETCHED, observation, outcome, run
        )

    raise ValueError("UNSUPPORTED_PROCESSING_INTENT")
