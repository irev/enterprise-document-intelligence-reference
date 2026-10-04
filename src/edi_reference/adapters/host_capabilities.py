"""Portable host capability discovery for runtime bootstrap."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

from edi_reference.application.runtime_bootstrap import (
    HostCapabilities,
    PythonInterpreter,
)


def discover_python_interpreters() -> tuple[PythonInterpreter, ...]:
    candidates: list[str] = [sys.executable]
    for name in (
        "python3.12",
        "python3.11",
        "python3.10",
        "python3",
        "python",
        "py",
    ):
        resolved = shutil.which(name)
        if resolved is not None:
            candidates.append(resolved)

    discovered: dict[Path, PythonInterpreter] = {}
    for candidate in candidates:
        executable = Path(candidate).resolve()
        if executable in discovered:
            continue
        version = _query_python_version(executable)
        if version is not None:
            discovered[executable] = PythonInterpreter(executable, version)
    return tuple(discovered.values())


def inspect_host_capabilities(
    *,
    nvidia_driver_version: tuple[int, int, int] | None = None,
) -> HostCapabilities:
    os_name = platform.system().lower()
    return HostCapabilities(
        os=os_name,
        architecture=platform.machine().lower(),
        python_interpreters=discover_python_interpreters(),
        docker=shutil.which("docker") is not None,
        wsl2=_has_wsl2(os_name),
        nvidia=shutil.which("nvidia-smi") is not None,
        nvidia_driver_version=nvidia_driver_version,
        apple_mps=os_name == "darwin" and platform.machine().lower() in {"arm64", "aarch64"},
    )


def _query_python_version(executable: Path) -> tuple[int, int, int] | None:
    try:
        result = subprocess.run(
            [
                str(executable),
                "-c",
                "import sys; print('.'.join(map(str, sys.version_info[:3])))",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        parts = tuple(int(part) for part in result.stdout.strip().split("."))
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    return (parts[0], parts[1], parts[2])


def _has_wsl2(os_name: str) -> bool:
    if os_name != "windows" or shutil.which("wsl") is None:
        return False
    try:
        result = subprocess.run(
            ["wsl", "--status"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
