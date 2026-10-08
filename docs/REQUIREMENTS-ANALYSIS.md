# Project Requirements Analysis — Installation, Usage, Control Panel, Manual

Status: reference-implementation planning document. This document is not a normative
specification. It records observed repository state, gaps, and phased requirements for
operator tooling. Where behavior is contract-relevant, the Enterprise Document
Intelligence specification takes precedence.

Evidence references use `path:line` against the repository at the time of writing.

## 1. Purpose and audiences

This analysis covers the project from installation through daily usage, and defines the
requirements for two control surfaces (CLI and WEB) plus a usage manual.

Audiences:

- **Operator** — installs core and provider runtimes, provisions models, verifies hosts,
  operates air-gapped/on-prem deployments.
- **Developer** — runs the deterministic test suite, typecheck, and local PostgreSQL
  integration flows.
- **Consumer application integrator/admin** — registers applications, submits documents,
  inspects processing, and reviews results through the shared service
  (`docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:9-19`).

The shared-service model has three logical planes — data plane, control plane, and
processing plane (`docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:41-76`). A control panel
exposes the control plane; it must not contain payment approval or other business
authorization (`docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:123`).

## 2. Installation requirements

### 2.1 Current operator flow

`INSTALLATION.md` is the operator runbook. Its required sequence:

1. Prerequisites and `tlkdoc doctor` as a read-only host probe (`INSTALLATION.md:7-34`).
2. Core bootstrap in `.venv`; core must stay independent of ML dependencies
   (`INSTALLATION.md:36-68`).
3. Optional PostgreSQL adapter install and disposable test database
   (`INSTALLATION.md:70-84`).
4. Mandatory `--dry-run` inspection before any provider install; installer resolves a
   trusted, code-owned argv — never shell strings or URLs (`INSTALLATION.md:86-104`).
5. Isolated provider runtime install below `.edi/runtimes/<provider>/<profile>/venv`
   with atomic `install-state.json` (`INSTALLATION.md:106-142`).
6. Model provisioning via `tlkdoc models pull` / `tlkdoc models verify`
   (`INSTALLATION.md:146-205`).
7. Production ProcessingProfile pinning of model identity (`INSTALLATION.md:207-225`).
8. Runtime isolation rules; GPU optional, correctness MUST NOT depend on it
   (`INSTALLATION.md:227-241`).
9. Per-OS flows with fail-closed GPU selection (`INSTALLATION.md:243-456`).
10. Error-specific troubleshooting (`INSTALLATION.md:458-543`).
11. Verification checklist (`INSTALLATION.md:545-556`).

### 2.2 Required behaviors (normative for tooling)

| Requirement | Source |
|---|---|
| ML provider packages never enter the core `.venv` | `INSTALLATION.md:5`, `:68`, `:227-241` |
| NVIDIA profile fails closed; no silent CPU fallback | `INSTALLATION.md:134`, `deploy/runtime-profiles/providers.yaml:30` |
| Installer state written atomically; stdout/stderr not persisted | `INSTALLATION.md:136-142` |
| Browser/CLI inputs are identifiers only; trusted typed argv on the server | `docs/RUNTIME-CONTROL-PLANE.md:5,21-31` |
| Model identity pinned in production profiles; upstream default changes must not alter active profiles | `docs/RUNTIME-CONTROL-PLANE.md:35` |
| Offline deployments validate local artifacts before network removal | `INSTALLATION.md:556`, `docs/MODEL-RUNTIME-INSTALLATION.md:69-78` |

### 2.3 Installation gaps

| ID | Gap | Evidence |
|---|---|---|
| G2 | Migration/test commands pointer is wrong: `INSTALLATION.md:84` defers to `docs/LOCAL-DEVELOPMENT.md`, which contains no migration/test commands (they are in `README.md:89-106`). No `tlkdoc` migration subcommand exists; schema setup requires `python scripts/apply_migrations.py --dsn ...`. | `scripts/apply_migrations.py:68-74` |
| G9 | Offline/air-gap not delivered: model pull records `WARMED` / `UPSTREAM_CACHE` only, which MUST NOT be read as `READY`/`LOCAL_PINNED`/`OFFLINE_VERIFIED`. | `INSTALLATION.md:186-205`; `src/edi_reference/application/paddle_models.py:128` |
| G10 | Doc/code drift: `INSTALLATION.md:144` and `:552` claim `install-state.json` reports `INSTALLED`; code writes `READY` on success and `FAILED` on failure, and `cli.py:163` gates on `READY`. `INSTALLED` appears nowhere in `src/`. | `src/edi_reference/application/runtime_management.py:136,148` |
| G11 | Formatting defects in operator docs (historical; repaired with this change set). | `README.md:126`; `docs/MODEL-RUNTIME-INSTALLATION.md:1,19` |

