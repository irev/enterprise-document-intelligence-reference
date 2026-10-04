from pathlib import Path

from edi_reference.application.runtime_bootstrap import (
    Accelerator,
    CompatibilityStatus,
    HostCapabilities,
    ProviderRuntimeRequirement,
    PythonInterpreter,
    RuntimeEnvironment,
    resolve_runtime,
)


def python(path: str, version: tuple[int, int, int]) -> PythonInterpreter:
    return PythonInterpreter(Path(path), version)


def requirement(
    *,
    accelerator: Accelerator = Accelerator.CPU,
    environments: frozenset[RuntimeEnvironment] = frozenset({RuntimeEnvironment.NATIVE}),
) -> ProviderRuntimeRequirement:
    return ProviderRuntimeRequirement(
        provider_id="provider",
        profile="test",
        supported_os=frozenset({"linux", "windows", "darwin"}),
        python_min=(3, 10),
        python_max_exclusive=(3, 13),
        accelerator=accelerator,
        environments=environments,
    )


def test_resolver_selects_highest_compatible_interpreter() -> None:
    host = HostCapabilities(
        "linux",
        "x86_64",
        (
            python("/python314", (3, 14, 1)),
            python("/python311", (3, 11, 9)),
            python("/python312", (3, 12, 8)),
        ),
    )

    result = resolve_runtime(host, requirement())

    assert result.status is CompatibilityStatus.COMPATIBLE
    assert result.python == python("/python312", (3, 12, 8))


def test_resolver_fails_closed_without_compatible_python() -> None:
    host = HostCapabilities(
        "linux",
        "x86_64",
        (python("/python314", (3, 14, 1)),),
    )

    result = resolve_runtime(host, requirement())

    assert result.status is CompatibilityStatus.INCOMPATIBLE
    assert result.reason == "RUNTIME_PYTHON_NOT_AVAILABLE"


def test_nvidia_profile_requires_detected_accelerator() -> None:
    host = HostCapabilities(
        "linux",
        "x86_64",
        (python("/python312", (3, 12, 8)),),
    )

    result = resolve_runtime(
        host,
        requirement(accelerator=Accelerator.NVIDIA),
    )

    assert result.reason == "NVIDIA_RUNTIME_NOT_DETECTED"


def test_windows_can_resolve_wsl2_environment() -> None:
    host = HostCapabilities(
        "windows",
        "amd64",
        (python("python.exe", (3, 12, 8)),),
        wsl2=True,
        nvidia=True,
    )

    result = resolve_runtime(
        host,
        requirement(
            accelerator=Accelerator.NVIDIA,
            environments=frozenset({RuntimeEnvironment.WSL2}),
        ),
    )

    assert result.status is CompatibilityStatus.COMPATIBLE
    assert result.environment is RuntimeEnvironment.WSL2


def test_missing_required_environment_fails_closed() -> None:
    host = HostCapabilities(
        "windows",
        "amd64",
        (python("python.exe", (3, 12, 8)),),
        wsl2=False,
        docker=False,
        nvidia=True,
    )

    result = resolve_runtime(
        host,
        requirement(
            accelerator=Accelerator.NVIDIA,
            environments=frozenset({RuntimeEnvironment.WSL2}),
        ),
    )

    assert result.reason == "RUNTIME_ENVIRONMENT_NOT_AVAILABLE"
