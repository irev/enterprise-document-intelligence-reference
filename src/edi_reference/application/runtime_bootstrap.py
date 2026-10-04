"""Typed host discovery and runtime compatibility resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RuntimeEnvironment(StrEnum):
    NATIVE = "NATIVE"
    WSL2 = "WSL2"
    CONTAINER = "CONTAINER"


class Accelerator(StrEnum):
    CPU = "CPU"
    NVIDIA = "NVIDIA"
    APPLE_MPS = "APPLE_MPS"


class CompatibilityStatus(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"


@dataclass(frozen=True, slots=True)
class PythonInterpreter:
    executable: Path
    version: tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class HostCapabilities:
    os: str
    architecture: str
    python_interpreters: tuple[PythonInterpreter, ...]
    docker: bool = False
    wsl2: bool = False
    nvidia: bool = False
    nvidia_driver_version: tuple[int, int, int] | None = None
    apple_mps: bool = False


@dataclass(frozen=True, slots=True)
class ProviderRuntimeRequirement:
    provider_id: str
    profile: str
    supported_os: frozenset[str]
    python_min: tuple[int, int]
    python_max_exclusive: tuple[int, int]
    accelerator: Accelerator
    environments: frozenset[RuntimeEnvironment]


@dataclass(frozen=True, slots=True)
class ResolvedRuntime:
    provider_id: str
    profile: str
    status: CompatibilityStatus
    environment: RuntimeEnvironment | None
    accelerator: Accelerator | None
    python: PythonInterpreter | None
    reason: str | None = None


def resolve_runtime(
    host: HostCapabilities,
    requirement: ProviderRuntimeRequirement,
) -> ResolvedRuntime:
    if host.os not in requirement.supported_os:
        return _incompatible(requirement, "HOST_OS_NOT_SUPPORTED")

    environment = _select_environment(host, requirement)
    if environment is None:
        return _incompatible(requirement, "RUNTIME_ENVIRONMENT_NOT_AVAILABLE")

    if requirement.accelerator is Accelerator.NVIDIA and not host.nvidia:
        return _incompatible(requirement, "NVIDIA_RUNTIME_NOT_DETECTED")
    if requirement.accelerator is Accelerator.APPLE_MPS and not host.apple_mps:
        return _incompatible(requirement, "APPLE_MPS_NOT_DETECTED")

    compatible = tuple(
        item
        for item in host.python_interpreters
        if requirement.python_min
        <= item.version[:2]
        < requirement.python_max_exclusive
    )
    if not compatible:
        return _incompatible(requirement, "RUNTIME_PYTHON_NOT_AVAILABLE")

    selected = max(compatible, key=lambda item: item.version)
    return ResolvedRuntime(
        provider_id=requirement.provider_id,
        profile=requirement.profile,
        status=CompatibilityStatus.COMPATIBLE,
        environment=environment,
        accelerator=requirement.accelerator,
        python=selected,
    )


def _select_environment(
    host: HostCapabilities,
    requirement: ProviderRuntimeRequirement,
) -> RuntimeEnvironment | None:
    if RuntimeEnvironment.NATIVE in requirement.environments:
        return RuntimeEnvironment.NATIVE
    if RuntimeEnvironment.WSL2 in requirement.environments and host.wsl2:
        return RuntimeEnvironment.WSL2
    if RuntimeEnvironment.CONTAINER in requirement.environments and host.docker:
        return RuntimeEnvironment.CONTAINER
    return None


def _incompatible(
    requirement: ProviderRuntimeRequirement,
    reason: str,
) -> ResolvedRuntime:
    return ResolvedRuntime(
        provider_id=requirement.provider_id,
        profile=requirement.profile,
        status=CompatibilityStatus.INCOMPATIBLE,
        environment=None,
        accelerator=None,
        python=None,
        reason=reason,
    )
