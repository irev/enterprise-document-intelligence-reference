# RI-6.0 — Data-Plane API v1 (design)

Status: **phase A implemented** (see §12). Phases B–E remain design. Machine-readable artifacts:

- [`src/edi_reference/contracts/openapi-v1.json`](../src/edi_reference/contracts/openapi-v1.json): HTTP contract (OpenAPI 3.1), served at `/v1/openapi.json`.
- [`src/edi_reference/contracts/result-v1.schema.json`](../src/edi_reference/contracts/result-v1.schema.json): result document (JSON Schema 2020-12), served at `/v1/result-v1.schema.json`.
- [`docs/api/examples/`](api/examples/): example payloads that validate against those schemas.

> **Specification alignment pending.** This design builds on the contracts already in this reference implementation (RI-0.5, RI-1.5/1.6/1.11, RI-3.x, RI-5.x). It has not yet been checked against `irev/enterprise-document-intelligence` (`SPECIFICATION.md`, `NORMATIVE-MAP.md`, schemas, conformance vectors), because that repository was not available. Where the specification defines a result or error schema, the specification wins and this design must be adjusted. `contracts/specification.py` states that this implementation targets specification 0.9 with **canonical schema 2.0**: `tlkdoc.result/v1` must either become that canonical schema or carry a documented, tested mapping to it.

## 1. Goal

Let several applications submit documents to one local service, receive a standardized classification and field result as JSON, and get notified when it is ready. All OCR and model inference stays on the service host (PaddleOCR + loopback LLM, RI-4.10); documents never leave the machine.

