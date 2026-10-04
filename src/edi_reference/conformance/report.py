"""Machine-readable conformance report primitives."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from edi_reference.contracts.specification import TARGET
from edi_reference.domain.models import Capability, ConformanceStatus


@dataclass(frozen=True, slots=True)
class VectorResult:
    vector_id: str
    capability: Capability
    status: ConformanceStatus
    message: str | None = None


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    implementation_name: str
    implementation_version: str
    declared_capabilities: tuple[Capability, ...]
    vector_results: tuple[VectorResult, ...]

    def to_dict(self) -> dict[str, object]:
        passed = sum(x.status is ConformanceStatus.PASS for x in self.vector_results)
        failed = sum(x.status is ConformanceStatus.FAIL for x in self.vector_results)
        skipped = sum(x.status is ConformanceStatus.SKIP for x in self.vector_results)
        not_applicable = sum(
            x.status is ConformanceStatus.NOT_APPLICABLE for x in self.vector_results
        )
        return {
            "specification_version": TARGET.specification_version,
            "implementation": {
                "name": self.implementation_name,
                "version": self.implementation_version,
                "environment": "unspecified",
            },
            "declared_capabilities": [x.value for x in self.declared_capabilities],
            "vector_results": [
                {
                    **asdict(result),
                    "capability": result.capability.value,
                    "status": result.status.value,
                }
                for result in self.vector_results
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
        vector_results=tuple(results),
    )
