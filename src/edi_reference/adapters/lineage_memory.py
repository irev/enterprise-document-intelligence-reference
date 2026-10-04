"""In-memory lineage adapters for deterministic tests."""

from dataclasses import dataclass, field

from edi_reference.domain.lineage import ProcessingRunBinding, ScopedObservation


@dataclass
class InMemoryObservationRepository:
    observations: dict[str, ScopedObservation] = field(default_factory=dict)

    def get(self, observation_id: str) -> ScopedObservation | None:
        return self.observations.get(observation_id)

    def save(self, observation: ScopedObservation) -> None:
        self.observations[observation.observation_id] = observation

    def find_by_document_digest(self, document_id: str, sha256: str) -> ScopedObservation | None:
        return next(
            (
                item
                for item in self.observations.values()
                if item.document_id == document_id and item.sha256 == sha256
            ),
            None,
        )


@dataclass
class InMemoryProcessingRunRepository:
    bindings: dict[str, ProcessingRunBinding] = field(default_factory=dict)

    def save(self, binding: ProcessingRunBinding) -> None:
        self.bindings[binding.processing_run_id] = binding
