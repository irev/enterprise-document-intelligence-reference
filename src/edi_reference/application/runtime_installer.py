"""Safe execution boundary for trusted runtime installation plans."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from edi_reference.application.paddle_install import InstallStep


@dataclass(frozen=True, slots=True)
class StepResult:
    name: str
    returncode: int


@dataclass(frozen=True, slots=True)
class InstallExecutionResult:
    provider_id: str
    profile: str
    runtime_dir: str
    status: str
    steps: tuple[StepResult, ...]
    error_code: str | None = None
    runtime_python: str | None = None
    runtime_python_version: str | None = None


class InstallStepFailed(RuntimeError):
    def __init__(self, step: str, results: tuple[StepResult, ...]) -> None:
        super().__init__(f"INSTALL_STEP_FAILED:{step}")
        self.step = step
        self.results = results


def runtime_python(runtime_dir: Path) -> Path:
    if os.name == "nt":
        return runtime_dir / "venv" / "Scripts" / "python.exe"
    return runtime_dir / "venv" / "bin" / "python"


def ensure_runtime_venv(runtime_dir: Path, *, base_python: Path) -> Path:
    executable = runtime_python(runtime_dir)
    if executable.is_file():
        return executable
    if not base_python.is_file():
        raise RuntimeError("RUNTIME_PYTHON_NOT_AVAILABLE")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [str(base_python), "-m", "venv", str(runtime_dir / "venv")],
        capture_output=True,
        check=False,
        text=True,
        timeout=120,
        shell=False,
    )
    if completed.returncode != 0 or not executable.is_file():
        raise RuntimeError("RUNTIME_VENV_CREATION_FAILED")
    return executable


def execute_steps(
    steps: Iterable[InstallStep],
    *,
    timeout_seconds: int = 900,
) -> tuple[StepResult, ...]:
    results: list[StepResult] = []
    for step in steps:
        completed = subprocess.run(
            list(step.argv),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
        result = StepResult(name=step.name, returncode=completed.returncode)
        results.append(result)
        if completed.returncode != 0:
            raise InstallStepFailed(step.name, tuple(results))
    return tuple(results)


def verify_runtime(
    verify_argv: tuple[str, ...],
    *,
    timeout_seconds: int = 120,
) -> StepResult:
    completed = subprocess.run(
        list(verify_argv),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
        shell=False,
    )
    result = StepResult("verify-runtime", completed.returncode)
    if completed.returncode != 0:
        raise InstallStepFailed("verify-runtime", (result,))
    return result


def query_python_version(python_executable: Path) -> str:
    completed = subprocess.run(
        [str(python_executable), "-c", "import platform; print(platform.python_version())"],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
        shell=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("RUNTIME_PYTHON_VERSION_UNAVAILABLE")
    return completed.stdout.strip()


def write_install_state(runtime_dir: Path, result: InstallExecutionResult) -> None:
    state_path = runtime_dir / "install-state.json"
    payload = {
        **asdict(result),
        "recorded_at": datetime.now(UTC).isoformat(),
        "orchestrator_python": sys.version.split()[0],
    }
    runtime_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".install-state-", suffix=".json", dir=runtime_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, state_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_install_state(runtime_dir: Path) -> InstallExecutionResult:
    state_path = runtime_dir / "install-state.json"
    if not state_path.is_file():
        raise ValueError("RUNTIME_STATE_NOT_FOUND")
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    return InstallExecutionResult(
        provider_id=raw["provider_id"],
        profile=raw["profile"],
        runtime_dir=raw["runtime_dir"],
        status=raw["status"],
        steps=tuple(StepResult(**item) for item in raw["steps"]),
        error_code=raw.get("error_code"),
        runtime_python=raw.get("runtime_python"),
        runtime_python_version=raw.get("runtime_python_version"),
    )
