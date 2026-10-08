"""Control-panel document service: storage, processing, jobs, benchmark (RI-4.11).

- Documents are content-addressed by SHA-256 and written once.
- Every processing run writes a new immutable result version; reprocessing
  never replaces an earlier result.
- Results record the configuration versions, OCR engine and model used.
- One worker thread runs jobs in order; the queue is in memory, so jobs that
  were queued when the service stopped must be resubmitted.
"""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from edi_reference.application.classification import ClassificationPolicy, classify_document
from edi_reference.application.extraction import extract_fields
from edi_reference.application.invocation import ProviderInvoker
from edi_reference.application.llm_classification import LlmClassifier
from edi_reference.application.llm_extraction import LlmFieldExtractor
from edi_reference.application.panel_config import ConfigStore, schema_from_dict
from edi_reference.application.structured_ocr import structured_ocr_to_document
from edi_reference.application.title_rules import TitleRuleClassifier, title_rule_profile_from_dict
from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE
from edi_reference.domain.document_structure import StructuredDocument
from edi_reference.domain.execution import (
    Capability,
    DataEgress,
    ExecutionClass,
    ExecutionPolicy,
    ProviderCapability,
)
from edi_reference.domain.extraction import FieldState
from edi_reference.domain.invocation import InvocationLimits
from edi_reference.domain.lineage import SourceObservation
from edi_reference.domain.ocr import OcrResult
from edi_reference.domain.taxonomy import DocumentTaxonomy

MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}")
MEDIA_SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)
PROVIDER_ID = "lmstudio-local"


def detect_media_type(content: bytes) -> str:
    for signature, media_type in MEDIA_SIGNATURES:
        if content.startswith(signature):
            return media_type
    raise ValueError("UNSUPPORTED_MEDIA_TYPE")


class OcrPagesResult(Protocol):
    @property
    def result(self) -> OcrResult: ...
    @property
    def text_layer(self) -> str: ...
    @property
    def total_pages(self) -> int: ...


class OcrEngine(Protocol):
    def recognize(self, content: bytes, media_type: str, *, max_pages: int) -> OcrPagesResult: ...
    def decode(self, raw_pages: list) -> OcrResult: ...


class ModelControl(Protocol):
    def status(self) -> dict: ...
    def start(self) -> None: ...
    def load(self, key: str, *, exclusive: bool = True) -> None: ...


InvokerFactory = Callable[[str], ProviderInvoker]


def _write_once(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=1)


def _read(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class DocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def _dir(self, document_id: str) -> Path:
        if not SHA256.fullmatch(document_id):
            raise ValueError("INVALID_DOCUMENT_ID")
        return self.root / document_id[:2] / document_id

    def put(self, content: bytes, filename: str, *, uploaded_by: str) -> dict:
        if not 0 < len(content) <= MAX_DOCUMENT_BYTES:
            raise ValueError("DOCUMENT_SIZE_INVALID")
        media_type = detect_media_type(content)
        document_id = hashlib.sha256(content).hexdigest()
        name = Path(filename.replace("\\", "/")).name[:200] or "document"
        with self._lock:
            directory = self._dir(document_id)
            meta_path = directory / "meta.json"
            meta = _read(meta_path)
            if meta is None:
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "content").write_bytes(content)
                meta = {"document_id": document_id, "media_type": media_type, "byte_length": len(content),
                        "filenames": [name], "uploaded_by": uploaded_by,
                        "uploaded_at": datetime.now(UTC).isoformat(), "label": None}
            elif name not in meta["filenames"]:
                meta["filenames"].append(name)
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return meta

    def meta(self, document_id: str) -> dict:
        meta = _read(self._dir(document_id) / "meta.json")
        if meta is None:
            raise LookupError("DOCUMENT_NOT_FOUND")
        return meta

    def content(self, document_id: str) -> bytes:
        self.meta(document_id)
        return (self._dir(document_id) / "content").read_bytes()

    def set_label(self, document_id: str, label: str | None) -> None:
        with self._lock:
            path = self._dir(document_id) / "meta.json"
            meta = self.meta(document_id)
            meta["label"] = label
            path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def list_documents(self) -> list[dict]:
        items = []
        for meta_path in self.root.glob("*/*/meta.json"):
            meta = _read(meta_path)
            if meta:
                results = sorted((meta_path.parent / "results").glob("r*.json"))
                latest = _read(results[-1]) if results else None
                meta = dict(meta, result_count=len(results),
                            latest=None if latest is None else {key: latest.get(key) for key in (
                                "version", "status", "document_type", "classification_source", "completed_at",
                                "fields_present")})
                items.append(meta)
        return sorted(items, key=lambda item: item["uploaded_at"], reverse=True)

    def save_result(self, document_id: str, result: dict) -> int:
        with self._lock:
            directory = self._dir(document_id) / "results"
            directory.mkdir(parents=True, exist_ok=True)
            number = max((int(p.stem[1:]) for p in directory.glob("r*.json")), default=0) + 1
            _write_once(directory / f"r{number:05d}.json", dict(result, version=number))
            return number

    def results(self, document_id: str) -> list[dict]:
        self.meta(document_id)
        return [_read(p) for p in sorted((self._dir(document_id) / "results").glob("r*.json"))]

    def ocr_cache(self, document_id: str, key: str) -> Path:
        return self._dir(document_id) / "ocr-cache" / f"{key}.json"


