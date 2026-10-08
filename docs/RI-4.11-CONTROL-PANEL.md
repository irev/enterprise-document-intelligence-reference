# RI-4.11 — Control Panel (`tlkdoc serve-panel`)

## Objective

One authenticated web console to operate the local pipeline (PaddleOCR → title rules → grounded LLM extraction, RI-4.10) for a small office network: runtime status and control, document processing with evidence, model benchmarking and versioned configuration.

Standard library only. No web framework, ORM, queue or cloud SDK. OCR runs in the isolated PaddleOCR runtime interpreter; the panel process never imports it.

## Components

| Layer | Module | Responsibility |
|---|---|---|
| application | `panel_auth.py` | users (PBKDF2-HMAC-SHA256, 600k iterations, per-user salt), roles, in-memory sessions with idle/absolute expiry, login throttling |
| application | `panel_audit.py` | append-only JSONL audit log, SHA-256 hash chain, `verify_chain` |
| application | `panel_config.py` | versioned configuration: `pipeline`, `title_rules`, `extraction_schema`; validated before storage; activation pointer |
| application | `panel_service.py` | content-addressed document store, immutable result versions, single-worker job queue, benchmark runs |
| application | `llm_classification.py` | LLM classification fallback that must quote a source line as evidence |
| adapters | `runtime_ocr.py`, `paddle_page_worker.py` | OCR through the runtime interpreter with a fixed argument vector, timeout and pinned model digests |
| adapters | `lmstudio_control.py` | LM Studio server and model control through the `lms` CLI |
| adapters | `control_panel_web.py`, `control_panel_static/` | HTTP(S) server, routes, UI |
| CLI | `panel_cli.py` | `tlkdoc serve-panel`, `tlkdoc panel-user` |

## Security model

- **Transport.** Binding to anything but loopback requires `--tls-cert` and `--tls-key`; the server refuses to start otherwise. TLS 1.2 minimum. HSTS is sent under TLS.
- **Authentication.** Username and password; no default account. The server refuses to start until an admin exists (`tlkdoc panel-user add <name> --role ADMIN`). Passwords are at least 12 characters, never stored or logged in plaintext. Five failures per username or client address lock both for 15 minutes.
- **Sessions.** Random 256-bit tokens held only in memory (a restart signs everyone out), cookie `HttpOnly; SameSite=Strict` (+`Secure` under TLS), 30-minute idle and 12-hour absolute expiry. Disabling a user or changing their password or role revokes their sessions.
- **Request integrity.** Every state-changing request needs the per-session `X-CSRF-Token` header and a same-origin `Origin`. The `Host` header must be one of the configured hosts (DNS-rebinding defence).
- **Roles.** `VIEWER` reads; `OPERATOR` uploads, labels, processes and benchmarks; `ADMIN` additionally controls LM Studio, configuration, server-side folder import, users and the audit log. Panel roles authorize panel operations only, never business actions on documents.
- **Content.** Document bytes are untrusted. Uploads are accepted only for PDF, PNG, JPEG and TIFF signatures (50 MB limit), stored by SHA-256, and downloaded only as `attachment` with `Content-Security-Policy: sandbox`. The UI renders document text with `textContent` only, under `default-src 'self'` without inline scripts or styles.
- **Errors.** Clients receive stable codes only. OCR worker diagnostics go to the server log.
- **Audit.** Logins (including failures and lockouts), uploads, downloads, labels, jobs, runtime actions, configuration changes and user changes are written with actor, client address, target and outcome. Credentials, tokens and field values are never written.

## Data and versioning

State lives under `--state-dir` (default `.edi/panel`, git-ignored):

```text
users.json                  password hashes
audit.jsonl                 hash-chained audit log
config/<kind>/v00001.json   immutable configuration versions + active.json pointer
documents/<aa>/<sha256>/    content, meta.json, results/r00001.json …, ocr-cache/
benchmarks/<run>.json       benchmark runs
```

- A document is written once; uploading the same bytes again only records the extra filename.
- Each processing run writes a new result version that records the pipeline, title-rule and schema versions, OCR engine and model. Earlier versions are never replaced. A failure is recorded as `FAILED_SAFE` with document type `UNKNOWN` and a stable error code.
- Benchmarks never write official document results.
- Configuration saves create a new version; any earlier version can be re-activated. OCR model digests are set only by the "pin" action, never typed in, and a mismatch stops OCR with `OCR_MODEL_DIGEST_MISMATCH`.

## Limits

- The job queue is in memory. Jobs queued when the service stops must be resubmitted; completed results are durable.
- One worker processes jobs in order, matching a single local GPU.
- Sessions are per process; run one panel instance per state directory.
- Human correction of extracted values is not part of this panel; results are machine claims.
