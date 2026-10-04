"""Safe execution boundary for trusted runtime installation plans."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import venv
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


class InstallStepFailed(RuntimeError):
    def __init__(self, step: str, results: tuple[StepResult, ...]) -> None:
        super().__init__(f"INSTALL_STEP_FAILED:{step}")
        self.step = step
        self.results = results


def runtime_python(runtime_dir: Path) -> Path:
    if os.name == "nt":
        return runtime_dir / "venv" / "Scripts" / "python.exe"
    return runtime_dir / "venv" / "bin" / "python"


def ensure_runtime_venv(runtime_dir: Path) -> Path:
    target = runtime_dir / "venv"
    if not runtime_python(runtime_dir).exists():
        runtime_dir.mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(target)
    return runtime_python(runtime_dir)


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
