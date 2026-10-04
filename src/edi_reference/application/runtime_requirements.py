"""Code-owned runtime requirements for implemented provider installers."""

from edi_reference.application.runtime_bootstrap import (
    Accelerator,
    ProviderRuntimeRequirement,
    RuntimeEnvironment,
)


def provider_runtime_requirement(
    provider_id: str,
    profile: str,
    *,
    host_os: str,
) -> ProviderRuntimeRequirement:
    if provider_id == "qwen3-vl":
        return _qwen3_vl_requirement(profile)

    if provider_id != "paddle-ocr":
        raise ValueError("RUNTIME_REQUIREMENT_NOT_IMPLEMENTED")

    if profile == "cpu":
        return ProviderRuntimeRequirement(
            provider_id=provider_id,
            profile=profile,
            supported_os=frozenset({"linux", "windows", "darwin"}),
            python_min=(3, 12),
            python_max_exclusive=(3, 13),
            accelerator=Accelerator.CPU,
            environments=frozenset({RuntimeEnvironment.NATIVE}),
        )

    if profile == "nvidia":
        if host_os == "windows":
            raise ValueError("PADDLE_NVIDIA_REQUIRES_LINUX_RUNTIME")
        return ProviderRuntimeRequirement(
            provider_id=provider_id,
            profile=profile,
            supported_os=frozenset({"linux"}),
            python_min=(3, 12),
            python_max_exclusive=(3, 13),
            accelerator=Accelerator.NVIDIA,
            environments=frozenset({RuntimeEnvironment.NATIVE}),
        )

    raise ValueError("UNSUPPORTED_PADDLE_PROFILE")


def _qwen3_vl_requirement(profile: str) -> ProviderRuntimeRequirement:
    if profile == "cpu":
        return ProviderRuntimeRequirement(
            provider_id="qwen3-vl",
            profile=profile,
            supported_os=frozenset({"linux", "windows", "darwin"}),
            python_min=(3, 12),
            python_max_exclusive=(3, 13),
            accelerator=Accelerator.CPU,
            environments=frozenset({RuntimeEnvironment.NATIVE}),
        )

    if profile in {"nvidia", "quantized"}:
        return ProviderRuntimeRequirement(
            provider_id="qwen3-vl",
            profile=profile,
            supported_os=frozenset({"linux", "windows"}),
            python_min=(3, 12),
            python_max_exclusive=(3, 13),
            accelerator=Accelerator.NVIDIA,
            environments=frozenset({RuntimeEnvironment.NATIVE}),
        )

    raise ValueError("UNSUPPORTED_QWEN3_VL_PROFILE")
