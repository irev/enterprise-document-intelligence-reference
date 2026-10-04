"""Trusted installation recipes for the PaddleOCR runtime.

Recipes are code-owned typed argv sequences. Provider manifests and management
API input never contain executable shell strings.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstallStep:
    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PaddleInstallPlan:
    profile: str
    python_version: str
    steps: tuple[InstallStep, ...]
    verify_argv: tuple[str, ...]


def build_paddle_install_plan(
    *,
    python_executable: str,
    profile: str,
    nvidia_driver_major: int | None = None,
) -> PaddleInstallPlan:
    if profile == "cpu":
        engine = (
            python_executable,
            "-m",
            "pip",
            "install",
            "paddlepaddle==3.2.1",
            "-i",
            "https://www.paddlepaddle.org.cn/packages/stable/cpu/",
        )
    elif profile == "nvidia":
        if nvidia_driver_major is None:
            raise ValueError("NVIDIA_DRIVER_VERSION_REQUIRED")
        channel = "cu126" if nvidia_driver_major >= 550 else "cu118"
        engine = (
            python_executable,
            "-m",
            "pip",
            "install",
            "paddlepaddle-gpu==3.2.1",
            "-i",
            f"https://www.paddlepaddle.org.cn/packages/stable/{channel}/",
        )
    else:
        raise ValueError("UNSUPPORTED_PADDLE_PROFILE")

    return PaddleInstallPlan(
        profile=profile,
        python_version="3.12",
        steps=(
            InstallStep("upgrade-pip", (python_executable, "-m", "pip", "install", "--upgrade", "pip")),
            InstallStep("install-engine", engine),
            InstallStep(
                "install-paddleocr",
                (python_executable, "-m", "pip", "install", "paddleocr>=3.7,<3.8"),
            ),
        ),
        verify_argv=(
            python_executable,
            "-c",
            "import paddle, paddleocr; print(paddle.__version__)",
        ),
    )