## 3. Usage requirements

### 3.1 Operator flows

Available today (all read-only or explicitly confirmed):

- inspect host, list providers, list models, plan/install a provider profile, pull/verify
  a model (see §4.1 inventory).

Required but missing:

| Need | Gap |
|---|---|
| Fleet status: list installed runtimes and model states with readiness across providers/profiles (only per-model `models verify` exists) | G3 |
| Uninstall / rollback / upgrade / repair / cache cleanup commands | G4 |
| Tenant, application, provider-authorization, and profile administration — currently PostgreSQL tables only, requiring raw SQL | G7 |
| Consistent machine-readable output: only `tlkdoc doctor` emits JSON; `providers list` / `models list` are plain text with no `--json` | G8 |
| A migration command inside `tlkdoc` (today a separate script) | G2 |

### 3.2 Developer flows

- Bootstrap and suite: `README.md:76-106` (`pip install -e ".[dev]"`, `python -m pytest`,
  conditional PostgreSQL integration via `EDI_TEST_POSTGRES_DSN`).
- Typecheck: `python -m mypy src/edi_reference` under Python 3.12
  (`README.md:108-122`).
- Constraints: deterministic tests without network/model/provider access
  (`AGENTS.md`, rule 13); tests run only through the repository virtual environment.

### 3.3 Consumer application flows

The data plane (submit → ingest → process → review → results → events) exists as library
code and PostgreSQL schema (`migrations/0002`–`0016`: `inbound_request`, `document`,
`processing_run`, `processing_result`, `human_review`, `outbox_message`, …) but has **no
executable anchor**: no `tlkdoc` subcommand, no worker runner entry point, no HTTP endpoint.
A usage manual cannot demonstrate day-to-day document processing yet (G5).

### 3.4 GPU detection and advisory model recommendation

Requirement (carried from the GPU-tier work in this project):

1. `tlkdoc doctor` (or a new `tlkdoc recommend` view) detects GPU name, VRAM, and — where
   available — compute capability from `nvidia-smi` (`src/edi_reference/cli.py`,
   host capability inspection in `src/edi_reference/adapters/host_capabilities.py`).
2. A **configuration file** (extension of `src/edi_reference/runtime/providers.toml` or a
   sibling tier map) maps hardware tiers to recommended provider profiles/models.
   Customer- or hardware-specific behavior stays in configuration, never in code branches.
3. Output is **advisory only**. The panel must not select or switch providers
   automatically: provider selection flows `ProcessingProfile → ExecutionPolicy →
   ExecutionPlan` (`docs/MODEL-RUNTIME-INSTALLATION.md:10`) and silent fallback is
   forbidden (`providers.yaml:30`).
4. Unknown hardware yields an explicit `UNKNOWN` tier, never a guess (`AGENTS.md`, rule 5).

**Shipped**: the sibling tier map exists (`src/edi_reference/runtime/tiers.toml`,
`application/tier_map.py`, bands `cpu` / `gpu-low` / `gpu-mid` / `gpu-high`) and is
surfaced by `tlkdoc config`, `tlkdoc ps`, `tlkdoc serve recommend`, and the API operations
`status.summary` / `serve.recommend`. It stays advisory: no code path selects a
provider from a tier.

Note: recommended candidates discussed in this project (for example newer OCR/VL models)
are not all installable — `providers.toml` / `providers.yaml` declare seven providers
(`paddle-ocr`, `paddleocr-vl`, `qwen3-vl`, `qwen25-vl-7b`, `qwen25-vl-3b`, `docling`,
`surya`); `paddle-ocr` and `qwen3-vl` implement installers, `paddleocr-vl` is
catalog-only (fail-closed). Catalog extension is a manifest change, not a code change.

## 4. Control panel: CLI

### 4.1 Current command inventory

Entry point `edi = "edi_reference.cli:main"` (`pyproject.toml:14-15`). Complete surface
(`src/edi_reference/cli.py`):

