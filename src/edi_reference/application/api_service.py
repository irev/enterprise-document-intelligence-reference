"""v1 data-plane API service: keys, submission, durable worker, result v1 (RI-6.0, phase A).

Framework-free application layer. Storage and normalizers are injected; the
pipeline itself is the control panel's `PanelService.process_document`, so the
panel and the API produce results the same way and share one OCR/GPU worker
(serialized by `PanelService.processing_lock`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Protocol

from edi_reference.application.extraction_registry import registry_from_dict
from edi_reference.application.normalization import NormalizationRegistry
from edi_reference.application.panel_service import PanelService, config_versions, detect_media_type
from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE
from edi_reference.domain.normalization import NormalizationError

RESULT_SCHEMA = "tlkdoc.result/v1"
NOTICE = "Machine result. Not a business approval or authorization."
SCOPES = ("documents:write", "documents:read", "results:read", "documents:read:tenant")
DEFAULT_SCOPES = ("documents:write", "documents:read", "results:read")
MAX_BYTES_CEILING = 50 * 1024 * 1024
MAX_ATTEMPTS = 3
ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
IDEMPOTENCY_PATTERN = re.compile(r"[\x21-\x7e]{1,200}")
REFERENCE_PATTERN = re.compile(r"([A-Za-z0-9_.-]{1,50})=([^\r\n]{1,200})")
KEY_PATTERN = re.compile(r"tlk_(k[0-9A-Z]{16})\.([A-Za-z0-9_-]{43})")
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_id(prefix: str) -> str:
    """Time-ordered 26-character identifier (ULID layout) with a type prefix."""
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


class ApiError(Exception):
    def __init__(self, status: int, code: str, title: str = "", *, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.status, self.code, self.title, self.retry_after = status, code, title or code, retry_after


@dataclass(frozen=True, slots=True)
class ApiPrincipal:
    tenant_id: str
    application_id: str
    key_id: str
    scopes: frozenset[str]
    application: dict

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise ApiError(403, "SCOPE_REQUIRED", f"Scope {scope} required")


class ApiStore(Protocol):
    def application(self, application_id: str) -> dict | None: ...
    def key(self, key_id: str) -> dict | None: ...
    def touch_key(self, key_id: str) -> None: ...
    def add_key(self, *, key_id: str, application_id: str, secret_sha256: str, scopes: list[str], created_by: str) -> None: ...
    def submit(self, document: dict): ...
    def queued_count(self, tenant_id: str, application_id: str) -> int: ...
    def document(self, document_id: str) -> dict | None: ...
    def claim(self, *, lease_seconds: int) -> dict | None: ...
    def complete(self, job_id: str, document_id: str, body: dict) -> int: ...


def issue_key(store: ApiStore, application_id: str, scopes: list[str], *, created_by: str) -> tuple[str, str]:
    """Create a key; returns (key_id, full secret token). The token is shown once and never stored."""
    if store.application(application_id) is None:
        raise LookupError("APPLICATION_NOT_FOUND")
    if not scopes or any(scope not in SCOPES for scope in scopes):
        raise ValueError("INVALID_SCOPES")
    key_id = "k" + "".join(secrets.choice(_CROCKFORD) for _ in range(16))
    secret = secrets.token_urlsafe(32)
    store.add_key(key_id=key_id, application_id=application_id, secret_sha256=hashlib.sha256(secret.encode()).hexdigest(),
                  scopes=sorted(set(scopes)), created_by=created_by)
    return key_id, f"tlk_{key_id}.{secret}"


class RateLimiter:
    """Per-application token bucket (requests per minute)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._buckets: dict[str, tuple[float, float]] = {}
        self._clock = clock
        self._lock = threading.Lock()

    def check(self, key: str, per_minute: int) -> None:
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - last) * per_minute / 60.0)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                raise ApiError(429, "RATE_LIMITED", "Too many requests", retry_after=max(1, int((1 - tokens) * 60 / per_minute) + 1))
            self._buckets[key] = (tokens - 1.0, now)


