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
tlkdoc doctor
```

`tlkdoc doctor` reports the host OS/architecture, Docker availability, and detected NVIDIA runtime/driver information. It does not install or modify the host.

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
tlkdoc doctor
tlkdoc providers list
tlkdoc models list
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

Use a disposable database for integration tests. See `README.md` (Development section) for migration and test commands.

## 4. Inspect provider installation

Always inspect the plan before executing a provider installation.

CPU:

```text
tlkdoc install --provider paddle-ocr --profile cpu --dry-run
```

NVIDIA:

```text
tlkdoc install --provider paddle-ocr --profile nvidia --dry-run
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
tlkdoc install --provider paddle-ocr --profile cpu --yes
```

### NVIDIA

First confirm `tlkdoc doctor` detects `nvidia-smi` and a driver version. Then:

```text
tlkdoc install --provider paddle-ocr --profile nvidia --yes
```

The current trusted Paddle recipe installs a pinned PaddlePaddle engine and a constrained PaddleOCR release range with document-parser support. GPU package selection is resolved from the detected NVIDIA driver. A requested NVIDIA profile fails closed when a compatible NVIDIA runtime is not detected; it does not silently fall back to CPU.

Installation state is written atomically to:

```text
.edi/runtimes/paddle-ocr/<profile>/install-state.json
```

State contains operational metadata and step return codes. Installer stdout/stderr is intentionally not persisted because package-manager output can contain sensitive repository information.

A partial failure is recorded as `FAILED`; a successful install is recorded as `READY`.

Model provisioning can be part of the same install run: pass `--model <model_id>` to pull it immediately after the runtime reports `READY`, or run interactively on a TTY without `--model` to choose from a numbered catalog menu (press `q` to skip; non-interactive sessions without `--model` install the runtime only). See `docs/manual/cli-reference.md` for details.

## 6. Provision Paddle models

List the governed model catalog:

```text
tlkdoc models list
```

Current Paddle catalog:

| Model ID | Purpose |
|---|---|
| `pp-ocrv6-medium` | default OCR candidate |
| `pp-ocrv5-server` | compatibility/benchmark OCR candidate |
| `pp-structure-v3` | document structure/layout candidate |

Warm the default OCR model after the Paddle runtime is installed:

```text
tlkdoc models pull pp-ocrv6-medium --profile cpu --yes
```

For the NVIDIA runtime:

```text
tlkdoc models pull pp-ocrv6-medium --profile nvidia --yes
```

The default upstream source is Hugging Face. The supported alternative is:

```text
tlkdoc models pull pp-ocrv6-medium --profile cpu --source BOS --yes
```

Verify the recorded artifact metadata:

```text
tlkdoc models verify pp-ocrv6-medium
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

`tlkdoc models verify` currently verifies the reference implementation's resolved-model manifest/provenance integrity. It does **not** claim that every upstream weight file has been copied, pinned, or cryptographically verified.

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

## 9. Operating-system installation

The core is cross-platform and CI-tested on Windows, Linux, and macOS. Provider support is a separate capability: a supported core OS does not imply that every ML accelerator is supported on that OS.

| Host | Core | Paddle CPU | Paddle NVIDIA | Recommended use |
|---|---|---|---|---|
| Windows 11 native | supported | provider-dependent | verify upstream/runtime compatibility first | development and administration |
| Windows 11 + WSL2 Ubuntu | supported inside Linux guest | supported when runtime recipe resolves | preferred Windows NVIDIA path when GPU passthrough is healthy | GPU development/workstation |
| Ubuntu/Debian Linux | supported | supported when runtime recipe resolves | preferred GPU deployment target | production |
| RHEL/Rocky/AlmaLinux | supported | supported when compatible Python/runtime is supplied | provider/runtime-dependent | enterprise Linux |
| macOS Intel | supported | provider-dependent | not applicable | core development |
| macOS Apple Silicon | supported | provider-dependent | not applicable | core development; provider acceleration evaluated separately |
| Docker Linux | supported deployment boundary | supported image/profile | preferred with NVIDIA Container Toolkit when enabled | reproducible production |

Always run `tlkdoc doctor` on the actual execution host. Never select an accelerator profile based only on the development machine.

