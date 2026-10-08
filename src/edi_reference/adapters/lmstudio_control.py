"""LM Studio control through its `lms` CLI (RI-4.11).

Every call is a fixed argument vector without a shell. Model keys are checked
against the installed-model list before they reach the CLI, so a client can
only name a model that is already on this machine.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

MODEL_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@/-]{0,199}")


class LmStudioError(RuntimeError):
    pass


class LmStudioControl:
    def __init__(self, cli: Path, *, port: int) -> None:
        self.cli = cli
        self.port = port

    def available(self) -> bool:
        return self.cli.is_file()

    def _run(self, *args: str, timeout: int = 120) -> str:
        if not self.available():
            raise LmStudioError("LMS_CLI_NOT_FOUND")
        try:
            done = subprocess.run([str(self.cli), *args], capture_output=True, text=True, timeout=timeout,
                                  shell=False, check=False, encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            raise LmStudioError("LMS_TIMEOUT") from None
        if done.returncode != 0:
            raise LmStudioError("LMS_COMMAND_FAILED")
        return done.stdout

    def status(self) -> dict:
        server = json.loads(self._run("server", "status", "--json", timeout=30))
        loaded = json.loads(self._run("ps", "--json", timeout=30) or "[]")
        return {"running": bool(server.get("running")), "port": server.get("port"),
                "loaded": [item.get("identifier") or item.get("modelKey") for item in loaded]}

    def models(self) -> list[dict]:
        return [
            {"key": item["modelKey"], "name": item.get("displayName") or item["modelKey"],
             "params": item.get("paramsString"), "size_gb": round(item.get("sizeBytes", 0) / 1e9, 2),
             "vision": bool(item.get("vision"))}
            for item in json.loads(self._run("ls", "--json", timeout=60))
            if item.get("type") == "llm"
        ]

    def _known(self, key: str) -> str:
        if not MODEL_KEY.fullmatch(key) or key not in {item["key"] for item in self.models()}:
            raise LmStudioError("MODEL_NOT_INSTALLED")
        return key

    def start(self) -> None:
        self._run("server", "start", "--port", str(self.port), "--bind", "127.0.0.1", timeout=120)

    def stop(self) -> None:
        self._run("server", "stop", timeout=60)

    def load(self, key: str, *, exclusive: bool = True) -> None:
        key = self._known(key)
        if exclusive:
            self.unload_all()
        self._run("load", key, "--yes", timeout=900)

    def unload_all(self) -> None:
        self._run("unload", "--all", timeout=120)


def gpu_status() -> list[dict]:
    """Best-effort NVIDIA GPU snapshot; empty when no driver tool is present."""
    tool = shutil.which("nvidia-smi")
    if tool is None:
        return []
    try:
        done = subprocess.run([tool, "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                               "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                              shell=False, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    gpus = []
    for line in done.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 4 and all(part.replace(".", "").isdigit() for part in parts[1:]):
            gpus.append({"name": parts[0], "memory_used_mib": int(float(parts[1])),
                         "memory_total_mib": int(float(parts[2])), "utilization_pct": int(float(parts[3]))})
    return gpus
