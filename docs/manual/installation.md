# Installation Quickstart

Condensed path for a fresh host. The authoritative, full runbook — per-OS flows,
PostgreSQL, offline constraints, verification checklist — is
[`INSTALLATION.md`](../../INSTALLATION.md). Do not skip its troubleshooting section.

## 1. Prerequisites

- Git, Python 3.12, pip.
- Optional: NVIDIA driver + Docker/WSL2 for GPU profiles.
- Verify the host before anything else:

```text
tlkdoc doctor
```

`tlkdoc doctor` is a read-only probe. It prints JSON host information including
`nvidia_gpu` when detected.

## 2. Bootstrap the core

Linux / macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

One-shot bootstrap (same steps in a single command, `--force` to rebuild an
existing venv, `--check` to add `pytest` + `tlkdoc doctor`):

```bash
scripts/bootstrap.sh              # Linux/macOS
```
```powershell
.\scripts\bootstrap.ps1           # Windows PowerShell
```

Verify:

```text
python -m pytest
edi --help
tlkdoc providers list
tlkdoc models list
```

Never install Paddle/PyTorch/Docling/Surya into this core environment.

Alternative with [uv](https://docs.astral.sh/uv/) (source tree only, no PyPI publish):

```bash
uvx --from . tlkdoc doctor     # run directly from the checkout
uv tool install .           # or install `tlkdoc` as a tool
```

One-time defaults (paths, provider, profile, model, web bind/port) can be stored in
`.edi/config.json` instead of re-typing flags: `tlkdoc config --wizard`
(precedence: explicit flag > config > built-in default).

## 3. Inspect, then install a provider runtime

Always dry-run first (this creates nothing):

```text
tlkdoc install --provider paddle-ocr --profile cpu --dry-run
```

GPU host (requires a detected driver; fails closed otherwise):

```text
tlkdoc install --provider paddle-ocr --profile nvidia --dry-run
```

Execute only after reviewing the plan:

```text
tlkdoc install --provider paddle-ocr --profile cpu --yes
```

The runtime is created under `.edi/runtimes/<provider>/<profile>/venv` with an atomic
`install-state.json`. A successful install records status `READY`; a failure records
`FAILED` with an `error_code`.

## 4. Provision a model

```text
tlkdoc models pull pp-ocrv6-medium --profile cpu --yes
tlkdoc models verify pp-ocrv6-medium
```

`models pull` requires the matching provider profile to be `READY` first. Current model
state is recorded as `WARMED` with storage `UPSTREAM_CACHE` — this is an upstream cache
claim, not an offline-pinned artifact claim. See `INSTALLATION.md` §6 for state
semantics and §7 for production profile pinning.

## 5. PostgreSQL (optional / integration)

```bash
python -m pip install -e ".[dev,postgres]"
python scripts/apply_migrations.py --dsn "$EDI_TEST_POSTGRES_DSN"
```

Migration and integration-test commands live in `README.md` (Development section).

## 6. Final verification

```text
python -m pytest
tlkdoc doctor
tlkdoc ps
tlkdoc providers list
tlkdoc models list
tlkdoc models verify pp-ocrv6-medium
```

Then walk the checklist in `INSTALLATION.md` §11. For restricted/offline environments,
validate local model artifacts **before** removing public network access.

## Next

- Command details: [CLI reference](cli-reference.md).
- Failures: [Troubleshooting index](troubleshooting.md).