### 9.1 Windows 11 native

Use PowerShell and a dedicated Python 3.12 core environment:

```powershell
git clone <repository>
cd enterprise-document-intelligence-reference
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest
tlkdoc doctor
```

Install the Paddle CPU profile only after inspecting the plan:

```powershell
tlkdoc install --provider paddle-ocr --profile cpu --dry-run
tlkdoc install --provider paddle-ocr --profile cpu --yes
tlkdoc models pull pp-ocrv6-medium --profile cpu --yes
tlkdoc models verify pp-ocrv6-medium
```

Do not assume that native Windows NVIDIA installation is equivalent to Linux CUDA installation. The installer MUST fail closed when it cannot resolve a supported host/runtime combination. Prefer WSL2 or Docker for NVIDIA workloads when native provider compatibility is uncertain.

### 9.2 Windows 11 with WSL2

Install/enable WSL2 and an Ubuntu distribution using the normal Windows administration process. Inside the Linux guest, verify the environment rather than assuming Windows host capability is inherited:

```bash
uname -a
python3 --version
nvidia-smi
```

Then bootstrap the repository inside the Linux filesystem:

```bash
git clone <repository>
cd enterprise-document-intelligence-reference
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest
tlkdoc doctor
```

For NVIDIA, inspect the resolved plan first:

```bash
tlkdoc install --provider paddle-ocr --profile nvidia --dry-run
tlkdoc install --provider paddle-ocr --profile nvidia --yes
tlkdoc models pull pp-ocrv6-medium --profile nvidia --yes
tlkdoc models verify pp-ocrv6-medium
```

If `nvidia-smi` is unavailable inside WSL2, correct GPU passthrough/driver configuration before attempting the NVIDIA profile. Do not install arbitrary CUDA/Paddle packages into the core `.venv` as a workaround.

### 9.3 Ubuntu / Debian Linux

Install the operating-system prerequisites using the distribution package manager. Exact Python package names vary by release; the required project interpreter is Python 3.12 compatible with project metadata.

Example after Python/Git are available:

```bash
git clone <repository>
cd enterprise-document-intelligence-reference
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest
tlkdoc doctor
```

CPU:

```bash
tlkdoc install --provider paddle-ocr --profile cpu --dry-run
tlkdoc install --provider paddle-ocr --profile cpu --yes
tlkdoc models pull pp-ocrv6-medium --profile cpu --yes
```

NVIDIA:

```bash
nvidia-smi
tlkdoc install --provider paddle-ocr --profile nvidia --dry-run
tlkdoc install --provider paddle-ocr --profile nvidia --yes
tlkdoc models pull pp-ocrv6-medium --profile nvidia --yes
```

Linux is the preferred production/container GPU target. Host NVIDIA driver installation remains an infrastructure responsibility; the EDI installer provisions the isolated provider runtime, not the host kernel driver.

### 9.4 RHEL / Rocky Linux / AlmaLinux

Do not copy Debian `apt` commands to RPM-based systems. Provision Git, Python 3.12, Python venv support, compiler/system libraries when required, and PostgreSQL client/development dependencies through the organization's approved repositories.

Once a compatible interpreter exists, the application bootstrap remains:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest
tlkdoc doctor
```

Provider installation then uses the same governed `tlkdoc install --dry-run` and `tlkdoc install --yes` workflow. NVIDIA host-driver/repository configuration MUST follow the enterprise Linux platform policy and the provider's supported compatibility matrix.

### 9.5 macOS Intel

Bootstrap the core with a Python 3.12 interpreter supplied by the organization's approved package manager/runtime manager:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest
tlkdoc doctor
```

macOS Intel is a supported core-development target. Do not select the `nvidia` profile. Paddle/provider installation is conditional on upstream support for the exact macOS/Python combination.

### 9.6 macOS Apple Silicon

Use a native ARM64 Python where possible and verify architecture:

```bash
uname -m
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest
tlkdoc doctor
```

The core does not require Rosetta. Do not assume MPS availability for Paddle because another PyTorch-based provider supports MPS. Accelerator capability is provider-specific and must be declared by that provider/runtime profile.

### 9.7 Docker CPU

Docker is an isolation/deployment boundary, not a domain dependency. A production image should keep the core and each ML runtime independently replaceable.

