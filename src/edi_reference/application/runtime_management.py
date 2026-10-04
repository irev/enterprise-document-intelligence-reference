"""Shared control-plane application service for CLI and Web/API adapters."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from edi_reference.application.paddle_install import build_paddle_install_plan
from edi_reference.application.provider_manifest import ProviderManifest
from edi_reference.application.runtime_bootstrap import CompatibilityStatus, ResolvedRuntime, RuntimeEnvironment
from edi_reference.application.runtime_installer import (
    InstallExecutionResult,
    InstallStepFailed,
    ensure_runtime_venv,
    execute_steps,
    query_python_version,
    verify_runtime,
    write_install_state,
)


class RuntimeManagementService:
    def __init__(self, manifest: ProviderManifest) -> None:
        self._manifest = manifest

    def providers(self) -> list[dict[str, object]]:
        return [
            {
                "provider_id": item.provider_id,
                "runtime_family": item.runtime_family,
                "capabilities": list(item.capabilities),
                "profiles": list(item.profiles),
                "models": list(item.models),
                "required": item.required,
            }
            for item in self._manifest.providers.values()
        ]

    def models(self) -> list[dict[str, str]]:
        return [
            {"provider_id": provider.provider_id, "model_id": model}
            for provider in self._manifest.providers.values()
            for model in provider.models
        ]

    def plan_install(
        self,
        *,
        provider_id: str,
        profile: str,
        host: Any,
        python_executable: str,
    ) -> dict[str, object]:
        definition = self._manifest.providers.get(provider_id)
        if definition is None:
            raise ValueError("UNKNOWN_PROVIDER")
        if profile not in definition.profiles:
            raise ValueError("UNSUPPORTED_PROVIDER_PROFILE")
        host_data = asdict(host)
        if profile == "nvidia" and not host_data.get("nvidia_smi"):
            raise ValueError("NVIDIA_RUNTIME_NOT_DETECTED")
        if profile == "mps" and host_data.get("os") != "darwin":
            raise ValueError("MPS_REQUIRES_MACOS")
        payload: dict[str, object] = {
            "provider": provider_id,
            "profile": profile,
            "host": host_data,
            "execution": "isolated-runtime",
            "status": "PLANNED",
        }
        if provider_id == "paddle-ocr":
            paddle = build_paddle_install_plan(
                python_executable=python_executable,
                profile=profile,
                nvidia_driver_version=host_data.get("nvidia_driver_version"),
            )
            payload["steps"] = [
                {"name": step.name, "argv": list(step.argv)} for step in paddle.steps
            ]
            payload["verify_argv"] = list(paddle.verify_argv)
        return payload

    def install_provider(
        self,
        *,
        provider_id: str,
        profile: str,
        host: Any,
        runtime_root: Path,
        resolved_runtime: ResolvedRuntime,
    ) -> InstallExecutionResult:
        if provider_id != "paddle-ocr":
            raise ValueError("INSTALLER_NOT_IMPLEMENTED_FOR_PROVIDER")
        if (
            resolved_runtime.status is not CompatibilityStatus.COMPATIBLE
            or resolved_runtime.provider_id != provider_id
            or resolved_runtime.profile != profile
            or resolved_runtime.python is None
            or resolved_runtime.environment is not RuntimeEnvironment.NATIVE
        ):
            raise ValueError("COMPATIBLE_RUNTIME_RESOLUTION_REQUIRED")

        runtime_dir = runtime_root / provider_id / profile
        python_path = ensure_runtime_venv(
            runtime_dir,
            base_python=resolved_runtime.python.executable,
        )
        actual_python_version = query_python_version(python_path)
        expected = resolved_runtime.python.version[:2]
        actual_parts = tuple(int(item) for item in actual_python_version.split(".")[:2])
        if actual_parts != expected:
            raise ValueError("RUNTIME_PYTHON_VERSION_MISMATCH")

        python_executable = str(python_path)
        self.plan_install(
            provider_id=provider_id,
            profile=profile,
            host=host,
            python_executable=python_executable,
        )
        paddle = build_paddle_install_plan(
            python_executable=python_executable,
            profile=profile,
            nvidia_driver_version=asdict(host).get("nvidia_driver_version"),
        )
        try:
            steps = execute_steps(paddle.steps)
            verification = verify_runtime(paddle.verify_argv)
            python_version = query_python_version(python_path)
        except (InstallStepFailed, RuntimeError) as exc:
            failed = InstallExecutionResult(
                provider_id=provider_id,
                profile=profile,
                runtime_dir=str(runtime_dir),
                status="FAILED",
                steps=(),
                error_code=str(exc),
                runtime_python=str(python_path),
            )
            write_install_state(runtime_dir, failed)
            raise

        result = InstallExecutionResult(
            provider_id=provider_id,
            profile=profile,
            runtime_dir=str(runtime_dir),
            status="READY",
            steps=steps + (verification,),
            runtime_python=str(python_path),
            runtime_python_version=python_version,
        )
        write_install_state(runtime_dir, result)
        return result
