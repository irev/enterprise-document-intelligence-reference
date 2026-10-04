"""Trusted installation recipe for the Qwen3-VL transformers runtime.

Recipes are code-owned typed argv sequences. Provider manifests and management
API input never contain executable shell strings.

The recipe follows the upstream Qwen3-VL requirements: a recent PyTorch build,
``transformers>=4.57.0`` and ``qwen-vl-utils``. The ``quantized`` profile adds
``bitsandbytes`` for low-VRAM inference; it still requires an NVIDIA runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

from edi_reference.application.paddle_install import InstallStep

SUPPORTED_PROFILES = frozenset({"cpu", "nvidia", "quantized"})


@dataclass(frozen=True, slots=True)
class Qwen3VlInstallPlan:
    profile: str
    python_version: str
    steps: tuple[InstallStep, ...]
    verify_argv: tuple[str, ...]


def build_qwen3_vl_install_plan(
    *,
    python_executable: str,
    profile: str,
) -> Qwen3VlInstallPlan:
    if profile not in SUPPORTED_PROFILES:
        raise ValueError("UNSUPPORTED_QWEN3_VL_PROFILE")

    steps: list[InstallStep] = [
        InstallStep(
            "upgrade-pip",
            (python_executable, "-m", "pip", "install", "--upgrade", "pip"),
        ),
    ]
    if profile == "nvidia":
        steps.append(
            InstallStep(
                "install-torch",
                (
                    python_executable,
                    "-m",
                    "pip",
                    "install",
                    "torch>=2.4",
                    "--index-url",
                    "https://download.pytorch.org/whl/cu126",
                ),
            )
        )
    else:
        steps.append(
            InstallStep(
                "install-torch",
                (python_executable, "-m", "pip", "install", "torch>=2.4"),
            )
        )
    if profile == "quantized":
        steps.append(
            InstallStep(
                "install-quantization",
                (python_executable, "-m", "pip", "install", "bitsandbytes>=0.43"),
            )
        )
    steps.append(
        InstallStep(
            "install-qwen3-vl",
            (
                python_executable,
                "-m",
                "pip",
                "install",
                "transformers>=4.57.0",
                "qwen-vl-utils",
            ),
        )
    )
    return Qwen3VlInstallPlan(
        profile=profile,
        python_version="3.12",
        steps=tuple(steps),
        verify_argv=(
            python_executable,
            "-c",
            "import torch, transformers; print(transformers.__version__)",
        ),
    )
