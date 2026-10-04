"""Machine-readable conformance report primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from edi_reference.contracts.specification import TARGET
from edi_reference.domain.models import Capability, ConformanceStatus


@dataclass(frozen=True, slots=True)
class VectorResult:
    vector_id: str
    status: ConformanceStatus
    message: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    implementation_name: str
    implementation_version: str
    declared_capabilities: tuple[Capability, ...]
    results: tuple[VectorResult, ...]

    def to_dict(self) -> dict[str, object]:
        passed = sum(x.status is ConformanceStatus.PASS for x in self.results)
        failed = sum(x.status is ConformanceStatus.FAIL for x in self.results)
        skipped = sum(x.status is ConformanceStatus.SKIP for x in self.results)
        not_applicable = sum(
            x.status is ConformanceStatus.NOT_APPLICABLE for x in self.results
        )
        return {
            "specification_version": TARGET.specification_version,
            "implementation": {
                "name": self.implementation_name,
                "version": self.implementation_version,
                "environment": None,
            },
            "declared_capabilities": [x.value for x in self.declared_capabilities],
            "results": [
                {
                    "vector_id": result.vector_id,
                    "status": result.status.value,
                    "message": result.message,
                    "evidence_ref": result.evidence_ref,
                }
                for result in self.results
            ],
            "summary": {
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "not_applicable": not_applicable,
            },
        }


def build_report(
    *,
    implementation_name: str,
    implementation_version: str,
    capabilities: Iterable[Capability],
    results: Iterable[VectorResult],
) -> ConformanceReport:
    return ConformanceReport(
        implementation_name=implementation_name,
        implementation_version=implementation_version,
        declared_capabilities=tuple(capabilities),
        results=tuple(results),
    )
