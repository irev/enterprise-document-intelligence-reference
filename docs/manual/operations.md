# Day-to-Day Operations

How the system is used after installation. Read the status notes first: the data plane
(submission → processing → review → results) is currently reachable as **library code
and PostgreSQL schema only** — there are no `edi` data-plane commands and no service
endpoint yet. See `../REQUIREMENTS-ANALYSIS.md` §3.3 (gap G5).

## Status overview

| Flow | How you operate it today | Status |
|---|---|---|
| Host inspection | `edi doctor` | current |
| Effective configuration (paths, provider/profile/model defaults) | `edi config` / `edi config --wizard` → `.edi/config.json` | current |
| Provider install / model provisioning | `edi install` (with `--model` or interactive TTY selection), `edi models pull/verify` | current (`paddle-ocr`, `qwen3-vl` installable) |
| Fleet status across runtimes | `edi ps` (host, VRAM tier, provider/model/server states; `--json` / API `status.summary`) | current |
| Local inference servers (ollama / lmstudio / vllm) | `edi serve list/recommend/plan/install` (confirm-gated) | current |
| Processing log inspection | `edi log [--tail N] [--follow] [--pretty]` | current |
| Schema migrations | `python scripts/apply_migrations.py --dsn ...` | current (not an `edi` command) |
| Single-file document processing with page audit | `edi process <file>` → JSON report + JSONL processing log | current |
| Standard JSON input/output API | `edi api` (stdin/stdout request-response) | current |
| Web panel (read + confirm-gated install/serve) | `edi web --port 4099 [--bind ...]` (local `http.server`) | current (Overview: doctor/status/catalog, Servers: serve list/recommend/plan/install, Install page, verify ops reserved) |
| Full pipeline submit/review | library code + PostgreSQL | **planned** as commands/service |
| Human review | library code + `human_review` tables | **planned** as commands/panel |
| Outbound delivery | `outbox_message` state machine (`DELIVERED`/`RETRY_PENDING`/`FAILED`) | **planned** inspection tooling |
| Tenant/application/authorization admin | raw SQL against `control_plane` tables | **planned** admin commands |

## 1. Routine operator loop

1. `edi doctor` — confirm the host, driver, and GPU visibility match intent.
2. `edi config` — confirm the effective paths/defaults; adjust once with
   `edi config --wizard` instead of re-typing flags.
3. `edi providers list` / `edi models list` — confirm declared catalog.
4. After any runtime change: `edi ps` (single view of runtimes, models, servers, and
   the advisory VRAM tier), or inspect the profile's `install-state.json`
   (status `READY` or `FAILED`).
5. `edi models verify <model_id>` — after provisioning or before an offline handover.
6. `edi process <file>` — process a document and keep the JSONL audit trail
   (`.edi/logs/processing.jsonl`): file identity + sha256, per-page line/character
   analysis, and total page count appear in both the JSON output and the log; follow it
   live with `edi log --follow`.
7. Optional local inference server: `edi serve recommend` (advisory) → `edi serve plan`
   (inspect the exact vector) → `edi serve install --yes`.
8. Run the suite after upgrades: `python -m pytest` through the project virtual
   environment, or `scripts/test-docker.sh` to run it inside Docker (WSL/Linux).

Do not rely on memory for state: the state files under `.edi/` are the source of truth
for runtime and model readiness.

## 2. Operating rules that must never be bent

- **No silent fallback.** An `nvidia` profile fails closed on a host without a
  compatible runtime. Never "fix" a failed GPU install by quietly switching a profile.
- **Model pinning.** Production ProcessingProfiles pin provider/model identity; an
  upstream default change must not alter an active profile
  (`INSTALLATION.md` §7).
- **State semantics.** `WARMED` / `UPSTREAM_CACHE` ≠ offline-pinned. Before an
  air-gapped handover, validate local artifacts while network is still available
  (`INSTALLATION.md` §11).
- **Isolation.** Provider packages stay in their runtimes; core `.venv` stays clean.
- **Immutability.** Completed result versions are immutable; reprocessing creates a new
  processing/result version (`AGENTS.md`).
- **Human correction** never overwrites original machine provenance; AI/model output is
  evidence/prediction, never business authorization (`AGENTS.md`).

## 3. Consumer application flows (integrator view)

Architecture and authorization boundaries: `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md`.

Planned end-to-end shape (evidence: schema in `migrations/0002`–`0016`):

1. **Register** tenant and application; grant provider authorization
   (`tenant`, `application`, `provider_*_authorization`). Today: raw SQL — planned admin
   command.
2. **Submit** an inbound document with explicit `tenant_id`, `application_id`,
   `request_id`, idempotency key (`inbound_request`, `document`). Today: library —
   planned command/service.
3. **Process** — execution plan/attempt records track parse/OCR → classify → extract →
   normalize → validate → evidence (`execution_plan`, `processing_result`,
   `evidence_reference`). Provider selection flows ProcessingProfile → ExecutionPolicy →
   ExecutionPlan; it is never chosen implicitly.
4. **Review** — human review actions attach alongside, never replacing, machine
   provenance (`human_review`, `human_review_action`).
5. **Deliver** — results/events/callbacks leave through the outbox with states
   `DELIVERED` / `RETRY_PENDING` / `FAILED`; a callback failure must not convert a
   completed result into failure.

Identity rules: `tenant_id`, `application_id`, `request_id`, `correlation_id`,
`idempotency_key`, `document_id`, `processing_run_id`, and `result_version` are not
interchangeable. Document content is untrusted data and never chooses callback
destinations.

## 4. What the control panel will add

Read-only runtime visibility first, then privileged operations, then the data-plane
dashboard: [Web control panel](web-panel.md). Until then, `edi` plus the state files
are the control surface.

## See also

- [CLI reference](cli-reference.md)
- `../REQUIREMENTS-ANALYSIS.md` — gap register and phased requirements
- `docs/RI-5.0-POSTGRESQL-CONTROL-PLANE.md` — durable control-plane slice
