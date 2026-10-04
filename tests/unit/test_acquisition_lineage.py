from datetime import UTC, datetime

import pytest

from edi_reference.adapters.acquisition_lineage_memory import InMemorySourceAcquisitionRepository
from edi_reference.application.acquisition_lineage import record_acquisition
from edi_reference.domain.acquisition_lineage import AcquisitionStatus, SourceAcquisition
from edi_reference.domain.source import AcquisitionMethod


NOW = datetime(2026, 10, 4, 14, 0, tzinfo=UTC)


def acquired(acquisition_id="acq-1", observation_id="obs-1"):
    return SourceAcquisition(
        acquisition_id=acquisition_id, document_id="doc-1",
        tenant_id="tenant-a", application_id="app-a",
        method=AcquisitionMethod.SIGNED_URL, status=AcquisitionStatus.ACQUIRED,
        acquired_at=NOW, observation_id=observation_id,
    )


def test_acquisition_attempt_is_persisted_independently():
    repo = InMemorySourceAcquisitionRepository()
    record_acquisition(acquired(), repository=repo)
    assert repo.get("acq-1").observation_id == "obs-1"


def test_multiple_acquisitions_can_reference_same_observation():
    repo = InMemorySourceAcquisitionRepository()
    record_acquisition(acquired("acq-1"), repository=repo)
    record_acquisition(acquired("acq-2"), repository=repo)
    assert len(repo.acquisitions) == 2
    assert {item.observation_id for item in repo.acquisitions.values()} == {"obs-1"}


def test_acquired_requires_observation():
    with pytest.raises(ValueError, match="ACQUIRED_REQUIRES_OBSERVATION"):
        SourceAcquisition(
            acquisition_id="acq-1", document_id="doc-1",
            tenant_id="tenant-a", application_id="app-a",
            method=AcquisitionMethod.UPLOAD, status=AcquisitionStatus.ACQUIRED,
            acquired_at=NOW,
        )


def test_failed_acquisition_cannot_reference_observation():
    with pytest.raises(ValueError, match="NON_ACQUIRED_CANNOT_REFERENCE_OBSERVATION"):
        SourceAcquisition(
            acquisition_id="acq-1", document_id="doc-1",
            tenant_id="tenant-a", application_id="app-a",
            method=AcquisitionMethod.CONNECTOR, status=AcquisitionStatus.FAILED,
            acquired_at=NOW, observation_id="obs-1", failure_code="SOURCE_UNAVAILABLE",
        )


def test_acquisition_id_is_immutable_in_memory_store():
    repo = InMemorySourceAcquisitionRepository()
    record_acquisition(acquired(), repository=repo)
    with pytest.raises(ValueError, match="ACQUISITION_ALREADY_EXISTS"):
        record_acquisition(acquired(), repository=repo)
