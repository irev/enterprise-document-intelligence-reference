import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from edi_reference.adapters.normalizers import reference_normalizers
from edi_reference.adapters.sqlite_api_store import SqliteApiStore
from edi_reference.application.api_service import ApiService
from edi_reference.application.extraction_registry import registry_from_dict
from edi_reference.application.normalization import NormalizationRegistry
from edi_reference.application.panel_config import ConfigStore
from edi_reference.application.panel_service import DocumentStore, PanelService
from edi_reference.application.title_rules import load_title_rule_profile
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.invocation import InvocationResult
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine

ROOT = Path(__file__).resolve().parents[2]
SEEDS = ROOT / "deploy/classification-profiles"
REGISTRY = json.loads((SEEDS / "extraction-registry-business-documents.json").read_text(encoding="utf-8"))
RULES = json.loads((SEEDS / "title-rules-id-en.json").read_text(encoding="utf-8"))
RESULT = Draft202012Validator(json.loads((ROOT / "src/edi_reference/contracts/result-v1.schema.json").read_text(encoding="utf-8")),
                              format_checker=FormatChecker())


def mutate(fn):
    data = copy.deepcopy(REGISTRY)
    fn(data)
    return data


def test_seed_registry_is_valid_and_covers_every_seed_category():
    registry = registry_from_dict(REGISTRY)
    taxonomy = {rule.document_type for rule in load_title_rule_profile(SEEDS / "title-rules-id-en.json").rules}
    assert set(registry.categories) == taxonomy
    assert all(spec.description for spec in registry.fields.values())


@pytest.mark.parametrize(("change", "code"), [
    (lambda d: d["categories"]["INVOICE"]["fields"].append("nonexistent_field"), "UNKNOWN_FIELD_REFERENCE"),
    (lambda d: d["fields"]["subject"].update(description=""), "FIELD_DESCRIPTION_REQUIRED"),
    (lambda d: d["fields"]["subject"].update(value_type="blob"), "INVALID_FIELD_VALUE_TYPE"),
    (lambda d: d["normalizers"]["date"].append("date.guess@1"), "UNKNOWN_NORMALIZER"),
    (lambda d: d["normalizers"]["date"].append("money.idr.multi-format@1"), "UNKNOWN_NORMALIZER"),
    (lambda d: d["categories"]["RECEIPT"].update(schema_id="invoice-header"), "DUPLICATE_SCHEMA_ID"),
    (lambda d: d.update(unknown_policy="GUESS"), "INVALID_SCHEMA_POLICY"),
    (lambda d: d["categories"].update(UNKNOWN=d["common_schema"]), "INVALID_CATEGORY_ID"),
    (lambda d: d["categories"]["INVOICE"]["fields"].append("subject"), "INVALID_CATEGORY_SCHEMA_FIELDS"),
])
def test_registry_validation(change, code):
    with pytest.raises(ValueError, match=code):
        registry_from_dict(mutate(change))


def test_schema_selection_and_policies():
    registry = registry_from_dict(REGISTRY)
    invoice = registry.select("INVOICE")
    assert invoice.source == "CATEGORY" and invoice.reference == {"id": "invoice-header", "version": "1"}
    assert "contract value" in registry.select("CONTRACT").descriptions["contract_amount"]
    assert registry.select("UNKNOWN").source == "COMMON"
    assert registry.select("NOT_CONFIGURED").reference == {"id": "common-header", "version": "1"}
    strict = registry_from_dict(mutate(lambda d: d.update(unknown_policy="NONE", missing_category_policy="NONE")))
    assert strict.select("UNKNOWN").schema is None and strict.select("NOT_CONFIGURED").source == "NONE"


# ---------------------------------------------------------------- pipeline with the registry
LINES = ["INVOICE", "Nomor INV-SYN-0001", "Tanggal 15 Juli 2026", "Jatuh tempo 05/08/2026", "Total Rp 1.250.000,00",
         "Subtotal 1,125,000.00"]


class Pages:
    def __init__(self, lines):
        self.result = OcrResult((OcrPage(1, 1000.0, 1000.0, tuple(
            OcrTextLine(t, BoundingBox(0.1, 0.05 * i, 0.9, 0.05 * i + 0.04), 0.99) for i, t in enumerate(lines))),))
        self.text_layer = "\n".join(lines)
        self.total_pages = 1
        self.raw_pages = None


class Ocr:
    lines = LINES

    def recognize(self, content, media_type, *, max_pages):
        return Pages(Ocr.lines)

    def decode(self, raw):
        raise AssertionError


class Invoker:
    requests: list = []

    def __init__(self, model):
        self.model = model

    def invoke(self, request, limits):
        task = json.loads(request.input_bytes)
        Invoker.requests.append(task)
        values = {"document_number": "INV-SYN-0001", "document_date": "15 Juli 2026", "due_date": "05/08/2026",
                  "total_amount": "Rp 1.250.000,00", "subtotal_amount": "1,125,000.00"}
        return InvocationResult("lmstudio-local", request.provider_version,
                                json.dumps({"fields": {f["name"]: values.get(f["name"]) for f in task["fields"]}}).encode())


