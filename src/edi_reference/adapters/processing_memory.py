"""Deterministic processing claim adapter for tests."""

from dataclasses import dataclass, field

from edi_reference.domain.processing import ProcessingClaim


@dataclass
class InMemoryProcessingClaimRepository:
    claims: dict[str, ProcessingClaim] = field(default_factory=dict)

    def get(self, message_id: str) -> ProcessingClaim | None:
        return self.claims.get(message_id)

    def try_create(self, claim: ProcessingClaim) -> bool:
        if claim.message_id in self.claims:
            return False
        self.claims[claim.message_id] = claim
        return True

    def save(self, claim: ProcessingClaim) -> None:
        self.claims[claim.message_id] = claim
