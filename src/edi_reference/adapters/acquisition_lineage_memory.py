"""In-memory durable acquisition repository for tests."""

from dataclasses import dataclass, field

from edi_reference.domain.acquisition_lineage import SourceAcquisition


@dataclass
class InMemorySourceAcquisitionRepository:
    acquisitions: dict[str, SourceAcquisition] = field(default_factory=dict)

    def save(self, acquisition: SourceAcquisition) -> None:
        if acquisition.acquisition_id in self.acquisitions:
            raise ValueError("ACQUISITION_ALREADY_EXISTS")
        self.acquisitions[acquisition.acquisition_id] = acquisition

    def get(self, acquisition_id: str) -> SourceAcquisition | None:
        return self.acquisitions.get(acquisition_id)
