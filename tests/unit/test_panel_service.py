import json
import threading
from pathlib import Path

import pytest

from edi_reference.application.panel_config import ConfigStore
from edi_reference.application.panel_service import DocumentStore, PanelService, detect_media_type, summarize
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.invocation import InvocationResult
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine

ROOT = Path(__file__).resolve().parents[2]
PDF = b"%PDF-1.7 synthetic document"
PNG = b"\x89PNG\r\n\x1a\n synthetic"


class Pages:
    def __init__(self, lines):
        self.result = OcrResult((OcrPage(1, 1000.0, 1000.0, tuple(
            OcrTextLine(text, BoundingBox(0.1, 0.05 * i, 0.9, 0.05 * i + 0.04), 0.99) for i, text in enumerate(lines))),))
        self.text_layer = "\n".join(lines)
        self.total_pages = 1
        self.raw_pages = None


class FakeOcr:
    calls = 0

    def __init__(self, lines):
        self.lines = lines

    def recognize(self, content, media_type, *, max_pages):
        FakeOcr.calls += 1
        return Pages(self.lines)

    def decode(self, raw):
        raise AssertionError("cache not used in this test")


class FakeInvoker:
    def __init__(self, model):
        self.model = model

    def invoke(self, request, limits):
        task = json.loads(request.input_bytes)
        if "fields" in task:
            out = {"fields": {"document_number": "SYN-0001", "total_amount": "Rp 9.999", "tax_id": None}}
        else:
            out = {"document_type": "PAYMENT_REQUEST", "evidence": "Pernyataan dana sintetis"}
        return InvocationResult("lmstudio-local", request.provider_version, json.dumps(out).encode())


class FakeModels:
    def __init__(self):
        self.loaded = []

    def status(self):
        return {"running": True, "loaded": self.loaded}

    def start(self):
        pass

    def load(self, key, *, exclusive=True):
        self.loaded = [key]


@pytest.fixture
def service(tmp_path):
    config = ConfigStore(tmp_path / "config")
    config.save("title_rules", json.loads((ROOT / "deploy/classification-profiles/title-rules-id-en.json").read_text()),
                author="t")
    config.save("extraction_schema", {"schema_id": "s", "version": "1", "fields": [
        {"field_name": "document_number", "value_type": "string"}, {"field_name": "total_amount", "value_type": "string"},
        {"field_name": "tax_id", "value_type": "string"}]}, author="t")
    config.save("pipeline", {"classification_mode": "rules", "max_pages": 2,
                             "llm": {"host": "127.0.0.1", "port": 12340, "model": "synthetic-model"},
                             "ocr": {"det_name": "d", "det_dir": "/d", "rec_name": "r", "rec_dir": "/r"}}, author="t")
    lines = {"value": ["INVOICE", "Invoice number SYN-0001", "Total Rp 1.000"]}
    finished = threading.Event()
    svc = PanelService(store=DocumentStore(tmp_path / "docs"), config=config, ocr=lambda cfg: FakeOcr(lines["value"]),
                       invoker_factory=FakeInvoker, models=FakeModels(), runs_dir=tmp_path / "runs",
                       on_event=lambda *a, **k: finished.set())
    svc.lines, svc.finished = lines, finished
    return svc


def wait(svc, job):
    assert svc.finished.wait(10)
    svc.finished.clear()
    return svc.job(job.job_id)


def test_media_detection_and_content_addressing(tmp_path):
    store = DocumentStore(tmp_path)
    first = store.put(PDF, "a.pdf", uploaded_by="op")
    again = store.put(PDF, "copy.pdf", uploaded_by="op2")
    assert first["document_id"] == again["document_id"]
    assert store.meta(first["document_id"])["filenames"] == ["a.pdf", "copy.pdf"]
    assert store.meta(first["document_id"])["uploaded_by"] == "op"
    assert detect_media_type(PNG) == "image/png"
    with pytest.raises(ValueError, match="UNSUPPORTED_MEDIA_TYPE"):
        store.put(b"MZ executable", "x.exe", uploaded_by="op")
    with pytest.raises(ValueError, match="INVALID_DOCUMENT_ID"):
        store.meta("../etc")


