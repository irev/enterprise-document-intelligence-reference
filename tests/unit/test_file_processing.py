import hashlib
import json

import pytest

from edi_reference.application.file_processing import ProcessingLog, process_file
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine


def _ocr_result() -> OcrResult:
    box = BoundingBox(0.0, 0.0, 1.0, 1.0)
    return OcrResult(
        (
            OcrPage(1, 100.0, 100.0, (OcrTextLine("alpha", box), OcrTextLine("beta gamma", box))),
            OcrPage(2, 100.0, 100.0, (OcrTextLine("delta", box),)),
        )
    )


def test_process_file_reports_total_pages_and_per_page_analysis(tmp_path) -> None:
    log_path = tmp_path / "processing.jsonl"
    log = ProcessingLog(sink_path=log_path, now=lambda: "2026-10-05T00:00:00+00:00")

    report = process_file(
        source_name="sample.pdf",
        document_bytes=b"%PDF-1.4 synthetic",
        analyze=lambda _: _ocr_result(),
        log=log,
    )

    digest = hashlib.sha256(b"%PDF-1.4 synthetic").hexdigest()
    assert report.file_id == digest
    assert report.sha256 == digest
    assert report.source_name == "sample.pdf"
    assert report.status == "COMPLETED"
    assert report.total_pages == 2
    assert [page.page_number for page in report.pages] == [1, 2]
    assert report.pages[0].line_count == 2
    assert report.pages[0].character_count == len("alpha") + len("beta gamma")
    assert report.pages[1].line_count == 1
    assert report.pages[1].character_count == len("delta")

    payload = report.to_dict()
    assert payload["total_pages"] == 2
    assert payload["status"] == "COMPLETED"
    pages = payload["pages"]
    assert isinstance(pages, tuple)
    assert pages[0]["page_number"] == 1
    assert pages[0]["line_count"] == 2

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [entry["event"] for entry in events] == [
        "FILE_PROCESSING_STARTED",
        "PAGE_ANALYZED",
        "PAGE_ANALYZED",
        "FILE_PROCESSING_COMPLETED",
    ]
    assert events[0]["source_name"] == "sample.pdf"
    assert events[0]["sha256"] == digest
    assert events[1]["page_number"] == 1
    assert events[1]["line_count"] == 2
    assert events[1]["ts"] == "2026-10-05T00:00:00+00:00"
    assert events[2]["page_number"] == 2
    assert events[3]["total_pages"] == 2
    assert events[3]["pages_analyzed"] == 2


def test_process_file_records_failure_and_reraises() -> None:
    log = ProcessingLog(now=lambda: "T")

    def boom(_: bytes) -> OcrResult:
        raise RuntimeError("LOCAL_OCR_FAILED")

    with pytest.raises(RuntimeError, match="LOCAL_OCR_FAILED"):
        process_file(
            source_name="broken.pdf",
            document_bytes=b"broken",
            analyze=boom,
            log=log,
        )

    assert [entry["event"] for entry in log.events] == [
        "FILE_PROCESSING_STARTED",
        "FILE_PROCESSING_FAILED",
    ]
    failure = log.events[-1]
    assert failure["error_code"] == "LOCAL_OCR_FAILED"
    assert failure["file_id"] == hashlib.sha256(b"broken").hexdigest()


def test_processing_log_appends_jsonl_across_instances(tmp_path) -> None:
    log_path = tmp_path / "nested" / "dir" / "processing.jsonl"
    first = ProcessingLog(sink_path=log_path, now=lambda: "T1")
    first.record("FILE_PROCESSING_STARTED", file_id="f1")
    second = ProcessingLog(sink_path=log_path, now=lambda: "T2")
    second.record("FILE_PROCESSING_STARTED", file_id="f2")

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [entry["file_id"] for entry in events] == ["f1", "f2"]
    assert first.events != second.events
