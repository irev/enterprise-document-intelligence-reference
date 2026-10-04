from datetime import UTC, datetime

import pytest

from edi_reference.adapters.lineage_memory import InMemoryObservationRepository, InMemoryProcessingRunRepository
from edi_reference.application.lineage import (
    ObservationAccessDenied,
    bind_processing_run,
    register_refetch,
    verify_reprocess_observation,
)
from edi_reference.domain.lineage import RefetchOutcome, ScopedObservation
from edi_reference.domain.source import SourceChangedError


class Clock:
    def now(self):
        return datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


class Ids:
    def __init__(self):
        self.n = 0
    def new_id(self):
        self.n += 1
        return f"id-{self.n}"


def observation(sha="a" * 64):
    return ScopedObservation(
        observation_id="obs-1", document_id="doc-1", tenant_id="tenant-a",
        application_id="app-a", sha256=sha, byte_length=10,
        detected_media_type="application/pdf", observed_at=Clock().now(),
    )


def test_processing_run_is_bound_to_observation():
    repo = InMemoryProcessingRunRepository()
    run = bind_processing_run(observation(), tenant_id="tenant-a", application_id="app-a",
                              repository=repo, clock=Clock(), ids=Ids())
    assert run.observation_id == "obs-1"
    assert run.observation_sha256 == "a" * 64


def test_cross_tenant_observation_access_is_denied():
    with pytest.raises(ObservationAccessDenied, match="OBSERVATION_ACCESS_DENIED"):
        bind_processing_run(observation(), tenant_id="tenant-b", application_id="app-a",
                            repository=InMemoryProcessingRunRepository(), clock=Clock(), ids=Ids())


def test_cross_application_observation_access_is_denied():
    with pytest.raises(ObservationAccessDenied):
        verify_reprocess_observation(observation(), tenant_id="tenant-a",
                                     application_id="app-b", reacquired_sha256="a" * 64)


def test_reprocess_changed_bytes_fails_explicitly():
    with pytest.raises(SourceChangedError, match="SOURCE_CHANGED"):
        verify_reprocess_observation(observation(), tenant_id="tenant-a",
                                     application_id="app-a", reacquired_sha256="b" * 64)


def test_refetch_same_digest_reuses_observation():
    repo = InMemoryObservationRepository()
    current = observation()
    repo.save(current)
    outcome, result = register_refetch(
        current, tenant_id="tenant-a", application_id="app-a",
        sha256="a" * 64, byte_length=10, detected_media_type="application/pdf",
        external_version="v2", repository=repo, clock=Clock(), ids=Ids(),
    )
    assert outcome is RefetchOutcome.UNCHANGED
    assert result is current
    assert len(repo.observations) == 1


def test_refetch_changed_digest_creates_new_observation():
    repo = InMemoryObservationRepository()
    current = observation()
    repo.save(current)
    outcome, result = register_refetch(
        current, tenant_id="tenant-a", application_id="app-a",
        sha256="b" * 64, byte_length=11, detected_media_type="application/pdf",
        external_version="v2", repository=repo, clock=Clock(), ids=Ids(),
    )
    assert outcome is RefetchOutcome.CHANGED
    assert result.observation_id != current.observation_id
    assert result.sha256 == "b" * 64
    assert len(repo.observations) == 2
