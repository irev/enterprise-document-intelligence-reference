# CLI Reference

Complete reference for the `tlkdoc` command-line entry point
(`pyproject.toml` → `edi_reference.cli:main`). Flags and behavior are fixed as of the
RI-5.13 code base; anything listed as **planned** does not exist yet.

`tlkdoc` is the command name. `edi`, the former name, is installed as an alias with
identical behavior so existing scripts keep working. Internal names are unchanged: the
Python package `edi_reference`, the state directory `.edi/`, `EDI_*` environment
variables and container names.

## Global conventions

- Confirmation: mutating commands require `--yes`; without it they stop with
  `INSTALL_CONFIRMATION_REQUIRED_USE_YES` or `MODEL_PULL_CONFIRMATION_REQUIRED_USE_YES`.
- Fail-closed: incompatible runtimes abort before execution (exit code 2,
  `RUNTIME_INCOMPATIBLE` or a specific reason code). There is no silent CPU fallback.
- Roots: `--runtime-root` (default `.edi/runtimes`) and `--model-root` (default
  `.edi/models`) let you point at alternate trees.
- Stored defaults: `tlkdoc config --wizard` writes `.edi/config.json`; every flag then
  follows **flag > config > built-in default** (`tlkdoc install`, `tlkdoc models pull`,
  `tlkdoc process`, `tlkdoc web`). Invalid config entries are dropped with a warning, never
  silently trusted.