| Command | Arguments / flags | Output |
|---|---|---|
| `tlkdoc doctor` | none | JSON host info incl. `nvidia_gpu` |
| `tlkdoc config` | `--wizard`, `--json`, `--config` | config listing / interactive `.edi/config.json` editor |
| `tlkdoc log` | `--path`, `--tail`, `--follow`, `--pretty` | JSONL log lines |
| `tlkdoc ps` | `--json`, `--runtime-root`, `--model-root` | status summary incl. VRAM tier (API `status.summary`) |
| `tlkdoc providers list` | none | `id: profiles` lines |
| `tlkdoc models list` (alias `tlkdoc model`) | none | `provider: model` lines |
| `tlkdoc models pull <model_id>` | `--profile` (default `cpu`), `--source {HUGGINGFACE,BOS}`, `--yes`, `--runtime-root`, `--model-root` | model-state |
| `tlkdoc models verify <model_id>` | `--model-root` | verification result |
| `tlkdoc install` | `--provider`, `--profile` (config defaults; required otherwise), `--dry-run`, `--yes`, `--model`, `--model-source`, `--runtime-root`, `--model-root` | plan / install result, optionally `{"install":..., "model":...}` |
| `tlkdoc serve list/recommend/plan/install` | `--server`, `--via {auto,native,docker}`, `--gpu {auto,on,off}`, `--variant {desktop,headless}` (lmstudio docker), `--model`, `--yes`, `--json`, roots | registry / advisory verdicts / typed vector (+ `start_hint`) / install result |
| `tlkdoc process <path>` | `--profile`, `--model`, `--runtime-root`, `--model-root`, `--log`, `--timeout` | JSON page-analysis report + JSONL processing log |
| `tlkdoc api [request]` | JSON request argument or stdin | `{ok, operation, result\|error}` envelope |

Cross-cutting CLI rules:

- `install` and `models pull` require explicit `--yes`; the stdio API equivalent is
  `params.confirm: true` (→ `CONFIRMATION_REQUIRED`).
- Incompatible runtime exits before execution (`RUNTIME_INCOMPATIBLE` or the specific
  reason code); `models pull`/`process` gate on runtime status `READY`
  (`PADDLE_RUNTIME_NOT_READY`).
- `paddle-ocr` and `qwen3-vl` are installable today; the remaining providers return
  `RUNTIME_REQUIREMENT_NOT_IMPLEMENTED` / `INSTALLER_NOT_IMPLEMENTED_FOR_PROVIDER`
  (`application/runtime_requirements.py`).
- `tlkdoc process` runs inference through the runtime interpreter with a trusted
  code-owned script (document bytes are data, never executed); failures are logged as
  `FILE_PROCESSING_FAILED` before exit 2.

### 4.2 Required CLI additions

| Priority | Addition | Serves | Status |
|---|---|---|---|
| P1 | Standard JSON-over-stdio API (`tlkdoc api`) dispatching to the same operations as the CLI | G8, panel Phase 0 | **shipped** |
| P1 | Web panel (`tlkdoc web`, stdlib `http.server`, read-only Overview + confirm-gated Install page, default `127.0.0.1:4099`) | G1 (partial), panel Phase 1–2 | **shipped** |
| P1 | `tlkdoc process` — single-file processing, per-page analysis + total pages in output and JSONL processing log | G5 (partial), audit | **shipped** |
| P1 | `tlkdoc install --model` + interactive TTY model selection during install | operator UX | **shipped** |
| P1 | `tlkdoc ps` — aggregate `install-state.json` + `model-state.json` + server detection across the installation (API `status.summary`) | G3 | **shipped** (delivers the `tlkdoc status` requirement) |
| P1 | `--json` on `providers list` / `models list` (stable machine-readable shape) | G8, panel Phase 1 | planned (stdio API covers machine consumers) |
| P1 | `tlkdoc config` — effective configuration view + `--wizard` editor writing `.edi/config.json` (flag > config > default) | operator UX | **shipped** |
| P1 | `tlkdoc log` — processing JSONL viewer (`--tail`, `--follow`, `--pretty`) | G5 (audit UX) | **shipped** |
| P2 | `tlkdoc serve` — local inference server registry/detect/recommend/plan/install (`ollama`, `lmstudio`, `vllm`), native + whitelisted Docker vectors, confirm-gated (API `serve.*`) | operator UX | **shipped** |
| P2 | GPU tier view: detect VRAM → advisory recommendation from config tier map (§3.4) | operator UX | **shipped** (`runtime/tiers.toml`) |
| P2 | `uvx` / `uv tool` run instructions (source tree only; no PyPI publish) | developer UX | **shipped** (cli-reference) |
| P2 | `tlkdoc migrate` wrapper over `scripts/apply_migrations.py` (same trusted argv) | G2 | planned |
| P3 | Administration commands for tenant/application/authorization/profile scoped to the control-plane tables | G7 | planned |
| P3 | Lifecycle commands: uninstall, verify-provider (mirror of reserved Web op) | G4, `RUNTIME-CONTROL-PLANE.md` | planned |