Recommended topology:

```text
core-api
worker-paddle-cpu
postgres
```

Persist provider/model data outside ephemeral container layers:

```text
/runtime-data  -> provider runtime/state
/model-data    -> governed model/cache/artifacts
```

Do not bake credentials into an image or accept arbitrary installer commands through a management API.

### 9.8 Docker NVIDIA

Recommended topology:

```text
core-api
worker-paddle-nvidia
postgres
```

The host must expose NVIDIA GPU capability to Docker through the supported NVIDIA container runtime/toolkit. Verify GPU visibility inside the worker container before provider installation:

```text
nvidia-smi
tlkdoc doctor
```

Then use the same governed NVIDIA dry-run/install/model workflow. A container that cannot see the GPU MUST fail the NVIDIA profile rather than silently switching execution class.

### 9.9 OS-independent verification

After installation on any supported host:

```text
python -m pytest
tlkdoc doctor
tlkdoc providers list
tlkdoc models list
tlkdoc models verify pp-ocrv6-medium
```

For a production host, also verify the intended ProcessingProfile, runtime state, model-state semantics, network/offline assumptions, and PostgreSQL connectivity where applicable.

## 10. Troubleshooting

### Windows: mypy fails with `librt.base64` or another `librt` module

This failure belongs to the **development/typecheck toolchain** unless an EDI source diagnostic is also reported. `librt` is not an application capability and MUST NOT be added to the EDI core or provider dependency set as a workaround.

The validated repository typecheck baseline is Python 3.12. First determine which interpreter is actually running mypy:

```powershell
where.exe python
python --version
python -c "import sys; print(sys.executable)"
python -m pip --version
python -m mypy --version
```

The interpreter should resolve inside this repository's `.venv\Scripts\python.exe` and report Python 3.12.

If it does not, recreate the environment explicitly:

```powershell
deactivate 2>$null
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python --version
python -m mypy src/edi_reference
```

Prefer `python -m mypy` over a bare `mypy` command so the executable and installed module are tied to the same selected interpreter.

If the error persists in a clean Python 3.12 project environment, capture these diagnostics before changing dependencies:

```powershell
python -m pip show mypy librt
python -m pip check
python -c "import sys, mypy; print(sys.executable); print(mypy.__file__)"
```

Then compare against the Windows CI typecheck for the same commit. If CI succeeds but the local clean environment fails, investigate local package cache/environment corruption. If Windows CI fails with the same bootstrap/import error, treat it as a pinned development-toolchain compatibility issue and fix the dev dependency constraints centrally.

Do not:

- install Paddle/PyTorch/provider packages into the core environment to fix mypy;
- add `librt` as an EDI runtime dependency solely for mypy;
- disable typechecking for Windows to hide the bootstrap failure;
- interpret a mypy bootstrap failure as an EDI source type error without a source diagnostic.

### `NVIDIA_RUNTIME_NOT_DETECTED`

Run:

```text
tlkdoc doctor
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

Install the requested Paddle profile before running `tlkdoc models pull`.

### `MODEL_WARM_FAILED`

Check network access, upstream model source availability, runtime package health, and free disk space. Retry with the same model/source after correcting the cause.

### `MODEL_ARTIFACT_INTEGRITY_MISMATCH`

The local provenance manifest changed after it was recorded. Treat the state as invalid and reprovision it. Do not bypass verification.

## 11. Verification checklist

Before declaring a host ready:

- core tests pass;
- `tlkdoc doctor` matches the intended host;
- the requested provider profile installs successfully;
- `install-state.json` reports `READY`;
- required model operations report the expected governed state;
- no provider silently falls back to a different execution class/profile;
- production ProcessingProfile pins the intended provider/model configuration;
- restricted/offline environments have separately validated local model artifacts before public network access is removed.

## 12. Related documentation

- `docs/LOCAL-DEVELOPMENT.md` — developer bootstrap and PostgreSQL testing.
- `docs/MODEL-RUNTIME-INSTALLATION.md` — provider/runtime architecture and isolation policy.
- `docs/RUNTIME-CONTROL-PLANE.md` — shared CLI/Web management boundary.
- `AGENTS.md` — repository engineering rules.
