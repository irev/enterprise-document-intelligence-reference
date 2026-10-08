# Enterprise Document Intelligence — Python Reference Implementation

Reference implementation for the technology-neutral [Enterprise Document Intelligence specification](https://github.com/irev/enterprise-document-intelligence).

## Status

**RI-5.13 — Provider authorization security complete; durable processing hardening continues**

This repository demonstrates one possible implementation of the specification. It is **not** the normative source of platform behavior. When implementation behavior conflicts with the specification, the specification and its versioned contracts take precedence.

## Runtime

- Python 3.12 is the validated development/typecheck baseline
- Standard library first
- External dependencies are introduced only when a concrete capability requires them

No web framework, database, queue, OCR engine, model provider, or cloud platform is mandated by RI-0.

## Architecture

```text
Specification / schemas / conformance vectors
                    |
                    v
             Contract boundary
                    |
                    v
              Application core
                    |
          +---------+---------+
          |                   |
          v                   v
     Provider ports      Conformance reporting
          |
          v
   Replaceable adapters
```

Initial package boundaries:

- `domain` — implementation-neutral domain values and outcomes.
- `contracts` — references to specification versions and observable contract vocabulary.
- `application` — use-case orchestration; no provider SDK dependencies.
- `adapters` — replaceable parser/OCR/classifier/extractor/storage/provider integrations.
- `conformance` — machine-readable reporting primitives for specification conformance.

## RI-0 acceptance criteria

RI-0 is complete when the implementation can:

1. identify the specification and contract versions it targets;
2. declare supported capabilities;
3. represent explicit processing/result states without inventing business authorization;
4. represent conformance outcomes through provider-neutral machine-readable reporting;
5. emit a machine-readable conformance report shape;
6. run deterministic unit tests without OCR/model/network dependencies.

## Milestone progression

RI-0 through RI-4 established the portable contract, deterministic ingestion, parser/OCR, classification/extraction, and normalization/validation foundations.

RI-5 is the active durability and control-plane series. RI-5.0 through RI-5.13 cover PostgreSQL control-plane persistence, explicit provider authorization, durable inbound/outbox and source lineage, processing ownership/lease fencing, observation identity and referential integrity, long-running processing safety, and tenant-scoped provider authorization.

The next implementation work continues durable processing/result/evidence behavior before human review and shared-service production hardening.

## Confidentiality

This repository MUST NOT contain confidential corporate blueprints, source documents, organization/customer/vendor/person identities, internal system names, production identifiers, credentials, bank/tax identifiers, or source-derived material that can identify a private source.

Private material may inform validation privately. Only generalized, sanitized, non-identifying implementation requirements or test cases may be committed.

## Installation

The command-line tool is `tlkdoc`. The former name `edi` still works as an alias.

Use [`INSTALLATION.md`](INSTALLATION.md) for operator installation, isolated PaddleOCR runtime provisioning, model warm/verification, GPU profile selection, and troubleshooting. Usage guidance (quickstart, CLI reference, operations, troubleshooting index) lives in [`docs/manual/`](docs/manual/README.md). Do not install ML provider dependencies into the core development environment.

## Development

Use an activated project virtual environment for development commands.

The default suite installs development dependencies and runs the tests that do not require a live PostgreSQL DSN:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

One-shot setup for any supported OS (creates `.venv`, installs `requirements-dev.txt`):

```bash
scripts/bootstrap.sh              # Linux/macOS
```
```powershell
.\scripts\bootstrap.ps1           # Windows PowerShell
```

With [uv](https://docs.astral.sh/uv/) installed, the CLI can also be run straight from
the checkout without activating a virtual environment: `uvx --from . tlkdoc doctor`
(also `uvx --with ".[dev]" pytest`, or `uv tool install .` for a global `tlkdoc`).

PostgreSQL integration tests are conditional. If `EDI_TEST_POSTGRES_DSN` is not set, those tests are **skipped**; a default-suite success therefore does not by itself prove the durable PostgreSQL layer.

### Running the tests in Docker (WSL/Linux)

A containerized run builds the same suite on a clean Python 3.12 image — useful on
Windows through WSL2:

```bash
# inside WSL (or any Linux host with Docker)
scripts/test-docker.sh                                  # python -m pytest
scripts/test-docker.sh python -m ruff check src tests   # lint
scripts/test-docker.sh python -m mypy src/edi_reference # typecheck
```

From Windows: `wsl -d Ubuntu-22.04 -- bash /mnt/<drive>/repo/<repo>/scripts/test-docker.sh`.
The image is defined by `Dockerfile`; `.dockerignore` keeps `.venv`, `.edi`, and caches
out of the build context.

To run the PostgreSQL layer, install the adapter, point `EDI_TEST_POSTGRES_DSN` at a disposable test database, apply migrations through the versioned runner, then run the integration suite:

```bash
python -m pip install -e ".[dev,postgres]"
export EDI_TEST_POSTGRES_DSN="postgresql://edi:edi@localhost:5432/edi_test"

python scripts/apply_migrations.py --dsn "$EDI_TEST_POSTGRES_DSN"
python -m pytest tests/integration -vv
```

The migration runner discovers ordered `NNNN_*.sql` files automatically and records their filename and SHA-256 in `control_plane.schema_migration`. Applied versions are skipped on rerun; changing an already-applied migration fails checksum verification instead of silently accepting schema drift.

On Windows PowerShell, set `$env:EDI_TEST_POSTGRES_DSN = "postgresql://edi:edi@localhost:5432/edi_test"`, then run:

```powershell
python scripts/apply_migrations.py --dsn $env:EDI_TEST_POSTGRES_DSN
python -m pytest tests/integration -vv
```

## Windows mypy / `librt.base64` troubleshooting

Development and CI typechecking use **Python 3.12**. Run mypy through the active project interpreter:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python --version
python -m mypy src/edi_reference
```

If Windows reports an import/module error involving `librt.base64`, treat it first as a **mypy toolchain/environment problem**, not an EDI application dependency. Confirm that `python -m mypy` is using the project Python 3.12 virtual environment. Do **not** add `librt` to the core/runtime dependencies merely to make mypy start.

A machine-wide/default Python (for example a newer Python release) may resolve a different mypy/native dependency set than the validated project environment. Recreate the project `.venv` with Python 3.12 before investigating EDI source typing. See `INSTALLATION.md` for the full diagnostic procedure.

See `AGENTS.md` before making architecture or contract changes.

The implementation is intended to operate as a shared service for multiple authorized consumer applications. See `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md`.

## Installation

The core and ML provider runtimes are intentionally isolated. Do **not** install PaddlePaddle/PaddleOCR or other model stacks into the core `.venv`.

### 1. Bootstrap the core

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Verify the host and available providers:

```text
tlkdoc doctor
tlkdoc providers list
tlkdoc models list
```

### 2. Inspect, then install PaddleOCR

CPU:

```text
tlkdoc install --provider paddle-ocr --profile cpu --dry-run
tlkdoc install --provider paddle-ocr --profile cpu --yes
```

NVIDIA:

```text
tlkdoc doctor
tlkdoc install --provider paddle-ocr --profile nvidia --dry-run
tlkdoc install --provider paddle-ocr --profile nvidia --yes
```

Provider dependencies are installed into `.edi/runtimes/paddle-ocr/<profile>/venv`, not the core environment. NVIDIA installation fails closed when a compatible runtime/driver cannot be resolved; it does not silently downgrade to CPU.

### 3. Provision a governed OCR model

```text
tlkdoc models pull pp-ocrv6-medium --profile cpu --yes
tlkdoc models verify pp-ocrv6-medium
```

Use `--profile nvidia` when provisioning against the installed NVIDIA runtime. The current pull operation warms Paddle-managed upstream cache and records provenance as `WARMED / UPSTREAM_CACHE`; it does not yet claim offline-pinned model weights.

For PostgreSQL setup, model-source selection, WSL2/Linux guidance, offline/on-premise constraints, state files, troubleshooting, and the full verification checklist, read [`INSTALLATION.md`](INSTALLATION.md).

