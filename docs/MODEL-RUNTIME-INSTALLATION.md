# Model Runtime Installation Strategy\n\nFor executable operator commands, start with `INSTALLATION.md`. This document defines runtime architecture and isolation policy.

Model runtimes are deployment capabilities, not core domain dependencies.

## Rules

1. Core correctness MUST NOT depend on a GPU or a specific model vendor.
2. PaddlePaddle and PyTorch/VLM stacks MUST be isolated into separate environments or containers.
3. Model weights MUST be treated as versioned deployment artifacts. Production deployments SHOULD pin model revision and integrity metadata and MAY pre-download weights for offline operation.
4. Runtime selection MUST flow through ProcessingProfile -> ExecutionPolicy -> ExecutionPlan. Model code MUST NOT choose an unconfigured provider.
5. CPU fallback MUST remain possible for required platform capabilities unless a tenant profile explicitly requires an accelerator.
6. GPU access is optional and provider-specific. NVIDIA/CUDA, Apple MPS, other accelerators, and remote inference are capability implementations, not domain concepts.

## Initial provider baseline

| Capability | Provider/model | Role | Install boundary |
|---|---|---|---|
| OCR | PaddleOCR / PP-OCRv6 medium | primary OCR candidate | Paddle worker |
| OCR compatibility | PaddleOCR / PP-OCRv5 server | compatibility/benchmark candidate | Paddle worker |\n| Document structure | PaddleOCR / PP-StructureV3 | primary structure candidate | Paddle worker |
| Document parsing | Docling | parser challenger/composition | Docling worker |
| Vision-language | Qwen2.5-VL-7B-Instruct | primary local VLM baseline | PyTorch VLM worker |
| Vision-language | Qwen2.5-VL-3B-Instruct | constrained-hardware fallback | PyTorch VLM worker |
| OCR/layout | Surya | benchmark challenger | isolated PyTorch worker |
| OCR | Tesseract or ONNX-based provider | lightweight deterministic fallback | optional worker |
| Remote inference | configured provider | optional external execution | no local model |

No model in this table is authoritative business logic.

## Installation profiles

### Core

Installs only the reference service and database adapter requirements. No ML framework is required.

### Paddle CPU

Install a supported PaddlePaddle 3.x CPU package first, then PaddleOCR. Pin versions in the deployable image/environment.

### Paddle NVIDIA

Use a PaddlePaddle GPU build compatible with the host NVIDIA driver, then install PaddleOCR. Docker deployments MUST explicitly expose the GPU to the container.

### Qwen VLM

Use an isolated PyTorch/Transformers environment. GPU and quantized variants are deployment choices. Do not install this stack into the Paddle worker merely to share a Python environment.

### Docling

Install in its own worker environment when enabled. Accelerator selection is deployment configuration.

### Surya

Install in its own PyTorch environment when enabled. Do not let Surya's Transformers/PyTorch constraints govern the Qwen worker.

## Docker topology

```text
core-api                 CPU
worker-paddle-cpu        CPU
worker-paddle-nvidia     NVIDIA GPU
worker-qwen-vl           CPU or NVIDIA GPU
worker-docling           CPU or accelerator
worker-surya             optional benchmark worker
postgres                 CPU
```

GPU workers are replaceable capability providers. The same core service MUST operate when they are absent.

## Offline/on-premise operation

Production and restricted-network deployments SHOULD support:

- pre-downloaded model artifacts;
- pinned model revisions;
- integrity metadata/checksums where the upstream distribution supports them;
- configurable model/cache directories;
- startup without public-network access after required artifacts are provisioned;
- explicit failure when a configured model artifact is unavailable rather than silently selecting another model.

## OS support

Core tests target Linux, Windows, and macOS.

Model-provider support is declared independently:

- Linux: preferred production container/GPU target.
- Windows: supported core target; GPU providers depend on their upstream runtime and may run natively or through Docker/WSL2.
- macOS: supported core target; provider acceleration may use CPU/MPS when supported.
- Containers: preferred production isolation boundary for ML runtimes.

Cross-platform support does not imply identical accelerator support on every OS.
