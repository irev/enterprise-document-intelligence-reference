# Installation Guide

This is the operational installation runbook for the Enterprise Document Intelligence reference implementation.

> The core application and ML providers use separate environments. Do **not** install PaddlePaddle, PaddleOCR, PyTorch/Qwen, Docling, or Surya into the core project virtual environment.

## 1. Prerequisites

Required for the core:

- Git
- Python 3.12 compatible with the project metadata
- pip
- PostgreSQL only when durable persistence/integration testing is required

Optional provider prerequisites:

- NVIDIA driver for the `nvidia` Paddle profile
- Docker/WSL2 when chosen as the deployment isolation boundary

Check the host first:

```text
python --version
python -m pip --version
```

After the package is installed, use:

```text
edi doctor
```

`edi doctor` reports the host OS/architecture, Docker availability, and detected NVIDIA runtime/driver information. It does not install or modify the host.

## 2. Install the core

Create a dedicated core virtual environment.

### Linux / macOS

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Verify:

```text
python -m pytest
edi --help
edi doctor
edi providers list
edi models list
```

The core environment MUST remain independent from provider-specific ML dependencies.

## 3. PostgreSQL support

For PostgreSQL adapter work:

```text
python -m pip install -r requirements-postgres.txt
```

For development plus PostgreSQL:

```text
python -m pip install -e ".[dev,postgres]"
```

Use a disposable database for integration tests. See `docs/LOCAL-DEVELOPMENT.md` for migration and test commands.

## 4. Inspect provider installation

Always inspect the plan before executing a provider installation.

CPU:

```text
edi install --provider paddle-ocr --profile cpu --dry-run
```

NVIDIA:

```text
edi install --provider paddle-ocr --profile nvidia --dry-run
```

The dry-run MUST NOT create the provider runtime or install packages.

The installer resolves a trusted, code-owned argument vector. The CLI/Web control plane does not accept arbitrary shell commands, executable URLs, or package-manager command strings.

## 5. Install PaddleOCR runtime

Provider runtimes are created below:

```text
.edi/
  runtimes/
    paddle-ocr/
      cpu/
        venv/
      nvidia/
        venv/
```

### CPU

```text
edi install --provider paddle-ocr --profile cpu --yes
```

### NVIDIA

First confirm `edi doctor` detects `nvidia-smi` and a driver version. Then:

```text
edi install --provider paddle-ocr --profile nvidia --yes
```

The current trusted Paddle recipe installs a pinned PaddlePaddle engine and a constrained PaddleOCR release range with document-parser support. GPU package selection is resolved from the detected NVIDIA driver. A requested NVIDIA profile fails closed when a compatible NVIDIA runtime is not detected; it does not silently fall back to CPU.

Installation state is written atomically to:

```text
.edi/runtimes/paddle-ocr/<profile>/install-state.json
```

State contains operational metadata and step return codes. Installer stdout/stderr is intentionally not persisted because package-manager output can contain sensitive repository information.

A partial failure is recorded as `FAILED`; a successful install is recorded as `INSTALLED`.

## 6. Provision Paddle models

List the governed model catalog:

```text
edi models list
```

Current Paddle catalog:

| Model ID | Purpose |
|---|---|
| `pp-ocrv6-medium` | default OCR candidate |
| `pp-ocrv5-server` | compatibility/benchmark OCR candidate |
| `pp-structure-v3` | document structure/layout candidate |

Warm the default OCR model after the Paddle runtime is installed:

```text
edi models pull pp-ocrv6-medium --profile cpu --yes
```

For the NVIDIA runtime:

```text
edi models pull pp-ocrv6-medium --profile nvidia --yes
```

The default upstream source is Hugging Face. The supported alternative is:

```text
edi models pull pp-ocrv6-medium --profile cpu --source BOS --yes
```

Verify the recorded artifact metadata:

```text
edi models verify pp-ocrv6-medium
```

### Important model-state semantics

The current model operation warms Paddle/PaddleX-managed upstream cache. Therefore the state is deliberately:

```text
status  = WARMED
storage = UPSTREAM_CACHE
```

It MUST NOT be interpreted as:

