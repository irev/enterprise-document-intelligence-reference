from datetime import UTC, datetime

import pytest

from edi_reference.adapters.lineage_memory import (
    InMemoryObservationRepository, InMemoryProcessingRunRepository,
)
from edi_reference.application.retry import RetryAction, orchestrate_retry
from edi_reference.domain.lineage import RefetchOutcome, ScopedObservation
from edi_reference.domain.source import ProcessingIntent, SourceChangedError


class Clock:
    def now(self):
        return datetime(2026, 10, 4, 14, 30, tzinfo=UTC)


class Ids:
    def __init__(self):
        self.n = 0
    def new_id(self):
        self.n += 1
        return f"id-{self.n}"


def current():
    return ScopedObservation(
        "obs-1", "doc-1", "tenant-a", "app-a", "a" * 64, 10,
        "application/pdf", Clock().now(),
    )


def repos():
    observations = InMemoryObservationRepository()
    observations.save(current())
    return observations, InMemoryProcessingRunRepository()


def test_reprocess_requires_exact_target_digest_and_creates_run():
    observations, runs = repos()
    result = orchestrate_retry(
        intent=ProcessingIntent.REPROCESS, current=current(),
        tenant_id="tenant-a", application_id="app-a",
        observation_repository=observations, processing_repository=runs,
        clock=Clock(), ids=Ids(), reacquired_sha256="a" * 64,
    )
    assert result.action is RetryAction.PROCESS_EXISTING
    assert result.processing_run.observation_id == "obs-1"


def test_reprocess_changed_source_fails_closed():
    observations, runs = repos()
    with pytest.raises(SourceChangedError, match="SOURCE_CHANGED"):
        orchestrate_retry(
            intent=ProcessingIntent.REPROCESS, current=current(),
            tenant_id="tenant-a", application_id="app-a",
            observation_repository=observations, processing_repository=runs,
            clock=Clock(), ids=Ids(), reacquired_sha256="b" * 64,
        )


def test_refetch_same_bytes_records_no_processing():
    observations, runs = repos()
    result = orchestrate_retry(
        intent=ProcessingIntent.REFETCH, current=current(),
        tenant_id="tenant-a", application_id="app-a",
        observation_repository=observations, processing_repository=runs,
        clock=Clock(), ids=Ids(), reacquired_sha256="a" * 64,
        byte_length=10, detected_media_type="application/pdf",
    )
    assert result.refetch_outcome is RefetchOutcome.UNCHANGED
    assert result.action is RetryAction.NO_PROCESSING
    assert result.processing_run is None


def test_refetch_changed_bytes_creates_observation_but_not_run():
    observations, runs = repos()
    result = orchestrate_retry(
        intent=ProcessingIntent.REFETCH, current=current(),
        tenant_id="tenant-a", application_id="app-a",
        observation_repository=observations, processing_repository=runs,
        clock=Clock(), ids=Ids(), reacquired_sha256="b" * 64,
        byte_length=11, detected_media_type="application/pdf",
    )
    assert result.refetch_outcome is RefetchOutcome.CHANGED
    assert result.observation.observation_id != "obs-1"
    assert not runs.bindings


def test_refetch_and_reprocess_processes_resulting_observation():
    observations, runs = repos()
    result = orchestrate_retry(
        intent=ProcessingIntent.REFETCH_AND_REPROCESS, current=current(),
        tenant_id="tenant-a", application_id="app-a",
        observation_repository=observations, processing_repository=runs,
        clock=Clock(), ids=Ids(), reacquired_sha256="b" * 64,
        byte_length=11, detected_media_type="application/pdf",
    )
    assert result.action is RetryAction.PROCESS_REFETCHED
    assert result.processing_run.observation_id == result.observation.observation_id
