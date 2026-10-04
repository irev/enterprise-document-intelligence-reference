"""Persist source acquisition attempts independently from observations."""

from typing import Protocol

from edi_reference.domain.acquisition_lineage import SourceAcquisition


class SourceAcquisitionRepository(Protocol):
    def save(self, acquisition: SourceAcquisition) -> None: ...
    def get(self, acquisition_id: str) -> SourceAcquisition | None: ...


def record_acquisition(
    acquisition: SourceAcquisition, *, repository: SourceAcquisitionRepository
) -> SourceAcquisition:
    repository.save(acquisition)
    return acquisition