### 4.3 Shared-operations contract

CLI and Web Admin MUST call the same runtime-management application operations; the Web
layer MUST NOT accept shell commands, package-manager arguments, executable paths, or
installer URLs (`docs/RUNTIME-CONTROL-PLANE.md:5`). This means Phase 1 web work is an
adapter over the same application services `tlkdoc` already uses — not a second
implementation.

## 5. Control panel: WEB (phased)

Before this change set there was no HTTP surface anywhere in `src/` or `deploy/`; a
stdlib read-only adapter now exists (`adapters/web_panel.py`, served by `tlkdoc web`). A
deployed service (auth, roles, metrics) is still a future milestone (RI-5.5)
(`docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:136,147`).

### Phase 0 — CLI parity (prerequisite)

Partially **shipped**: `tlkdoc api` provides the standard JSON request/response envelope
over the same operations, `tlkdoc process` provides the page-audit report + JSONL
processing log, and `tlkdoc ps` + the GPU tier view close the two Phase 0 read gaps
(every Phase 1 web read maps 1:1 to a CLI/API operation, per the shared-operations
contract). Remaining: nothing inside Phase 0 itself; `status.summary` / `serve.*` still
need local panel routes.

### Phase 1 — read-only runtime views — partially shipped

`tlkdoc web` (stdlib `http.server`, default bind `127.0.0.1`, port 4099) implements:

- `GET /admin/runtime/host`, `GET /admin/runtime/providers`,
  `GET /admin/runtime/models`,
  `POST /admin/runtime/providers/{id}/install-plans` (plan only)
  (`docs/RUNTIME-CONTROL-PLANE.md:11-14`).

Still planned for this phase: authenticated non-local deployment. Remaining phases:

- `GET /admin/runtime/host`, `GET /admin/runtime/providers`, `GET /admin/runtime/models`,
  `POST /admin/runtime/providers/{id}/install-plans` (plan only, no execution)
  (`docs/RUNTIME-CONTROL-PLANE.md:11-14`).
- Read-only by construction: no mutation endpoints in this phase.
- Rationale: this is the smallest slice that delivers operator visibility without
  crossing the privileged execution boundary.

### Phase 2 — execution operations — partially shipped

- Shipped on the local panel: confirm-gated execute provider install and pull model
  (`confirm: true` ≡ `--yes`, identifiers only) with staged plan → install → download
  animation; CLI equivalents show TTY-only stderr spinners
  (`docs/RUNTIME-CONTROL-PLANE.md:15,17`).
- Still reserved: verify provider/model, and all execution on a deployed Web Admin.
- Requirements when the deployed boundary is lifted: authenticated admin identity,
  full audit via `configuration_audit`.

### Phase 3 — data-plane operations dashboard

- Module IA from `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:106-123`: Dashboard,
  Inbound, Processing, Documents, Review, Outbound, Findings, Applications, Tenants,
  Providers, Profiles/Policies, Audit — reading the `control_plane`, `ingestion`,
  `integration`, and `processing` schema (`migrations/0001`–`0016`).
- Control-plane authorization is independent of UI visibility
  (`docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:63`).
- No payment approval or business authorization in the panel
  (`docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:123`).

### 5.1 Implementation options and constraints

| Constraint | Source |
|---|---|
| Domain/application core stays independent of web frameworks; new dependency only for a concrete capability, kept outside the domain boundary (adapters layer) | `AGENTS.md:19,48`; `README.md:14-17` |
| Option A (default): stdlib `http.server` adapter for local panel JSON/HTML (reads + confirm-gated execution) — no new dependency, adequate for a single-admin on-prem panel | `README.md:14` |
| Option B: optional framework extra (e.g. `.[web]`) only when Phase 2+ needs auth middleware/streaming; never a core dependency | `AGENTS.md`, dependency policy |
| Requests carry identifiers only; server resolves trusted plans | `docs/RUNTIME-CONTROL-PLANE.md:23-31` |
| Bind `127.0.0.1` by default; explicit configuration to expose; authentication required before any non-local bind | security baseline |
| Air-gap: no CDN assets, no external fonts/scripts; fully local static assets | project deployment context |
| Secrets (integration credentials) never exposed in panel views or logs | `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:130` |
| Fail-closed and UNKNOWN/OOD outcomes preserved in every view | `AGENTS.md`, rules 5 and 9 |