```text
App A ─┐  HTTPS + API key            ┌─────────────── tlkdoc service host ───────────────┐
App B ─┼──────────────────────────▶  │ data plane /v1 ─▶ inbound ─▶ durable queue ─▶ worker │
App C ─┘  ◀── webhook (HMAC, ids) ── │                                  │ OCR (local)       │
                                     │ control panel (humans, RI-4.11) │ rules → local LLM │
                                     │                                  ▼                   │
                                     │                   immutable results (JSON v1)       │
                                     └──────────────────────────────────────────────────────┘
```

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | `/v1` is served by the same `tlkdoc` process as the panel, on a **separate listener** (`tlkdoc serve --api-port`, default 8444). | Shares the single GPU worker and stores. Machine credentials and human sessions never mix, and firewall rules can differ per port. |
| D2 | Applications authenticate with **API keys** bound to `(tenant_id, application_id, scopes)`: `Authorization: Bearer tlk_<key_id>.<secret>`. | Simple for integrators. Secrets are 256-bit random values stored as SHA-256 (high entropy, so no slow hash is needed). Several active keys per app allow rotation. Admins manage them in the panel and with `tlkdoc app`. |
| D3 | A document is visible **only to the application that submitted it**. Sharing within a tenant needs an explicit `documents:read:tenant` scope. | Least privilege. Cross-application reads in one tenant are an exception, not the default. |
| D4 | `document_id` is a server-generated opaque id (`doc_` + ULID), **not** the content hash. Storage stays content-addressed internally. | A hash-derived id would let one tenant probe whether another tenant holds a given file. |
| D5 | `Idempotency-Key` is **required** on every submission (RI-1.11). Same key + same request → `200` with the original record; same key + different request → `409 IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST`. | Safe client retries without duplicate processing. |
| D6 | Durable state in **SQLite** (Python `sqlite3`, WAL mode) behind the existing repository ports. PostgreSQL adapters (RI-4.9/5.x) remain the multi-node option. | Survives restarts (today's in-memory queue does not), adds no dependency, and enforces the `(tenant, application, idempotency_key)` uniqueness with a constraint (RI-1.11). |
| D7 | Webhooks carry **identifiers only** (`document_id`, `result_version`, `status`). The app then fetches the result with its key. Requests are signed with HMAC-SHA256 and retried with backoff through the outbox (RI-5.2). | Field values are never pushed to a URL that may have been mis-configured. |
| D8 | Errors use **RFC 9457** `application/problem+json` with a stable `code`. | Standard, machine-readable, and never leaks internals. |
| D9 | The result document is versioned by its own `schema` field (`tlkdoc.result/v1`). API changes inside `/v1` are additive only. | Consumers can validate and pin. |

## 3. Resources and lifecycle

```text
submission ──▶ RECEIVED ──▶ ACCEPTED ──▶ PROCESSING ──▶ COMPLETED
                  │             │              └──────▶ FAILED_SAFE   (result exists, type UNKNOWN)
                  ├──▶ REJECTED   (policy: size, pages, signature, quota)
                  └──▶ UNSUPPORTED (media type)
reprocess ──▶ ACCEPTED ──▶ … ──▶ new result_version (earlier versions unchanged)
```

- **Document:** one submission by one application, with metadata, status and `latest_result_version`.
- **Result:** immutable version `1..n`, one per processing run. Reprocessing (another profile, a new model, a corrected configuration) always creates a new version.
- `FAILED_SAFE` is a completed outcome with a result whose type is `UNKNOWN` and a stable `failure.code`. It is not a transport error.

## 4. Endpoints

All endpoints except `/v1/health` require a key. Scopes are shown per endpoint.

| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/v1/documents` | `documents:write` | Submit by **upload** (raw body, `Content-Type` = document media type) or by **URL** (`application/json` with a `source` object). Returns `202`, or `200` on an idempotent replay. |
| `GET` | `/v1/documents/{document_id}` | `documents:read` | Status, metadata and latest result version. |
| `GET` | `/v1/documents` | `documents:read` | List own documents (`status`, `created_after`, `external_reference`, cursor pagination). |
| `GET` | `/v1/documents/{document_id}/results` | `results:read` | Result version list. |
| `GET` | `/v1/documents/{document_id}/results/{version}` | `results:read` | Full result (`tlkdoc.result/v1`). `latest` is accepted as the version. |
| `POST` | `/v1/documents/{document_id}/reprocess` | `documents:write` | New processing run with an allowed profile. Requires an `Idempotency-Key`. |
| `GET` | `/v1/taxonomy` | `documents:read` | Active document types (including the reserved `UNKNOWN`) and taxonomy version. |
| `GET` | `/v1/schemas/{document_type}` | `documents:read` | Fields extracted for a type, with their value types and normalizers. |
| `GET` | `/v1/health` | — | Liveness only (`{"status":"ok"}`). No versions or internals. |
| `GET` | `/v1/openapi.json` | — | This contract. |

### Submission headers and fields

| Item | Required | Notes |
|---|---|---|
| `Idempotency-Key` | yes | 1–200 visible ASCII characters, unique per application. |
| `X-Correlation-Id` | no | Echoed in responses, results and webhooks; generated when absent. |
| `X-Filename` | no (upload) | Display name only. Path components are stripped. |
| `X-Processing-Profile` | no | Must be in the application's allowed profiles; defaults to the application's default profile. |
| `X-External-Reference` | no | The caller's own reference, `key=value` and repeatable, max 10. Stored and returned; never interpreted. |
| `source` (URL mode) | yes | `{"method":"SIGNED_URL","url":"https://…","expected_sha256":"…"}`. Fetched only from the admin allow-list, with the full RI-1.6 SSRF rules (DNS/IP validation, no private ranges unless explicitly allowed, redirect re-validation, size and time limits). Query values are never logged. |

`CONNECTOR` sources (shared folders, DMS) remain control-plane configuration (RI-1.6). They are planned for v1.1, not part of v1.

## 5. Result document `tlkdoc.result/v1`

Summary (normative definition: `result-v1.schema.json`):

```json
{
  "schema": "tlkdoc.result/v1",
  "result_id": "res_…", "result_version": 2, "document_id": "doc_…",
  "tenant_id": "…", "application_id": "…", "processing_run_id": "run_…", "correlation_id": "…",
  "status": "COMPLETED", "failure": null, "created_at": "2026-10-08T10:00:00Z",
  "source": {"sha256": "…", "media_type": "application/pdf", "byte_length": 0, "pages_total": 2, "pages_processed": 2},
  "classification": {
    "document_type": "TAX_INVOICE", "abstained": false, "method": "TITLE_RULE",
    "taxonomy": {"id": "…", "version": "…"}, "classifier": {"id": "…", "version": "…"},
    "confidence": null, "evidence": [{"page": 1, "block_id": "…", "quote": "Faktur Pajak", "bbox": [0.1, 0.05, 0.4, 0.08]}]
  },
  "fields": [{
    "name": "total_amount", "value_type": "money", "state": "PRESENT",
    "raw_value": "Rp 1.250.000,00",
    "normalized": {"value": {"amount": "1250000.00", "currency": "IDR"}, "normalizer": {"id": "money.id-ID.IDR", "version": "1"}},
    "normalization_error": null, "confidence": null,
    "evidence": [{"page": 1, "block_id": "…", "quote": "Rp 1.250.000,00", "bbox": [0.6, 0.7, 0.9, 0.72]}],
    "extractor": {"id": "llm-grounded/…", "version": "…"}, "origin": "MACHINE"
  }],
  "provenance": {
    "processing_profile": {"id": "…", "version": 1},
    "configuration": {"pipeline": 3, "title_rules": 1, "extraction_schema": 1},
    "ocr": {"engine": "paddleocr", "models": ["…"], "model_digests_pinned": true},
    "model": {"id": "google/gemma-4-e2b", "execution_class": "LOCAL_MODEL", "data_egress": "NONE"}
  },
  "review": {"required": true, "status": "NOT_REVIEWED"},
  "notice": "Machine result. Not a business approval or authorization."
}
```

Rules carried from the contracts in this repository:

- `UNKNOWN` is always a possible `document_type`, and `abstained: true` accompanies it (RI-3).
- `PRESENT` requires `raw_value` and at least one `evidence` entry. `raw_value` is the exact source span, never model text (RI-3.1/4.10). `MISSING` carries no value or evidence.
- Normalization is a separate, versioned stage (RI-3.10). A value that cannot be normalized keeps its `raw_value`, sets `normalized: null` and reports `normalization_error` (for example `INVALID_DATE_FORMAT`). It is never guessed.
- `confidence` is `null` unless a calibrated value exists. Model scores are not presented as probabilities (RI-3).
- `review.required` is always `true` in v1. Consumers must not treat a result as an approval (RI-3, AGENTS rule 6).
- Human corrections (planned, §9) create a new version whose fields record `origin: HUMAN`. They never overwrite the machine result (AGENTS rule 10).

## 6. Webhooks

Configured per application in the control plane (URL, events, secret). Events: `document.completed`, `document.failed_safe`, `document.rejected`.

```http
POST <subscriber url>
Content-Type: application/json
Tlkdoc-Event: document.completed
Tlkdoc-Delivery: dlv_…
Tlkdoc-Signature: t=1760000000,v1=<hex HMAC-SHA256(secret, t + "." + body)>

{"event":"document.completed","document_id":"doc_…","result_version":2,"status":"COMPLETED",
 "correlation_id":"…","occurred_at":"…"}
```

- Receivers verify the signature and reject a timestamp older than 5 minutes.
- Delivery is at-least-once (deduplicate on `Tlkdoc-Delivery`). Retries use exponential backoff for 24 hours, and attempts are visible in the panel (`DeliveryAttempt`).
- Subscriber URLs must be HTTPS. Private-network URLs need an explicit admin allow. No document content is sent.

## 7. Security

- **Transport and access:**
  - TLS is required off loopback, as for the panel.
  - Keys are never logged.
  - Each request is audited in the hash-chained audit log (RI-4.11) with application, key id, endpoint, document id and outcome.
- **Authorization:** checked on every request: scope, ownership (D3) and allowed processing profile. The tenant and application come only from the key, never from request content.
- **Limits per application** (configurable): requests per minute, concurrent queued documents, max bytes (default 50 MB) and max pages (default 20). Exceeding them returns `429` or `413` with `Retry-After` where applicable.
- **Untrusted content:** document content cannot change routing, profile, schema, tenant or authorization (AGENTS rule 11).
- **Data stays local:** OCR and LLM run on the host only. Policy rejects any non-loopback model endpoint (`DataEgress.NONE`). Outbound traffic is limited to allow-listed URL fetches and webhooks carrying identifiers.

## 8. Errors

```json
{"type": "https://tlkdoc.local/problems/idempotency-conflict", "title": "Idempotency key reused",
 "status": 409, "code": "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST", "request_id": "req_…"}
```

| Status | Codes (examples) |
|---|---|
| 400 | `INVALID_REQUEST`, `IDEMPOTENCY_KEY_REQUIRED`, `SOURCE_URL_INVALID`, `PROFILE_NOT_ALLOWED` |
| 401 | `API_KEY_REQUIRED`, `API_KEY_INVALID` |
| 403 | `SCOPE_REQUIRED`, `SOURCE_HOST_FORBIDDEN` |
| 404 | `DOCUMENT_NOT_FOUND`, `RESULT_NOT_FOUND`, also returned for other applications' documents |
| 409 | `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST` |
| 413 | `DOCUMENT_TOO_LARGE`, `PAGE_LIMIT_EXCEEDED` |
| 415 | `UNSUPPORTED_MEDIA_TYPE` |
| 429 | `RATE_LIMITED`, `QUEUE_LIMIT_REACHED` |
| 503 | `SERVICE_UNAVAILABLE` (store unavailable); processing failures are results, not 5xx |

## 9. Implementation plan

| Phase | Scope | Builds on |
|---|---|---|
| **A** | Application registry and API keys (panel and `tlkdoc app`); SQLite store for inbound, idempotency, documents, jobs and results; `POST /v1/documents` (upload), status, result list and result; result v1 mapping with normalization; `/v1/taxonomy`, `/v1/schemas`, `/v1/health`, `/v1/openapi.json`; per-app limits. | `inbound.receive_document`, RI-1.11 fingerprint, `ProcessingResult`, normalizers, panel worker |
| **B** | URL submission with SSRF-hardened fetcher and allow-list; `reprocess`; processing profiles per application. | RI-1.6, RI-1.10 refetch, `processing_profile` |
| **C** | Webhooks through the outbox with HMAC signing, retries and a delivery view in the panel. | RI-5.2 outbox, `DeliveryAttempt` |
| **D** | Per-type extraction schemas (for example tax invoice: seller/buyer tax id, tax base, VAT) and an Indonesian date normalizer (`15 Juli 2026`, `15/07/2026`), with strict RI-3.11 rules. | field schema registry, RI-3.11 |
| **E** | Review API: human correction as a new version with `origin: HUMAN`. | `human_review`, migration 0016 |

Every phase ships with deterministic tests (no network or model), OpenAPI and example validation in CI, and an update to this document.

## 10. Open questions

1. Specification alignment: confirm or replace the result and error formats against `irev/enterprise-document-intelligence`.
2. First consumer application: which document types, and which source mode (upload, URL or shared folder)?
3. Retention: how long documents and results are kept, and whether deleting a document is allowed (results are immutable, but deletion for retention may be required).

## 11. Validation of the design artifacts

When this design was written:

- `openapi-v1.json` validated as OpenAPI 3.1 (`openapi-spec-validator`).
- Both result examples validated against `result-v1.schema.json` (`jsonschema`, Draft 2020-12). The submission, problem and webhook examples validated against their OpenAPI component schemas.
- Ten deliberate contract violations were rejected by the schema: `PRESENT` without evidence, `MISSING` with a value, `UNKNOWN` not marked abstained, a typed class without evidence, `FAILED_SAFE` with a type, a remote model, review not required, a normalized value together with a normalization error, an unknown top-level property, and confidence above 1.

Phase A adds this validation to the test suite.

## 12. Phase A — what is implemented

| Component | Module |
|---|---|
| SQLite store: applications, keys (SHA-256 of the secret), documents with a unique idempotency constraint, leased job queue, results that triggers make immutable | `adapters/sqlite_api_store.py` |
| Key authentication, scopes, ownership, per-application rate and queue limits, upload submission, durable worker, `tlkdoc.result/v1` mapping with normalization, discovery | `application/api_service.py` |
| `/v1` HTTP(S) listener with RFC 9457 errors, Host check, audit of every call | `adapters/api_v1_web.py` |
| Contracts served at `/v1/openapi.json` and `/v1/result-v1.schema.json` | `contracts/` |
| `tlkdoc serve-panel --api-port`, `tlkdoc app add|key|revoke|list|disable|enable`, panel tab **Aplikasi** | `panel_cli.py`, `control_panel_web.py`, `control_panel_static/` |

Behaviour:

- **Shared pipeline.** The API and the panel share one pipeline and one OCR/GPU worker (`PanelService.processing_lock`). Uploaded bytes go into the same content-addressed store; ownership is held by the API document record.
- **Interrupted work.** A job interrupted by a crash or a model server that is down is retried when its lease expires (15 minutes), up to 3 attempts. After that a `FAILED_SAFE` result with `PROCESSING_ATTEMPTS_EXHAUSTED` is recorded. There is no silent rules-only fallback.
- **Normalizers.** Only the existing ones are wired: `money.id-ID.IDR`, `date.iso-8601` and `identifier.trimmed`. Other formats keep their raw value with a stable `normalization_error`. For example, `15 Juli 2026` and `September 20, 2026` give `INVALID_DATE_FORMAT`, and `Rp349,000.00` gives `INVALID_MONEY_FORMAT`. Wider normalizers are phase D.
- **Not yet available:** URL submission (`SOURCE_METHOD_NOT_AVAILABLE`), `reprocess`, processing profiles beyond `default`, and webhooks.

Verification at the time of writing:

- 20 HTTP-level unit tests cover keys, scopes, ownership, idempotency, limits, immutability, crash retry and fail-safe results; every produced result is validated against `result-v1.schema.json`. The panel and CLI application-management tests are separate.
- A Windows 11 HTTPS smoke run on real local documents submitted four documents as a consumer application. Idempotent replays returned the same id. Processing took 24–45 s for four documents. Classification was `TAX_INVOICE`, `INVOICE`, `UNKNOWN` and `RECEIPT`, and all four results were schema-valid.
