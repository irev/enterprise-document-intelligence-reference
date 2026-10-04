from edi_reference.conformance.report import VectorResult, build_report
from edi_reference.domain.models import Capability, ConformanceStatus


def test_report_matches_normative_shape_and_is_summarized() -> None:
    report = build_report(
        implementation_name="edi-reference-python",
        implementation_version="0.1.0",
        capabilities=[Capability.CORE],
        results=[
            VectorResult("CORE-001", ConformanceStatus.PASS),
            VectorResult("CORE-002", ConformanceStatus.SKIP),
        ],
    )

    payload = report.to_dict()

    assert payload["specification_version"] == "0.9"
    assert payload["declared_capabilities"] == ["CORE"]
    assert payload["results"][0]["vector_id"] == "CORE-001"
    assert payload["results"][0]["status"] == "PASS"
    assert payload["summary"] == {
        "passed": 1,
        "failed": 0,
        "skipped": 1,
        "not_applicable": 0,
    }