- Machine-readable output: `doctor`, `models pull`, `models verify`, `install`,
  `process`, `config --json`, `ps --json`, `serve * --json` and `tlkdoc api` emit JSON;
  `providers list` and `models list` are plain text.
  For a uniform request/response contract use [`tlkdoc api`](#edi-api-stdin--stdout-json-api).

### Running with uv / uvx

No PyPI publish is planned; from a checkout (or any directory containing the project):

```text
uvx --from . tlkdoc doctor            # run the CLI directly from the source tree
uv tool install .                  # install `tlkdoc` into an isolated uv tool environment
uvx --with ".[dev]" pytest         # run the test suite without a manual venv
```

## `tlkdoc doctor`

Read-only host probe. Prints JSON: OS/Python facts plus `nvidia_gpu` details
(executable presence, driver version) when detected.

```text
tlkdoc doctor
```

Use it before any NVIDIA install. Exit behavior is informational; GPU absence does not
fail the core.

## `tlkdoc providers list`

Lists declared providers and their profiles:

```text
tlkdoc providers list
```

Output shape: `provider_id: profile1,profile2,...` per line, from
`src/edi_reference/runtime/providers.toml`. Declaring a provider does not mean it is
installable: `paddle-ocr` and `qwen3-vl` currently implement the installer; the other
entries (including `paddleocr-vl`) are catalog-only and report
`RUNTIME_REQUIREMENT_NOT_IMPLEMENTED` / `INSTALLER_NOT_IMPLEMENTED_FOR_PROVIDER` if you
attempt installation.

## `tlkdoc config`

Shows the effective local configuration — stored file, resolved defaults, host facts,
VRAM tier, and provider/server install status — or edits it interactively.

```text
tlkdoc config [--wizard] [--json] [--config PATH]
```

| Flag | Meaning |
|---|---|
| `--wizard` | Numbered-step editor: paths → provider → profile → model → source → web bind/port → review → save (requires stdin to be a TTY; otherwise `WIZARD_REQUIRES_TTY`, exit 2). `q` or a declined save cancels with `WIZARD_CANCELLED`. |
| `--json` | Emit the machine-readable payload instead of the human-readable listing. |
| `--config` | Config file path (default `.edi/config.json`). |

The file stores *defaults* only: explicit flags always win. Reads are fail-safe — a
missing, unreadable, or invalid file yields built-in defaults with a warning; execution
commands keep validating their own inputs fail-closed.

## `tlkdoc log`

Reads the append-only processing JSONL log written by `tlkdoc process`.

```text
tlkdoc log [--path PATH] [--tail N] [--follow] [--pretty]
```

| Flag | Default | Meaning |
|---|---|---|
| `--path` | config `log_path`, else `.edi/logs/processing.jsonl` | Log file to read. |
| `--tail` | `50` | Print only the last N lines (`0` prints the whole file). |
| `--follow` | — | Keep streaming new lines (1 s poll; Ctrl+C stops, exit 0). |
| `--pretty` | — | Pretty-print JSON lines; non-JSON lines are passed through unchanged. |

Missing file → `LOG_NOT_FOUND` (exit 2). The log is data: never execute its contents.

## `tlkdoc ps`

One-shot status summary across the local installation: host facts, VRAM tier, provider
runtime states, model provisioning states, and local inference server detection.

```text
tlkdoc ps [--json] [--runtime-root PATH] [--model-root PATH]
```

Statuses come from the state files only — `READY` / `FAILED` / `NOT_INSTALLED` for
provider runtimes, `WARMED` / `NOT_PROVISIONED` / `UNKNOWN` for models, `INSTALLED` /
`NOT_INSTALLED` / `UNKNOWN` for servers; unreadable state yields `UNKNOWN`, never an
optimistic `READY`. The tier comes from `runtime/tiers.toml` and is advisory
(`UNKNOWN` when VRAM is unknown). The same payload is available as API operation
`status.summary`.

## `tlkdoc models list`

Lists catalog entries as `provider: model_id` per line.
`tlkdoc model ...` is an alias of `tlkdoc models ...`.

## `tlkdoc models pull <model_id>`

Warms a model into the governed local cache.

```text
tlkdoc models pull <model_id> [--profile cpu|nvidia] [--source HUGGINGFACE|BOS] [--yes]
                           [--runtime-root PATH] [--model-root PATH]
```

| Flag | Default | Meaning |
|---|---|---|
| `--profile` | `cpu`, or config `profile` | Provider profile the model is provisioned against; the profile must be installed (`READY`) or the command stops with `PADDLE_RUNTIME_NOT_READY`. |
| `--source` | config `model_source`, else `HUGGINGFACE` | Upstream source (`HUGGINGFACE` or `BOS`). |
| `--yes` | — | Required confirmation. |
| `--model-root` | config `model_root`, else `.edi/models` | Model state root. |

Without a positional `model_id` the config's `model_id` is used; if neither exists the
command stops with `MODEL_ID_REQUIRED` (exit 2).

Recorded state: `WARMED`, storage `UPSTREAM_CACHE`. This is **not** an
`OFFLINE_VERIFIED`/pinned claim; see `INSTALLATION.md` §6. On a TTY a spinner runs on
stderr while the pull executes; stdout JSON stays byte-identical either way.

## `tlkdoc models verify <model_id>`

Verifies local model provenance/integrity.

```text
tlkdoc models verify <model_id> [--model-root PATH]
```

Integrity failure surfaces as `MODEL_ARTIFACT_INTEGRITY_MISMATCH` — treat the state as
invalid and reprovision; never bypass verification.

## `tlkdoc install`

Plans or executes an isolated provider runtime install, with optional model
provisioning in the same run.

```text
tlkdoc install --provider ID --profile PROFILE [--dry-run] [--yes]
            [--model MODEL_ID] [--model-source HUGGINGFACE|BOS]
            [--runtime-root PATH] [--model-root PATH]
```

| Flag | Required | Meaning |
|---|---|---|
| `--provider` | unless set in config | Provider id from the manifest (e.g. `paddle-ocr`). |
| `--profile` | unless set in config | Execution profile (e.g. `cpu`, `nvidia`). |
| `--dry-run` | no | Print the resolved plan; creates nothing, installs nothing (no model step). |
| `--yes` | — | Required to execute. |
| `--model` | no | Provision this model right after a successful install (`READY`). |
| `--model-source` | no | Upstream source for the pull (`HUGGINGFACE` default, or `BOS`). |
| `--model-root` | no | Model state root (default `.edi/models`). |

Missing provider/profile (flag and config both empty) stops with `PROVIDER_REQUIRED` /
`PROFILE_REQUIRED`.

Guarantees:

- Resolves a trusted, code-owned argument vector; never accepts shell strings, package
  manager commands, or installer URLs.
- TTY-only progress animation on stderr (`Installing <provider>/<profile> runtime`,
  `Downloading model <model_id>`); stdout output and exit codes are unchanged when
  stderr is redirected or piped.
- Writes `install-state.json` atomically; success → status `READY`, failure → `FAILED`
  with `error_code` (installer stdout/stderr is intentionally not persisted).
- An `nvidia` profile on a host without a compatible runtime/driver fails closed
  (`NVIDIA_RUNTIME_NOT_DETECTED`, `NVIDIA_DRIVER_VERSION_REQUIRED`,
  `NVIDIA_DRIVER_TOO_OLD`).
- An unknown `--model` fails closed with `UNKNOWN_PADDLE_MODEL` **before** the runtime
  is executed.

### Model selection during install

After the runtime reports `READY`, the install command can continue into model
provisioning:

1. `--model <id>` given → that model is pulled immediately (non-interactive; scripts
   and Docker stay deterministic).
2. `--model` omitted and **stdin is a TTY** → a numbered menu of pullable catalog
   models is shown; pick one, or enter `q` to skip. Repeated invalid input fails
   closed with `INVALID_MODEL_SELECTION` after five attempts.
3. `--model` omitted and stdin is not a TTY → runtime install only; nothing prompts.

The combined output is one JSON document:

- with a model: `{"install": {...}, "model": {...}}`
- without a model: the install result object (unchanged from earlier releases).

## `tlkdoc serve` (local inference servers)

Detects, recommends, plans, and installs local inference servers — `ollama` (port
11434), `lmstudio` (port 1234), `vllm` (port 8000). All vectors are code-owned typed
argument vectors; the commands never accept shell strings or image references.

```text
tlkdoc serve list [--json] [--runtime-root PATH]
tlkdoc serve recommend [--json]
tlkdoc serve plan --server ID [--via auto|native|docker] [--gpu auto|on|off]
               [--variant desktop|headless] [--model MODEL_ID]
               [--runtime-root PATH] [--model-root PATH]
tlkdoc serve install --server ID [--via auto|native|docker] [--gpu auto|on|off]
                  [--variant desktop|headless] [--model MODEL_ID] [--yes]
                  [--runtime-root PATH] [--model-root PATH]
```

- **`list`** — registry, default port, Docker image (LM Studio's
  `linuxserver/lm-studio` is a **community image**, labelled as such), detection
  (`INSTALLED` / `NOT_INSTALLED` / `UNKNOWN` — PATH probe first, then the runtime
  binary under `--runtime-root`, then a `READY` `install-state.json`), and
  native-vector availability for this OS (`AUTOMATED` / `MANUAL` / `UNSUPPORTED` /
  `ALREADY_INSTALLED`).
- **`recommend`** — advisory tier verdicts from `runtime/tiers.toml`
  (`RECOMMENDED` / `NOT_RECOMMENDED` / `UNKNOWN`). Advisory only: it never selects
  providers or execution paths; provider selection stays in `ProcessingProfile →
  ExecutionPolicy → ExecutionPlan`.
- **`plan`** — read-only preview of the install vector (native argv or Docker run
  argv + image + verify) plus a `start_hint` describing how to start the server
  after install. Manual vectors (LM Studio native) return `automated: false` with
  `instructions` and their `error_code`. Ollama on Linux is an automated native
  vector: a trusted stdlib bootstrap (`python -m edi_reference.application.server_bootstrap
  ollama <runtime-root>/ollama/native`) downloads the vendor user-space tarball into
  `.edi/runtimes/` — no sudo, no shell.
- **`install`** — requires `--yes` (API equivalent: `serve.execute` with
  `confirm: true`). Executes the vector, verifies (`ollama --version`, import check,
  or `docker inspect` → `running`), and writes `install-state.json` under
  `.edi/runtimes/<server>/<via>/` — success `READY`, failure `FAILED` with
  `error_code`.

`--via auto` (default) prefers an automated native vector, then a ready Docker daemon,
then a manual vector plan; explicit `--via` bypasses the choice and fails closed:
`DOCKER_NOT_AVAILABLE`, `NVIDIA_CONTAINER_TOOLKIT_NOT_DETECTED` (GPU host without the
toolkit — no silent CPU degradation), `VLLM_REQUIRES_GPU`, `VLLM_UNSUPPORTED_ON_HOST`
(vLLM native install is Linux-only; use `--via docker` elsewhere),
`INSTALL_VECTOR_UNSUPPORTED`, `INSTALL_VECTOR_NOT_AUTOMATED`,
`INVALID_MODEL_ID` (vLLM requires `org/model` from `--model`).

`--gpu` expresses GPU intent for the vector: `auto` (default — GPU only when the host
probe reports NVIDIA, same fail-closed behavior as before), `on` (require the GPU and
the container toolkit, fail closed otherwise), `off` (explicit CPU vector: no
`--gpus=all`, toolkit probe skipped; vLLM still fails closed with `VLLM_REQUIRES_GPU`
because it is a GPU-only server). `--variant` selects the LM Studio Docker image —
`desktop` (default, `linuxserver/lm-studio` GUI) or `headless` (`lmstudio/llmster-preview`
API-only) — and is rejected with `INVALID_PARAMS` for other servers or non-Docker
vectors.

## `tlkdoc process <path>`

Processes one document file through the installed OCR runtime and reports page
analysis for audit.

```text
tlkdoc process <path> [--profile cpu|nvidia] [--model MODEL_ID]
            [--runtime-root PATH] [--model-root PATH]
            [--log PATH] [--timeout SECONDS]
```

| Flag | Default | Meaning |
|---|---|---|
| `--profile` | `cpu` | Installed runtime profile to use (must be `READY`). |
| `--model` | `pp-ocrv6-medium` | Pullable OCR model with governed local state. |
| `--log` | `.edi/logs/processing.jsonl` | Append-only JSONL processing log. |
| `--timeout` | `300` | Inference timeout in seconds (must be > 0). |

Behavior:

- Fail-closed gates: missing runtime state → `RUNTIME_STATE_NOT_FOUND`; runtime not
  `READY` → `PADDLE_RUNTIME_NOT_READY`; unusable/interrupted model state → the model
  verification code; missing file → `DOCUMENT_NOT_FOUND`; inference failure →
  `LOCAL_OCR_FAILED` / `LOCAL_OCR_TIMEOUT`.
- Runs inference through the **runtime interpreter** (isolated venv) with a
  trusted code-owned script; document bytes are written to a temporary file and are
  never executed.
- On success, prints one JSON report:

```json
{
  "file_id": "<sha256>",
  "source_name": "invoice.pdf",
  "sha256": "<sha256>",
  "status": "COMPLETED",
  "total_pages": 3,
  "pages": [
    {"page_number": 1, "line_count": 24, "character_count": 812}
  ],
  "log_path": ".edi/logs/processing.jsonl"
}
```

- Every run appends to the processing log (JSONL), one event per line:
  `FILE_PROCESSING_STARTED` (file identity + sha256), `PAGE_ANALYZED` (per page:
  `page_number`, `line_count`, `character_count`), `FILE_PROCESSING_COMPLETED`
  (`total_pages`, `pages_analyzed`); failures append `FILE_PROCESSING_FAILED`
  (`error_code`) before the command exits 2. Output and log therefore carry the same
  per-file audit information.

## `tlkdoc api` (stdin/stdout JSON API)

Standard input/output API: one JSON request in, one JSON response out. Commands and
the API execute the **same** operations
(`docs/RUNTIME-CONTROL-PLANE.md`).

```text
echo '{"operation": "doctor"}' | tlkdoc api
tlkdoc api '{"operation": "models.list"}'
```

Request: `{"operation": "<name>", "params": {...}}` — read from the optional
argument, otherwise from standard input.

Response: `{"ok": true, "operation": ..., "result": {...}}` on success (exit 0), or
`{"ok": false, "operation": ..., "error": {"code": "..."}}` (exit 2).

| Operation | Params | Notes |
|---|---|---|
| `doctor` | — | Same payload as `tlkdoc doctor`. |
| `providers.list` | — | `{"providers": [...]}`. |
| `models.list` | — | `{"models": [...]}`. |
| `models.verify` | `model_id`, `model_root?` | |
| `models.pull` | `model_id`, `profile?`, `source?`, `runtime_root?`, `model_root?`, **`confirm: true`** | Missing confirm → `CONFIRMATION_REQUIRED`. |
| `status.summary` | `runtime_root?`, `model_root?` | Same payload as `tlkdoc ps --json`. |
| `serve.list` | `runtime_root?` | Same payload as `tlkdoc serve list --json`. |
| `serve.recommend` | — | Same payload as `tlkdoc serve recommend --json` (advisory). |
| `serve.plan` | `server_id`, `via?` (`auto`\|`native`\|`docker`), `gpu?` (`auto`\|`on`\|`off`), `variant?` (`desktop`\|`headless`), `model?`, `runtime_root?`, `model_root?` | Read-only plan; unknown `via`/`gpu`/`variant` → `INVALID_PARAMS`. |
| `serve.execute` | `server_id`, `via?`, `gpu?`, `variant?`, `model?`, `runtime_root?`, `model_root?`, **`confirm: true`** | Same gates as `tlkdoc serve install`; identifiers only. |
| `install.plan` | `provider_id`, `profile`, `runtime_root?` | Read-only plan. |
| `install.execute` | `provider_id`, `profile`, **`confirm: true`**, `model?`, `model_source?`, `runtime_root?`, `model_root?` | Same gates as `tlkdoc install`; identifiers only. |
| `process.file` | `path`, `profile?`, `model?`, `runtime_root?`, `model_root?`, `log?`, `timeout?` | Same report as `tlkdoc process`. |

Other error codes: `INVALID_REQUEST` (malformed JSON), `UNKNOWN_OPERATION`,
`INVALID_PARAMS`, plus the operation's own fail-closed codes. The API never accepts
shell commands, executable paths to run, or installer URLs — only identifiers and
paths of files the operator already owns.

## `tlkdoc web`

Read-only local web panel over the same operations (stdlib `http.server`, no
framework):

```text
tlkdoc web [--bind 127.0.0.1] [--port 4099] [--runtime-root PATH]
```

| Flag | Default | Meaning |
|---|---|---|
| `--bind` (alias `--hostname`) | `127.0.0.1`, or config `web_bind` | Bind address. `0.0.0.0` exposes an **unauthenticated** read-only view — trusted networks only. |
| `--port` | `4099`, or config `web_port` | Listen port (`0` picks a free port). |
| `--runtime-root` | `.edi/runtimes` | Root used when resolving install plans. |

Serves `GET /` (HTML, three pages: Overview, Servers, and Install), the read routes
`GET /admin/runtime/{host,status,providers,models,servers}` and
`GET /admin/runtime/servers/recommendations`, plan
`POST /admin/runtime/providers/{id}/install-plans` and
`POST /admin/runtime/servers/{id}/install-plans`, and the confirm-gated execution
routes `POST /admin/runtime/providers/{id}/install`, `POST
/admin/runtime/models/{id}/pull`, and `POST /admin/runtime/servers/{id}/install`
(body must carry `{"confirm": true}`, else
`400 CONFIRMATION_REQUIRED`; the panel sends it automatically from the Install and
Servers pages).
Verify routes answer `403 RESERVED_OPERATION`. Prints the listening URL; stop with
Ctrl+C. Details: [Web control panel](web-panel.md).

## Not available yet (planned)

The following appear in `../REQUIREMENTS-ANALYSIS.md` as gaps — do not expect them from
`tlkdoc` today:

- `tlkdoc migrate` (schema migrations; use `python scripts/apply_migrations.py --dsn ...`)
  — planned.
- Uninstall / upgrade / rollback, tenant-application-authorization administration —
  planned.
- Data-plane commands (submit, review, worker run, batch queues) — planned;
  `tlkdoc process` covers single-file OCR processing with audit logging, and the durable
  pipeline remains library entry points only.

## See also

- [Installation quickstart](installation.md)
- [Troubleshooting index](troubleshooting.md)
- [`INSTALLATION.md`](../../INSTALLATION.md) — full runbook