@dataclass
class Job:
    job_id: str
    kind: str
    actor: str
    params: dict
    status: str = "QUEUED"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    progress: dict = field(default_factory=lambda: {"done": 0, "total": 0})
    log: list = field(default_factory=list)
    result: dict | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def say(self, message: str) -> None:
        self.log.append(time.strftime("%H:%M:%S ") + message)
        del self.log[:-300]

    def view(self, *, full: bool = False) -> dict:
        out: dict[str, object] = {"job_id": self.job_id, "kind": self.kind, "actor": self.actor, "status": self.status,
               "created_at": self.created_at, "progress": self.progress, "params": self.params}
        if full:
            out.update(log=self.log[-60:], result=self.result)
        return out


class PanelService:
    def __init__(self, *, store: DocumentStore, config: ConfigStore, ocr: Callable[[dict], OcrEngine],
                 invoker_factory: InvokerFactory, models: ModelControl, runs_dir: Path,
                 on_event: Callable[..., object] = lambda *a, **k: None) -> None:
        self.store, self.config, self._ocr, self._invoker = store, config, ocr, invoker_factory
        self.models, self.runs_dir, self._on_event = models, runs_dir, on_event
        self._queue: deque[Job] = deque()
        self._jobs: dict[str, Job] = {}
        self._cv = threading.Condition()
        self._worker = threading.Thread(target=self._loop, name="panel-worker", daemon=True)
        self._worker.start()

    # ------------------------------------------------------------ jobs
    def submit(self, kind: str, actor: str, params: dict) -> Job:
        if kind not in ("process", "benchmark"):
            raise ValueError("UNKNOWN_JOB_KIND")
        job = Job(uuid.uuid4().hex[:12], kind, actor, params)
        with self._cv:
            self._jobs[job.job_id] = job
            self._queue.append(job)
            self._cv.notify()
        return job

    def jobs(self) -> list[dict]:
        return [job.view() for job in sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)][:100]

    def job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise LookupError("JOB_NOT_FOUND")
        return job

    def cancel(self, job_id: str) -> None:
        job = self.job(job_id)
        job.cancel.set()
        if job.status == "QUEUED":
            job.status = "CANCELLED"

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._queue:
                    self._cv.wait()
                job = self._queue.popleft()
            if job.status == "CANCELLED":
                continue
            job.status = "RUNNING"
            try:
                (self._run_process if job.kind == "process" else self._run_benchmark)(job)
                job.status = "CANCELLED" if job.cancel.is_set() else "DONE"
            except Exception as exc:  # noqa: BLE001 - reported on the job
                job.status = "FAILED"
                job.say(f"FAILED: {type(exc).__name__}: {exc}")
                traceback.print_exc()
            self._on_event(job.actor, f"job.{job.kind}.finished", target=job.job_id, outcome=job.status)

    # ------------------------------------------------------------ pipeline
    def snapshot(self, model_override: str | None = None, mode_override: str | None = None) -> dict:
        pipeline = self.config.get("pipeline")
        content = dict(pipeline["content"])
        if model_override:
            content["llm"] = dict(content["llm"], model=model_override)
        if mode_override:
            content["classification_mode"] = mode_override
        return {"pipeline": content, "pipeline_version": pipeline["version"],
                "title_rules": self.config.get("title_rules"), "schema": self.config.get("extraction_schema")}

    def _ensure_model(self, model: str, job: Job) -> None:
        status = self.models.status()
        if not status["running"]:
            job.say("Starting LM Studio server")
            self.models.start()
        if model not in status.get("loaded", []):
            job.say(f"Loading model {model}")
            self.models.load(model)

    def _ocr_pages(self, document_id: str, content: bytes, media_type: str, snap: dict) -> tuple[OcrResult, str, int, float, bool]:
        ocr_cfg = snap["pipeline"]["ocr"]
        max_pages = snap["pipeline"]["max_pages"]
        key = hashlib.sha256(json.dumps([ocr_cfg, max_pages], sort_keys=True).encode()).hexdigest()[:32]
        cache = self.store.ocr_cache(document_id, key)
        cached = _read(cache)
        engine = self._ocr(ocr_cfg)
        if cached is not None:
            return engine.decode(cached["pages"]), cached["text_layer"], cached["total_pages"], cached["ocr_s"], True
        started = time.perf_counter()
        pages = engine.recognize(content, media_type, max_pages=max_pages)
        seconds = round(time.perf_counter() - started, 2)
        raw = getattr(pages, "raw_pages", None)
        if raw is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"pages": raw, "text_layer": pages.text_layer,
                                         "total_pages": pages.total_pages, "ocr_s": seconds}), encoding="utf-8")
        return pages.result, pages.text_layer, pages.total_pages, seconds, False

    def process_document(self, document_id: str, snap: dict, *, use_llm: bool = True) -> dict:
        meta = self.store.meta(document_id)
        content = self.store.content(document_id)
        pipeline = snap["pipeline"]
        profile = title_rule_profile_from_dict(snap["title_rules"]["content"])
        schema = schema_from_dict(snap["schema"]["content"])
        taxonomy = DocumentTaxonomy("panel", profile.taxonomy_version,
                                    frozenset(rule.document_type for rule in profile.rules))
        model = pipeline["llm"]["model"]
        result: dict = {
            "document_id": document_id, "started_at": datetime.now(UTC).isoformat(),
            "config": {"pipeline": snap["pipeline_version"], "title_rules": snap["title_rules"]["version"],
                       "extraction_schema": snap["schema"]["version"]},
            "ocr_engine": f"{pipeline['ocr']['det_name']} + {pipeline['ocr']['rec_name']}",
            "llm_model": model if use_llm else None, "classification_mode": pipeline["classification_mode"],
        }
        try:
            ocr_result, text_layer, total_pages, ocr_s, cached = self._ocr_pages(document_id, content, meta["media_type"], snap)
            observation = SourceObservation(f"obs-{document_id[:16]}", document_id, "local", "control-panel",
                                            document_id, len(content), meta["media_type"], datetime.now(UTC))
            document = structured_ocr_to_document(ocr_result, observation=observation, component="paddleocr",
                                                  component_version=result["ocr_engine"])
            result.update(ocr_s=ocr_s, ocr_cached=cached, pages_processed=len(document.pages),
                          total_pages=total_pages, lines=sum(len(p.text_blocks) for p in document.pages))
            started = time.perf_counter()
            prediction, source = self._classify(document, pipeline, profile, taxonomy, use_llm)
            result.update(document_type=prediction.document_type, classification_source=source,
                          classifier=prediction.model_id, classify_s=round(time.perf_counter() - started, 2),
                          classification_evidence=[_evidence_view(e) for e in prediction.evidence])
            fields: list[dict] = []
            if use_llm:
                provider = _provider(model, Capability.FIELD_EXTRACTION)
                extractor = LlmFieldExtractor(schema=schema, provider=provider, policy=_LOCAL_POLICY,
                                              limits=_LIMITS, invoker=self._invoker(model))
                started = time.perf_counter()
                extracted = extract_fields(document, document_type=prediction.document_type, extractor=extractor,
                                           schema=schema)
                result["extract_s"] = round(time.perf_counter() - started, 2)
                fields = [{"field_name": f.field_name, "state": f.state.value, "raw_value": f.raw_value,
                           "value_type": f.value_type, "extractor": f.extractor_id,
                           "evidence": [_evidence_view(e) for e in f.evidence]} for f in extracted]
            result["fields"] = fields
            result["fields_present"] = sum(f["state"] == FieldState.PRESENT.value for f in fields)
            result["text_layer_check"] = {f["field_name"]: in_text_layer(f["raw_value"] or "", text_layer)
                                          for f in fields if f["state"] == FieldState.PRESENT.value}
            result["blocks"] = [{"page": p.page_number, "block_id": b.block_id, "text": b.text,
                                 "bbox": [b.bbox.x0, b.bbox.y0, b.bbox.x1, b.bbox.y1], "confidence": b.confidence}
                                for p in document.pages for b in p.text_blocks]
            result["status"] = "COMPLETED"
        except Exception as exc:  # noqa: BLE001 - fail safe, recorded on the result
            result.update(status="FAILED_SAFE", document_type=UNKNOWN_DOCUMENT_TYPE,
                          error_code=(str(exc) or type(exc).__name__)[:120])
        result["completed_at"] = datetime.now(UTC).isoformat()
        return result

    def _classify(self, document: StructuredDocument, pipeline: dict, profile, taxonomy, use_llm: bool):
        mode = pipeline["classification_mode"]
        policy = ClassificationPolicy(0.9, 0.0)
        if mode in ("rules", "rules_then_llm") or not use_llm:
            prediction = classify_document(document, classifier=TitleRuleClassifier(profile), policy=policy,
                                           taxonomy=taxonomy)
            if prediction.document_type != UNKNOWN_DOCUMENT_TYPE or mode == "rules" or not use_llm:
                return prediction, "rules"
        model = pipeline["llm"]["model"]
        classifier = LlmClassifier(taxonomy=taxonomy, provider=_provider(model, Capability.CLASSIFICATION),
                                   policy=_LOCAL_POLICY, limits=_LIMITS, invoker=self._invoker(model))
        return classify_document(document, classifier=classifier, policy=policy, taxonomy=taxonomy), "llm"

    def _run_process(self, job: Job) -> None:
        ids = list(job.params["document_ids"])
        use_llm = job.params.get("use_llm", True)
        snap = self.snapshot()
        job.progress["total"] = len(ids)
        if use_llm:
            self._ensure_model(snap["pipeline"]["llm"]["model"], job)
        versions = {}
        for document_id in ids:
            if job.cancel.is_set():
                return
            result = self.process_document(document_id, snap, use_llm=use_llm)
            result["job_id"], result["processed_by"] = job.job_id, job.actor
            versions[document_id] = self.store.save_result(document_id, result)
            job.say(f"{document_id[:12]} -> {result.get('document_type')} ({result['status']})")
            job.progress["done"] += 1
        job.result = {"versions": versions}

    # ------------------------------------------------------------ benchmark
    def _run_benchmark(self, job: Job) -> None:
        ids = list(job.params["document_ids"])
        models = list(job.params["models"]) or [None]
        mode = job.params.get("mode")
        job.progress["total"] = len(ids) * len(models)
        run: dict[str, Any] = {"run_id": job.job_id, "actor": job.actor, "mode": mode, "started_at": job.created_at, "models": {}}
        for model in models:
            if job.cancel.is_set():
                break
            snap = self.snapshot(model_override=model, mode_override=mode)
            if model:
                try:
                    self._ensure_model(model, job)
                except Exception as exc:  # noqa: BLE001
                    run["models"][model] = {"error": str(exc) or type(exc).__name__, "summary": summarize([]),
                                            "documents": []}
                    job.progress["done"] += len(ids)
                    continue
            docs = []
            for document_id in ids:
                if job.cancel.is_set():
                    break
                label = self.store.meta(document_id).get("label")
                result = self.process_document(document_id, snap, use_llm=model is not None)
                docs.append({"document_id": document_id, "file": self.store.meta(document_id)["filenames"][0],
                             "label": label, "predicted": result.get("document_type"),
                             "source": result.get("classification_source"), "present": result.get("fields_present", 0),
                             "text_layer_check": result.get("text_layer_check", {}), "ocr_s": result.get("ocr_s"),
                             "llm_s": result.get("extract_s"), "pages": result.get("pages_processed"),
                             "error": result.get("error_code")})
                job.progress["done"] += 1
            run["models"][model or "(rules only)"] = {"summary": summarize(docs), "documents": docs}
            job.say(f"Finished {model or 'rules only'}")
        run["finished_at"] = datetime.now(UTC).isoformat()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        _write_once(self.runs_dir / f"{job.job_id}.json", run)
        job.result = run

    def benchmark_runs(self) -> list[dict]:
        runs = []
        for path in sorted(self.runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            run = _read(path, {})
            runs.append({"run_id": run.get("run_id"), "actor": run.get("actor"), "mode": run.get("mode"),
                         "started_at": run.get("started_at"), "models": list(run.get("models", {}))})
        return runs

    def benchmark_run(self, run_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{12}", run_id):
            raise ValueError("INVALID_RUN_ID")
        run = _read(self.runs_dir / f"{run_id}.json")
        if run is None:
            raise LookupError("RUN_NOT_FOUND")
        return run


_LOCAL_POLICY = ExecutionPolicy("local-only", "1", frozenset({ExecutionClass.LOCAL_MODEL}), allow_external_egress=False)
_LIMITS = InvocationLimits(timeout_seconds=180, max_input_bytes=400_000, max_output_bytes=64_000)


def _provider(model: str, capability: Capability) -> ProviderCapability:
    return ProviderCapability(PROVIDER_ID, model, ExecutionClass.LOCAL_MODEL, frozenset({capability}), DataEgress.NONE)


def _evidence_view(evidence) -> dict:
    return {"page": evidence.page_number, "block_id": evidence.block_id, "quote": evidence.text_quote}


def _norm(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", value.lower())


def in_text_layer(value: str, text: str) -> bool | None:
    """Independent check against the PDF text layer; None when there is none (scans)."""
    if not text.strip():
        return None
    return bool(_norm(value)) and _norm(value) in _norm(text)


def summarize(docs: list[dict]) -> dict:
    labelled = [d for d in docs if d.get("label")]
    ok = [d for d in docs if not d.get("error")]
    checks = [v for d in ok for v in d.get("text_layer_check", {}).values() if v is not None]
    llm = [d["llm_s"] for d in ok if d.get("llm_s") is not None]
    confusion: dict[tuple[str, str], int] = {}
    for doc in labelled:
        predicted = doc.get("predicted") or "ERROR"
        if predicted != doc["label"]:
            confusion[(doc["label"], predicted)] = confusion.get((doc["label"], predicted), 0) + 1
    return {
        "documents": len(docs), "errors": len(docs) - len(ok), "labelled": len(labelled),
        "correct": sum(d.get("predicted") == d["label"] for d in labelled),
        "unknown": sum(d.get("predicted") == UNKNOWN_DOCUMENT_TYPE for d in ok),
        "wrong_not_unknown": sum(d.get("predicted") not in (d["label"], UNKNOWN_DOCUMENT_TYPE)
                                 for d in labelled if not d.get("error")),
        "fields_present": sum(d.get("present", 0) for d in ok),
        "text_layer_checked": len(checks), "text_layer_confirmed": sum(checks),
        "llm_median_s": round(statistics.median(llm), 2) if llm else None,
        "llm_max_s": round(max(llm), 2) if llm else None,
        "ocr_median_s": round(statistics.median(d["ocr_s"] for d in ok if d.get("ocr_s") is not None), 2)
        if any(d.get("ocr_s") is not None for d in ok) else None,
        "confusion": [{"label": a, "predicted": b, "count": n} for (a, b), n in sorted(confusion.items())],
    }