```text
READY
LOCAL_PINNED
OFFLINE_VERIFIED
```

`edi models verify` currently verifies the reference implementation's resolved-model manifest/provenance integrity. It does **not** claim that every upstream weight file has been copied, pinned, or cryptographically verified.

Production offline deployment requires a later/local-pinned artifact workflow with explicit model directories and weight integrity metadata. Until that workflow reports a local-pinned state, do not assume the deployment can start without network/cache availability.

## 7. Production model policy

Production ProcessingProfile versions MUST explicitly select the provider/model configuration. Do not depend on the upstream PaddleOCR default model.

The platform rule is:

```text
configured model identity
        ↓
versioned ProcessingProfile
        ↓
ExecutionPolicy / ExecutionPlan
        ↓
explicit provider construction
        ↓
OCR execution
```

An upstream release or default-model change MUST NOT silently alter an active production profile.

## 8. Runtime isolation rules

Keep these runtime families separate:

```text
core       -> .venv
PaddleOCR  -> .edi/runtimes/paddle-ocr/...
Qwen/VLM   -> separate PyTorch runtime
Docling    -> separate runtime
Surya      -> separate PyTorch runtime
```

Do not combine all ML providers into one Python environment to save disk space. Their dependency constraints and accelerator stacks evolve independently.

GPU acceleration is optional. Core platform correctness MUST NOT depend on GPU availability.

## 9. Windows, WSL2, Linux, and macOS

The core is cross-platform and CI-tested on Windows, Linux, and macOS.

For ML providers:

- Linux is the preferred production/container GPU target.
- Windows may use a supported native provider runtime or an isolated WSL2/Docker deployment.
- WSL2 is a valid Linux deployment boundary when NVIDIA GPU passthrough is configured.
- macOS remains a supported core target; provider acceleration depends on the individual provider.
- Never assume that identical accelerator profiles are available on every OS.

Use `edi doctor` on the actual execution host. Do not select a GPU profile from development-machine assumptions.

## 10. Troubleshooting

### `NVIDIA_RUNTIME_NOT_DETECTED`

Run:

```text
edi doctor
nvidia-smi
```

Do not force the NVIDIA profile when the runtime is unavailable. Use the CPU profile or correct the host GPU/runtime configuration.

### `NVIDIA_DRIVER_VERSION_REQUIRED`

`nvidia-smi` was detected but the installer could not resolve a usable driver version. Correct the NVIDIA installation before retrying.

### `NVIDIA_DRIVER_TOO_OLD`

The detected driver is below the trusted recipe's supported floor. Upgrade the host driver or use the CPU profile.

### `INSTALL_STEP_FAILED:<step>`

The isolated runtime was created but one installation step failed. Inspect the package-manager output from the interactive run and the redacted `install-state.json`. Correct the root cause and rerun the same provider/profile installation.

Do not manually install packages into the core `.venv` as a workaround.

### `PADDLE_RUNTIME_NOT_INSTALLED`

Install the requested Paddle profile before running `edi models pull`.

### `MODEL_WARM_FAILED`

Check network access, upstream model source availability, runtime package health, and free disk space. Retry with the same model/source after correcting the cause.

### `MODEL_ARTIFACT_INTEGRITY_MISMATCH`

The local provenance manifest changed after it was recorded. Treat the state as invalid and reprovision it. Do not bypass verification.

## 11. Verification checklist

Before declaring a host ready:

- core tests pass;
- `edi doctor` matches the intended host;
- the requested provider profile installs successfully;
- `install-state.json` reports `INSTALLED`;
- required model operations report the expected governed state;
- no provider silently falls back to a different execution class/profile;
- production ProcessingProfile pins the intended provider/model configuration;
- restricted/offline environments have separately validated local model artifacts before public network access is removed.

## 12. Related documentation

- `docs/LOCAL-DEVELOPMENT.md` — developer bootstrap and PostgreSQL testing.
- `docs/MODEL-RUNTIME-INSTALLATION.md` — provider/runtime architecture and isolation policy.
- `docs/RUNTIME-CONTROL-PLANE.md` — shared CLI/Web management boundary.
- `AGENTS.md` — repository engineering rules.