class Models:
    def status(self):
        return {"running": True, "loaded": ["synthetic-model"]}

    def start(self):
        pass

    def load(self, key, *, exclusive=True):
        pass


@pytest.fixture
def api(tmp_path):
    Invoker.requests = []
    Ocr.lines = LINES
    config = ConfigStore(tmp_path / "config")
    config.save("title_rules", RULES, author="t")
    config.save("extraction_schema", {"schema_id": "legacy", "version": "1", "fields": [
        {"field_name": "document_number", "value_type": "string"}]}, author="t")
    config.save("extraction_registry", REGISTRY, author="t")
    config.save("pipeline", {"classification_mode": "rules", "max_pages": 2,
                             "llm": {"host": "127.0.0.1", "port": 12340, "model": "synthetic-model"},
                             "ocr": {"det_name": "d", "det_dir": "/d", "rec_name": "r", "rec_dir": "/r"}}, author="t")
    panel = PanelService(store=DocumentStore(tmp_path / "docs"), config=config, ocr=lambda cfg: Ocr(),
                         invoker_factory=Invoker, models=Models(), runs_dir=tmp_path / "runs")
    store = SqliteApiStore(tmp_path / "api.sqlite3")
    store.create_application(application_id="app-a", tenant_id="t", name="a", default_profile="default",
                             allowed_profiles=["default"], rate_per_minute=100, max_queued=10, max_bytes=10_000, created_by="t")
    service = ApiService(store=store, panel=panel, registry=NormalizationRegistry(reference_normalizers()), normalizers={})
    yield service, store
    store.close()


def process(service, store, content=b"%PDF-1.7 synthetic"):
    from edi_reference.application.api_service import ApiPrincipal

    principal = ApiPrincipal("t", "app-a", "k", frozenset({"documents:write"}), store.application("app-a"))
    document, _ = service.submit_upload(principal, content, idempotency_key=content.hex()[:40], correlation_id=None,
                                        filename="x.pdf", profile=None, external_references=[])
    service.run_once()
    return store.result(document["document_id"], None)


def test_category_schema_drives_extraction_and_normalization(api):
    service, store = api
    result = process(service, store)
    assert list(RESULT.iter_errors(result)) == []
    assert result["provenance"]["extraction_schema"] == {"id": "invoice-header", "version": "1", "selection": "CATEGORY"}
    assert result["provenance"]["configuration"]["extraction_registry"] == 1
    names = [f["name"] for f in result["fields"]]
    assert names[:4] == ["document_number", "document_date", "issuer_name", "recipient_name"] and "due_date" in names
    # descriptions from the catalog reach the model
    sent = {f["name"]: f["description"] for f in Invoker.requests[-1]["fields"]}
    assert "due date" in sent["due_date"].lower()
    fields = {f["name"]: f for f in result["fields"]}
    assert fields["document_date"]["normalized"] == {"value": "2026-07-15", "normalizer": {"id": "date.textual.id-en", "version": "1"}}
    assert fields["total_amount"]["normalized"]["value"] == {"amount": "1250000.00", "currency": "IDR"}
    assert fields["subtotal_amount"]["normalized"]["value"] == {"amount": "1125000.00", "currency": "IDR"}
    # 05/08/2026 is ambiguous: kept raw, and the ambiguity is reported instead of a plain format error
    assert fields["due_date"]["normalized"] is None and fields["due_date"]["normalization_error"] == "AMBIGUOUS_DATE_FORMAT"


def test_unknown_documents_use_the_common_schema_explicitly(api):
    service, store = api
    Ocr.lines = ["Catatan rapat", "Nomor INV-SYN-0001"]
    result = process(service, store, b"%PDF-1.7 other")
    assert result["classification"]["document_type"] == "UNKNOWN"
    assert result["provenance"]["extraction_schema"]["selection"] == "COMMON"
    assert list(RESULT.iter_errors(result)) == []


def test_none_policy_extracts_nothing_and_skips_the_model(api):
    service, store = api
    service.panel.config.save("extraction_registry", dict(REGISTRY, unknown_policy="NONE"), author="t")
    Ocr.lines = ["Catatan rapat"]
    calls = len(Invoker.requests)
    result = process(service, store, b"%PDF-1.7 none")
    assert result["fields"] == [] and result["provenance"]["extraction_schema"] is None
    assert len(Invoker.requests) == calls
    assert list(RESULT.iter_errors(result)) == []


def test_schema_discovery_is_per_category(api):
    service, _ = api
    invoice = service.field_schema("INVOICE")
    assert invoice["schema_id"] == "invoice-header"
    assert {"name": "due_date", "value_type": "date", "normalizer": {"id": "date.iso-8601", "version": "1"}} in invoice["fields"]
    assert service.field_schema("TAX_INVOICE")["schema_id"] == "tax-invoice-header"