## 6. Usage manual requirements

A usage manual now exists at `docs/manual/` (this document's change set added it);
before that, operator docs covered installation only and 57 of 64 `docs/*.md` files
were architecture ADRs (original gap G5).

Requirements:

- English (repository convention; `AGENTS.md` confidentiality rules apply).
- Location: `docs/manual/` with an index page; linked from `README.md`.
- Every demonstrated command must exist in code; planned features are labeled
  explicitly (e.g. `status: planned`) so the manual never promises unavailable behavior.
- No duplication of `INSTALLATION.md`: quickstart pages link into the runbook.
- Page map: index; installation quickstart; CLI reference; operations (day-to-day,
  honest about the missing data-plane anchor); web panel (phase placeholder);
  troubleshooting index.

## 7. Gap register

| ID | Gap | Target |
|---|---|---|
| G1 | No HTTP/web surface at all | Partially shipped: local `tlkdoc web` (Phase 1 reads + confirm-gated Phase 2 install/pull); verify ops, deployed admin, Phase 3 remainder (§5) |
| G2 | No `tlkdoc` migration command; wrong doc pointer | CLI P2; pointer repaired in this change set |
| G3 | No fleet status command | **shipped** as `tlkdoc ps` + API `status.summary` |
| G4 | No uninstall/rollback/upgrade/repair commands | CLI P3 |
| G5 | Data-plane executable anchor; usage manual | Manual shipped; `tlkdoc process` (single-file + page-audit log), `tlkdoc api`, and `tlkdoc log` shipped; full submit/review pipeline remains a future milestone |
| G6 | Only `paddle-ocr` installable despite declared providers | Partially shipped: `paddle-ocr` + `qwen3-vl` installable of 7 declared; remaining providers (incl. catalog-only `paddleocr-vl`) out of scope |
| G7 | No tenant/application/authorization admin CLI | CLI P3 / Phase 3 |
| G8 | No auth/roles, logging, metrics; JSON only from `doctor` | Partially shipped: stdio JSON API, JSONL processing log, `ps`/`serve`/`config --json`; auth/roles/metrics remain |
| G9 | Offline/air-gap model pinning not delivered (`WARMED` ≠ `OFFLINE_VERIFIED`) | Model-state workflow (separate milestone) |
| G10 | `INSTALLED` vs `READY` doc/code drift | Repaired in this change set |
| G11 | Formatting defects in operator docs | Partially repaired here (`README.md:126`); `docs/MODEL-RUNTIME-INSTALLATION.md:1,19` remains |

## 8. Non-functional requirements

- **Fail-closed**: unsupported host/runtime combinations fail; no silent fallback to a
  different execution class (`INSTALLATION.md:134,283,442`).
- **Runtime isolation**: core correctness never depends on GPU or provider packages
  (`INSTALLATION.md:5,241`).
- **Determinism**: tests run without network/model/provider access (`AGENTS.md`, rule 13).
- **Confidentiality**: no production identifiers, credentials, or private-source material
  in any doc, panel view, or log (`AGENTS.md`; `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:130`).
- **Spec-first**: contract-relevant behavior is verified against the specification
  repository before change (`AGENTS.md`); note the specification repository is not
  available locally in this workspace and must be consulted remotely when contracts are
  touched.
- **Immutability/authorization invariants**: completed result versions immutable; AI/model
  output is evidence, never business authorization (`AGENTS.md`, rules 6–10).

## 9. Out of scope

- Remaining CLI additions (`tlkdoc migrate`, admin/lifecycle commands) and any web phase;
  this change set shipped only the items marked **shipped** in §4.2 plus the
  documentation repairs.
- Hardware/air-gap sizing recommendations produced in the separate blueprint review
  effort (not part of this repository).
- Implementing missing providers (G6) and offline model pinning (G9).

## 10. Related documentation

- `docs/manual/README.md` — usage manual index.
- `INSTALLATION.md` — operator runbook.
- `docs/RUNTIME-CONTROL-PLANE.md` — shared CLI/Web operation contract.
- `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md` — service model and panel module IA.
- `AGENTS.md` — engineering rules.