def test_processing_creates_new_immutable_result_versions(service):
    doc = service.store.put(PDF, "inv.pdf", uploaded_by="op")["document_id"]
    job = wait(service, service.submit("process", "op", {"document_ids": [doc], "use_llm": True}))
    assert job.status == "DONE"
    job2 = wait(service, service.submit("process", "op", {"document_ids": [doc], "use_llm": False}))
    assert job2.status == "DONE"

    results = service.store.results(doc)
    assert [r["version"] for r in results] == [1, 2]
    first = results[0]
    assert first["status"] == "COMPLETED"
    assert first["document_type"] == "INVOICE" and first["classification_source"] == "rules"
    assert first["config"] == {"pipeline": 1, "title_rules": 1, "extraction_schema": 1}
    fields = {f["field_name"]: f for f in first["fields"]}
    assert fields["document_number"]["state"] == "PRESENT"
    assert fields["document_number"]["evidence"][0]["quote"] == "SYN-0001"
    assert fields["total_amount"]["state"] == "MISSING"  # model value not in source
    assert results[1]["llm_model"] is None and results[1]["fields"] == []
    with pytest.raises(FileExistsError):  # completed versions are write-once
        (service.store.root / doc[:2] / doc / "results" / "r00001.json").open("x")


def test_llm_fallback_requires_quoted_evidence(service):
    service.config.save("pipeline", dict(service.config.active("pipeline"), classification_mode="rules_then_llm"), author="t")
    service.lines["value"] = ["Pernyataan dana sintetis", "Nomor SYN-0001"]
    doc = service.store.put(PNG, "x.png", uploaded_by="op")["document_id"]
    wait(service, service.submit("process", "op", {"document_ids": [doc]}))
    result = service.store.results(doc)[-1]
    assert result["document_type"] == "PAYMENT_REQUEST" and result["classification_source"] == "llm"
    assert result["classification_evidence"][0]["quote"] == "Pernyataan dana sintetis"

    service.lines["value"] = ["Some unrelated heading"]
    other = service.store.put(PDF + b"2", "y.pdf", uploaded_by="op")["document_id"]
    wait(service, service.submit("process", "op", {"document_ids": [other]}))
    assert service.store.results(other)[-1]["document_type"] == "UNKNOWN"  # quote not in source -> abstain


def test_ocr_failure_is_recorded_fail_safe(service):
    class Broken(FakeOcr):
        def recognize(self, *a, **k):
            raise RuntimeError("OCR_TIMEOUT")

    service._ocr = lambda cfg: Broken([])
    doc = service.store.put(PDF, "bad.pdf", uploaded_by="op")["document_id"]
    wait(service, service.submit("process", "op", {"document_ids": [doc]}))
    result = service.store.results(doc)[-1]
    assert result["status"] == "FAILED_SAFE"
    assert result["document_type"] == "UNKNOWN"
    assert result["error_code"] == "OCR_TIMEOUT"


def test_benchmark_compares_models_and_persists_run(service):
    doc = service.store.put(PDF, "inv.pdf", uploaded_by="op")["document_id"]
    service.store.set_label(doc, "INVOICE")
    job = wait(service, service.submit("benchmark", "op", {"document_ids": [doc], "models": ["m-a", "m-b"], "mode": "rules"}))
    assert job.status == "DONE"
    run = service.benchmark_run(job.job_id)
    assert set(run["models"]) == {"m-a", "m-b"}
    assert run["models"]["m-a"]["summary"]["correct"] == 1
    assert service.benchmark_runs()[0]["run_id"] == job.job_id
    assert service.store.results(doc) == []  # benchmarks never write official results


def test_summary_counts_abstention_separately():
    s = summarize([{"label": "INVOICE", "predicted": "UNKNOWN", "present": 0},
                   {"label": "UNKNOWN", "predicted": "INVOICE", "present": 2, "text_layer_check": {"a": True}}])
    assert (s["correct"], s["unknown"], s["wrong_not_unknown"], s["text_layer_confirmed"]) == (0, 1, 1, 1)