class ApiService:
    def __init__(self, *, store: ApiStore, panel: PanelService, registry: NormalizationRegistry,
                 normalizers: dict[str, tuple[str, str]], on_event: Callable[..., object] = lambda *a, **k: None,
                 lease_seconds: int = 900, poll_seconds: float = 1.0) -> None:
        self.store, self.panel = store, panel
        self._registry, self._normalizers = registry, normalizers
        self._on_event = on_event
        self._lease, self._poll = lease_seconds, poll_seconds
        self.limiter = RateLimiter()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ authentication
    def authenticate(self, authorization: str | None) -> ApiPrincipal:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "API_KEY_REQUIRED", "API key required")
        match = KEY_PATTERN.fullmatch(authorization[7:].strip())
        record = self.store.key(match.group(1)) if match else None
        if (match is None or record is None or record["revoked_at"] is not None or record["application_disabled"]
                or not hmac.compare_digest(hashlib.sha256(match.group(2).encode()).hexdigest(), record["secret_sha256"])):
            raise ApiError(401, "API_KEY_INVALID", "API key invalid")
        application = self.store.application(record["application_id"]) or {}
        self.store.touch_key(record["key_id"])
        principal = ApiPrincipal(record["tenant_id"], record["application_id"], record["key_id"],
                                 frozenset(record["scopes"]), application)
        self.limiter.check(principal.application_id, int(application["rate_per_minute"]))
        return principal

    def owned_document(self, principal: ApiPrincipal, document_id: str) -> dict:
        document = self.store.document(document_id) if re.fullmatch(r"doc_[0-9A-Z]{26}", document_id) else None
        visible = document is not None and document["tenant_id"] == principal.tenant_id and (
            document["application_id"] == principal.application_id or "documents:read:tenant" in principal.scopes)
        if not visible:
            # Other applications' documents are indistinguishable from missing ones.
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document not found")
        return document  # type: ignore[return-value]

    # ------------------------------------------------------------ submission
    def submit_upload(self, principal: ApiPrincipal, content: bytes, *, idempotency_key: str | None,
                      correlation_id: str | None, filename: str | None, profile: str | None,
                      external_references: list[str]) -> tuple[dict, bool]:
        principal.require("documents:write")
        if not idempotency_key:
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header required")
        if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
            raise ApiError(400, "INVALID_IDEMPOTENCY_KEY", "Invalid Idempotency-Key")
        if correlation_id is not None and not ID_PATTERN.fullmatch(correlation_id):
            raise ApiError(400, "INVALID_CORRELATION_ID", "Invalid X-Correlation-Id")
        app = principal.application
        profile = profile or app["default_profile"]
        if profile not in app["allowed_profiles"]:
            raise ApiError(400, "PROFILE_NOT_ALLOWED", "Processing profile not allowed")
        references = {}
        for item in external_references[:11]:
            match = REFERENCE_PATTERN.fullmatch(item)
            if match is None:
                raise ApiError(400, "INVALID_EXTERNAL_REFERENCE", "Invalid X-External-Reference")
            references[match.group(1)] = match.group(2)
        if len(references) > 10:
            raise ApiError(400, "TOO_MANY_EXTERNAL_REFERENCES", "At most 10 external references")
        if not content:
            raise ApiError(400, "EMPTY_DOCUMENT", "Document body is empty")
        if len(content) > min(int(app["max_bytes"]), MAX_BYTES_CEILING):
            raise ApiError(413, "DOCUMENT_TOO_LARGE", "Document too large")
        try:
            media_type = detect_media_type(content)
        except ValueError:
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Unsupported media type") from None
        sha256 = hashlib.sha256(content).hexdigest()
        fingerprint = hashlib.sha256(json.dumps({"method": "UPLOAD", "sha256": sha256, "profile": profile},
                                                sort_keys=True).encode()).hexdigest()
        if self.store.queued_count(principal.tenant_id, principal.application_id) >= int(app["max_queued"]):
            raise ApiError(429, "QUEUE_LIMIT_REACHED", "Too many documents waiting", retry_after=30)
        name = filename.replace("\\", "/").rsplit("/", 1)[-1][:200] if filename else None
        # Content-addressed blob; the API document record keeps tenant/application ownership.
        self.panel.store.put(content, name or "document", uploaded_by=f"app:{principal.application_id}")
        try:
            submission = self.store.submit({
                "document_id": new_id("doc"), "tenant_id": principal.tenant_id,
                "application_id": principal.application_id, "idempotency_key": idempotency_key,
                "fingerprint": fingerprint, "correlation_id": correlation_id or new_id("corr"), "sha256": sha256,
                "media_type": media_type, "byte_length": len(content), "filename": name,
                "external_references": references, "profile": profile,
            })
        except ValueError as exc:
            if str(exc) == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST":
                raise ApiError(409, str(exc), "Idempotency key reused with a different request") from None
            raise
        if not submission.replayed:
            self._wake.set()
        return submission.document, submission.replayed

    # ------------------------------------------------------------ worker
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="api-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not self.run_once():
                    self._wake.wait(self._poll)
                    self._wake.clear()
            except Exception:  # noqa: BLE001 - keep the worker alive; the job lease retries
                traceback.print_exc()
                time.sleep(self._poll)

    def run_once(self) -> bool:
        job = self.store.claim(lease_seconds=self._lease)
        if job is None:
            return False
        document = self.store.document(job["document_id"])
        assert document is not None
        snap = self.panel.snapshot()
        if job["attempts"] > MAX_ATTEMPTS:
            body = self.failed_safe(document, snap, "PROCESSING_ATTEMPTS_EXHAUSTED")
        else:
            # A model server that is down raises here; the job lease expires and the
            # job is retried, up to MAX_ATTEMPTS. There is no silent rules-only fallback.
            self.panel.ensure_model(snap["pipeline"]["llm"]["model"])
            try:
                raw = self.panel.process_document(document["sha256"], snap, use_llm=True)
                body = self.to_result(document, raw, snap)
            except Exception:  # noqa: BLE001 - a result is still recorded, fail-safe
                traceback.print_exc()
                body = self.failed_safe(document, snap, "RESULT_MAPPING_FAILED")
        version = self.store.complete(job["job_id"], document["document_id"], body)
        self._on_event(f"app:{document['application_id']}", "api.document.processed", target=document["document_id"],
                       outcome=body["status"], result_version=version)
        return True

    # ------------------------------------------------------------ result v1
    def _base(self, document: dict, snap: dict, status: str) -> dict:
        pipeline = snap["pipeline"]
        ocr = pipeline["ocr"]
        return {
            "schema": RESULT_SCHEMA, "result_id": new_id("res"), "result_version": 0,
            "document_id": document["document_id"], "tenant_id": document["tenant_id"],
            "application_id": document["application_id"], "processing_run_id": new_id("run"),
            "correlation_id": document["correlation_id"], "status": status, "failure": None,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "source": {"sha256": document["sha256"], "media_type": document["media_type"],
                       "byte_length": document["byte_length"], "pages_total": None, "pages_processed": 0,
                       "filename": document["filename"], "external_references": document["external_references"]},
            "provenance": {
                "processing_profile": {"id": document["profile"], "version": 1},
                "configuration": config_versions(snap),
                "extraction_schema": None,
                "ocr": {"engine": "paddleocr", "models": [ocr["det_name"], ocr["rec_name"]],
                        "model_digests_pinned": bool(ocr.get("det_digest") and ocr.get("rec_digest"))},
                "model": None,
            },
            "review": {"required": True, "status": "NOT_REVIEWED"},
            "notice": NOTICE,
        }

    def _taxonomy(self, snap: dict) -> dict:
        rules = snap["title_rules"]["content"]
        return {"id": str(rules["profile_id"]), "version": str(rules["taxonomy_version"])}

    def failed_safe(self, document: dict, snap: dict, code: str) -> dict:
        body = self._base(document, snap, "FAILED_SAFE")
        rules = snap["title_rules"]["content"]
        body["failure"] = {"code": code}
        body["classification"] = {"document_type": UNKNOWN_DOCUMENT_TYPE, "abstained": True, "method": "NONE",
                                  "taxonomy": self._taxonomy(snap),
                                  "classifier": {"id": f"title-rules/{rules['profile_id']}", "version": str(rules["version"])},
                                  "confidence": None, "evidence": []}
        body["fields"] = []
        return body

    def to_result(self, document: dict, raw: dict, snap: dict) -> dict:
        if raw.get("status") != "COMPLETED":
            body = self.failed_safe(document, snap, raw.get("error_code") or "PROCESSING_FAILED")
            return body
        body = self._base(document, snap, "COMPLETED")
        boxes = {block["block_id"]: block["bbox"] for block in raw.get("blocks", [])}

        def evidence(items: list[dict]) -> list[dict]:
            out = []
            for item in items:
                entry = {"page": item["page"], "block_id": item["block_id"], "quote": item["quote"]}
                if item["block_id"] in boxes:
                    entry["bbox"] = [round(float(v), 4) for v in boxes[item["block_id"]]]
                out.append(entry)
            return out

        body["source"].update(pages_total=raw.get("total_pages"), pages_processed=raw.get("pages_processed", 0))
        document_type = raw["document_type"]
        body["classification"] = {
            "document_type": document_type, "abstained": document_type == UNKNOWN_DOCUMENT_TYPE,
            "method": {"rules": "TITLE_RULE", "llm": "LLM_GROUNDED"}.get(str(raw.get("classification_source") or ""), "NONE"),
            "taxonomy": self._taxonomy(snap),
            "classifier": {"id": raw.get("classifier") or "none",
                           "version": str(snap["title_rules"]["version"]) if raw.get("classification_source") == "rules"
                           else str(raw.get("llm_model") or "none")},
            "confidence": None,
            "evidence": evidence(raw.get("classification_evidence", [])) if document_type != UNKNOWN_DOCUMENT_TYPE else [],
        }
        body["provenance"]["extraction_schema"] = raw.get("extraction_schema")
        model = raw.get("llm_model")
        if model:
            body["provenance"]["model"] = {"id": model, "execution_class": "LOCAL_MODEL", "data_egress": "NONE"}
        fields = []
        for field in raw.get("fields", []):
            normalized, error = None, None
            if field["state"] == "PRESENT":
                normalized, error = self._normalize(field["value_type"], field["raw_value"], snap)
            fields.append({
                "name": field["field_name"], "value_type": field["value_type"], "state": field["state"],
                "raw_value": field["raw_value"], "normalized": normalized, "normalization_error": error,
                "confidence": None, "evidence": evidence(field.get("evidence", [])),
                "extractor": {"id": field.get("extractor") or "none", "version": str(model or "none")},
                "origin": "MACHINE",
            })
        body["fields"] = fields
        return body

    def _chain(self, value_type: str, snap: dict) -> tuple[tuple[str, str], ...]:
        if snap.get("registry"):
            return registry_from_dict(snap["registry"]["content"]).normalizer_chain(value_type)
        return (self._normalizers[value_type],) if value_type in self._normalizers else ()

    def _normalize(self, value_type: str, raw_value: str, snap: dict) -> tuple[dict | None, str | None]:
        """Try the configured chain in order; the first normalizer that accepts the value wins.

        An ambiguity reported by any step is preferred over a plain format mismatch,
        because it tells the operator a locale decision is needed.
        """
        errors = []
        for normalizer_id, version in self._chain(value_type, snap):
            try:
                value = self._registry.normalize(raw_value, normalizer_id=normalizer_id, version=version)
            except NormalizationError as exc:
                errors.append(exc.code)
                continue
            return {"value": value.value, "normalizer": {"id": value.normalizer_id, "version": value.normalizer_version}}, None
        if not errors:
            return None, None
        return None, next((code for code in errors if code.startswith("AMBIGUOUS")), errors[-1])

    # ------------------------------------------------------------ discovery
    def taxonomy(self) -> dict:
        snap = self.panel.snapshot()
        rules = snap["title_rules"]["content"]
        types = sorted({rule["document_type"] for rule in rules["rules"]})
        return {"taxonomy_id": str(rules["profile_id"]), "version": str(rules["taxonomy_version"]),
                "document_types": types, "unknown": UNKNOWN_DOCUMENT_TYPE}

    def field_schema(self, document_type: str) -> dict:
        if document_type not in self.taxonomy()["document_types"] + [UNKNOWN_DOCUMENT_TYPE]:
            raise ApiError(404, "DOCUMENT_TYPE_NOT_FOUND", "Unknown document type")
        snap = self.panel.snapshot()

        def normalizer(value_type: str) -> dict | None:
            chain = self._chain(value_type, snap)
            return {"id": chain[0][0], "version": chain[0][1]} if chain else None

        if snap.get("registry"):
            registry = registry_from_dict(snap["registry"]["content"])
            selection = registry.select(document_type)
            schema = selection.schema
            if schema is None:
                return {"document_type": document_type, "schema_id": "none", "version": "0", "fields": []}
            return {"document_type": document_type, "schema_id": schema.schema_id, "version": schema.version,
                    "fields": [{"name": f.field_name, "value_type": f.value_type, "normalizer": normalizer(f.value_type)}
                               for f in schema.fields]}
        legacy = snap["schema"]["content"]
        return {"document_type": document_type, "schema_id": str(legacy["schema_id"]), "version": str(legacy["version"]),
                "fields": [{"name": f["field_name"], "value_type": f["value_type"], "normalizer": normalizer(f["value_type"])}
                           for f in legacy["fields"]]}
