"""Code-owned registry for local inference servers (ollama, lmstudio, vllm).

Split into three concerns:

* detection   - read-only PATH/version probes (`detect_server`, docker probes)
* planning    - typed argv install vectors (native installers and a Docker
                image whitelist); identifiers only, never shell strings
* execution   - the same safe execution boundary used by the paddle runtime
                (`execute_server_plan`), plus advisory recommendations

Docker images are code-owned and pinned to ``latest``: package input never
contributes an image reference. LM Studio's Docker image is a community image
and is labelled as such in every plan payload.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from edi_reference.application.paddle_install import InstallStep
from edi_reference.application.runtime_installer import (
    InstallExecutionResult,
    InstallStepFailed,
    StepResult,
    ensure_runtime_venv,
    execute_steps,
    query_python_version,
    runtime_python,
    verify_runtime,
    write_install_state,
)
from edi_reference.application.tier_map import TierDefinition, resolve_tier

WhichFn = Callable[[str], str | None]
RunFn = Callable[..., "subprocess.CompletedProcess[str] | None"]

MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")

NATIVE_AUTOMATED = "AUTOMATED"
NATIVE_MANUAL = "MANUAL"
NATIVE_UNSUPPORTED = "UNSUPPORTED"
NATIVE_ALREADY_INSTALLED = "ALREADY_INSTALLED"

GPU_MODES = frozenset({"auto", "on", "off"})
DOCKER_VARIANTS = frozenset({"desktop", "headless"})

VLLM_PIP_SPEC = "vllm==0.30.0"
_BOOTSTRAP_MODULE = "edi_reference.application.server_bootstrap"
_LMSTUDIO_DESKTOP_IMAGE = "linuxserver/lm-studio:latest"
_LMSTUDIO_HEADLESS_IMAGE = "lmstudio/llmster-preview:latest"
_LMSTUDIO_DESKTOP_CONTAINER = "edi-lm-studio"
_LMSTUDIO_HEADLESS_CONTAINER = "edi-lm-studio-headless"
_LMSTUDIO_DESKTOP_START_HINTS = (
    "start the API: docker exec edi-lm-studio lms server start",
    "verify: curl http://127.0.0.1:1234/v1/models",
    "web GUI (KasmVNC): http://127.0.0.1:3000",
)

_OLLAMA_LINUX_INSTRUCTIONS = (
    "official installer: curl -fsSL https://ollama.com/install.sh | sh",
    "manual: extract the ollama-linux archive (tar --zstd -xf ollama-linux-*.tar.zst) under /usr/local",
    "start the service: sudo systemctl enable --now ollama",
)
_LMSTUDIO_INSTRUCTIONS = (
    "install LM Studio from https://lmstudio.ai/download",
    "run `lms bootstrap` once so the local lms CLI is on PATH",
)
_NVIDIA_TOOLKIT_INSTRUCTIONS = (
    "install the NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html",
    "configure docker: sudo nvidia-ctk runtime configure --runtime=docker",
    "restart docker: sudo systemctl restart docker",
)


@dataclass(frozen=True, slots=True)
class ServerDefinition:
    server_id: str
    display_name: str
    default_port: int
    docker_image: str
    container_name: str
    community_image: bool
    detect_executable: str
    native_supported_os: frozenset[str]
    native_manual_os: frozenset[str]
    docker_requires_gpu: bool
    manual_error_code: str
    manual_instructions: tuple[str, ...]
    start_hint: str


SERVER_DEFINITIONS: dict[str, ServerDefinition] = {
    "ollama": ServerDefinition(
        server_id="ollama",
        display_name="Ollama",
        default_port=11434,
        docker_image="ollama/ollama:latest",
        container_name="edi-ollama",
        community_image=False,
        detect_executable="ollama",
        native_supported_os=frozenset({"windows", "darwin", "linux"}),
        native_manual_os=frozenset(),
        docker_requires_gpu=False,
        manual_error_code="INSTALL_VECTOR_UNSUPPORTED",
        manual_instructions=_OLLAMA_LINUX_INSTRUCTIONS,
        start_hint="ollama serve",
    ),
    "lmstudio": ServerDefinition(
        server_id="lmstudio",
        display_name="LM Studio",
        default_port=1234,
        docker_image="linuxserver/lm-studio:latest",
        container_name="edi-lm-studio",
        community_image=True,
        detect_executable="lms",
        native_supported_os=frozenset(),
        native_manual_os=frozenset({"windows", "linux", "darwin"}),
        docker_requires_gpu=False,
        manual_error_code="INSTALL_VECTOR_NOT_AUTOMATED",
        manual_instructions=_LMSTUDIO_INSTRUCTIONS,
        start_hint="LM Studio GUI, then `lms server start`",
    ),
    "vllm": ServerDefinition(
        server_id="vllm",
        display_name="vLLM",
        default_port=8000,
        docker_image="vllm/vllm-openai:latest",
        container_name="edi-vllm",
        community_image=False,
        detect_executable="vllm",
        native_supported_os=frozenset({"linux"}),
        native_manual_os=frozenset(),
        docker_requires_gpu=True,
        manual_error_code="INSTALL_VECTOR_UNSUPPORTED",
        manual_instructions=(),
        start_hint="vllm serve <model>",
    ),
}


@dataclass(frozen=True, slots=True)
class ServerDetection:
    server_id: str
    status: str
    version: str | None
    executable: str | None


@dataclass(frozen=True, slots=True)
class NativeVector:
    status: str
    instructions: tuple[str, ...]
    error_code: str | None


@dataclass(frozen=True, slots=True)
class ServerPlan:
    server_id: str
    via: str
    automated: bool
    steps: tuple[InstallStep, ...]
    verify_argv: tuple[str, ...] | None
    image: str | None = None
    community_image: bool = False
    container_name: str | None = None
    requires_gpu: bool = False
    venv_required: bool = False
    error_code: str | None = None
    instructions: tuple[str, ...] = ()
    step_timeout_seconds: int = 900


def get_server(server_id: str) -> ServerDefinition:
    try:
        return SERVER_DEFINITIONS[server_id]
    except KeyError as exc:
        raise ValueError("UNKNOWN_SERVER") from exc


def list_servers() -> tuple[ServerDefinition, ...]:
    return tuple(SERVER_DEFINITIONS.values())


def _run_capture(
    argv: tuple[str, ...] | list[str],
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _probe_version(executable: str) -> tuple[bool, str | None]:
    completed = _run_capture((executable, "--version"), timeout=15)
    if completed is None or completed.returncode != 0:
        return False, None
    output = (completed.stdout or "").strip() or (completed.stderr or "").strip()
    first_line = output.splitlines()[0].strip() if output else None
    return True, first_line or None


# Runtime binaries installed by automated native vectors (relative to
# runtime_root/<server_id>/<via>/) — probed when the executable is not on PATH.
_RUNTIME_BINARIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "ollama": ("native", ("bin", "ollama")),
    "vllm": ("native", ("venv", "bin", "vllm")),
}


def _detect_runtime_state(server_id: str, runtime_root: Path) -> ServerDetection | None:
    binary = _RUNTIME_BINARIES.get(server_id)
    if binary is not None:
        via, parts = binary
        candidate = runtime_root / server_id / via
        for part in parts:
            candidate = candidate / part
        if candidate.is_file():
            ok, version = _probe_version(str(candidate))
            if ok:
                return ServerDetection(server_id, "INSTALLED", version, str(candidate))
            return ServerDetection(server_id, "UNKNOWN", None, str(candidate))
    for via in ("native", "docker"):
        state_path = runtime_root / server_id / via / "install-state.json"
        if not state_path.is_file():
            continue
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if raw.get("status") == "READY":
            return ServerDetection(server_id, "INSTALLED", None, None)
    return None


def detect_server(
    server_id: str,
    *,
    which: WhichFn = shutil.which,
    runtime_root: Path | None = None,
) -> ServerDetection:
    definition = get_server(server_id)
    path = which(definition.detect_executable)
    if not path and runtime_root is not None:
        fallback = _detect_runtime_state(server_id, runtime_root)
        if fallback is not None:
            return fallback
    if not path:
        return ServerDetection(server_id, "NOT_INSTALLED", None, None)
    ok, version = _probe_version(str(path))
    if not ok:
        return ServerDetection(server_id, "UNKNOWN", None, str(path))
    return ServerDetection(server_id, "INSTALLED", version, str(path))


def docker_daemon_status(*, which: WhichFn = shutil.which, run: RunFn | None = None) -> str:
    if not which("docker"):
        return "NOT_INSTALLED"
    runner = run if run is not None else _run_capture
    completed = runner(("docker", "info", "--format", "{{.ServerVersion}}"), timeout=15)
    if completed is None or completed.returncode != 0:
        return "UNAVAILABLE"
    return "READY"


def docker_gpu_status(*, which: WhichFn = shutil.which, run: RunFn | None = None) -> str:
    runner = run if run is not None else _run_capture
    completed = runner(("docker", "info", "--format", "{{json .Runtimes}}"), timeout=15)
    if completed is not None and completed.returncode == 0 and '"nvidia"' in (completed.stdout or ""):
        return "READY"
    if which("nvidia-container-cli"):
        return "READY"
    return "NOT_AVAILABLE"


def native_vector_status(server_id: str, host_os: str) -> NativeVector:
    definition = get_server(server_id)
    if host_os in definition.native_supported_os:
        return NativeVector(NATIVE_AUTOMATED, (), None)
    if host_os in definition.native_manual_os:
        return NativeVector(
            NATIVE_MANUAL,
            definition.manual_instructions,
            definition.manual_error_code,
        )
    if server_id == "vllm":
        return NativeVector(NATIVE_UNSUPPORTED, (), "VLLM_UNSUPPORTED_ON_HOST")
    return NativeVector(
        NATIVE_UNSUPPORTED,
        definition.manual_instructions,
        "INSTALL_VECTOR_UNSUPPORTED",
    )


def _lmstudio_identity(variant: str) -> tuple[str, str, bool]:
    if variant == "headless":
        return _LMSTUDIO_HEADLESS_IMAGE, _LMSTUDIO_HEADLESS_CONTAINER, False
    return _LMSTUDIO_DESKTOP_IMAGE, _LMSTUDIO_DESKTOP_CONTAINER, True


def _container_steps(
    definition: ServerDefinition,
    *,
    use_gpu: bool,
    model_id: str | None,
    hf_cache: Path,
    variant: str = "desktop",
) -> tuple[InstallStep, ...]:
    argv: list[str] = ["docker", "run", "-d"]
    if use_gpu:
        argv.append("--gpus=all")
    if definition.server_id == "ollama":
        argv += [
            "-v", "edi-ollama:/root/.ollama",
            "-p", f"{definition.default_port}:{definition.default_port}",
            "--name", definition.container_name,
            definition.docker_image,
        ]
    elif definition.server_id == "lmstudio":
        image, container, _ = _lmstudio_identity(variant)
        if variant == "headless":
            argv += ["-p", "1234:1234"]
        else:
            argv += ["-p", "3000:3000", "-p", "3001:3001", "-p", "1234:1234"]
        argv += [
            "-e", "PUID=1000",
            "-e", "PGID=1000",
            "-e", "TZ=Etc/UTC",
            "--name", container,
            image,
        ]
    elif definition.server_id == "vllm":
        if model_id is None or not MODEL_ID_PATTERN.fullmatch(model_id):
            raise ValueError("INVALID_MODEL_ID")
        argv += [
            "--ipc=host",
            "-v", f"{hf_cache}:/root/.cache/huggingface",
            "-p", f"{definition.default_port}:{definition.default_port}",
            "--name", definition.container_name,
            definition.docker_image,
            "--model", model_id,
        ]
    else:  # pragma: no cover - registry is code-owned
        raise ValueError("UNKNOWN_SERVER")
    return (InstallStep("run-container", tuple(argv)),)


def build_native_plan(
    server_id: str,
    *,
    host_os: str,
    gpu: bool,
    runtime_root: Path,
    which: WhichFn = shutil.which,
) -> ServerPlan:
    definition = get_server(server_id)
    vector = native_vector_status(server_id, host_os)

    if vector.status == NATIVE_UNSUPPORTED:
        raise ValueError(vector.error_code or "INSTALL_VECTOR_UNSUPPORTED")

    if definition.server_id == "lmstudio":
        detection = detect_server(server_id, which=which, runtime_root=runtime_root)
        if detection.status == "INSTALLED":
            return ServerPlan(
                server_id=server_id,
                via="native",
                automated=True,
                steps=(),
                verify_argv=None,
            )
        return ServerPlan(
            server_id=server_id,
            via="native",
            automated=False,
            steps=(),
            verify_argv=None,
            error_code=definition.manual_error_code,
            instructions=definition.manual_instructions,
        )

    if vector.status == NATIVE_MANUAL:
        return ServerPlan(
            server_id=server_id,
            via="native",
            automated=False,
            steps=(),
            verify_argv=None,
            error_code=definition.manual_error_code,
            instructions=definition.manual_instructions,
        )

    if definition.server_id == "ollama":
        if host_os == "windows":
            install_argv: tuple[str, ...] = (
                "winget", "install", "-e", "--id", "Ollama.Ollama", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
            )
            return ServerPlan(
                server_id=server_id,
                via="native",
                automated=True,
                steps=(InstallStep("install-ollama", install_argv),),
                verify_argv=("ollama", "--version"),
            )
        if host_os == "darwin":
            return ServerPlan(
                server_id=server_id,
                via="native",
                automated=True,
                steps=(InstallStep("install-ollama", ("brew", "install", "ollama")),),
                verify_argv=("ollama", "--version"),
            )
        destination = runtime_root / "ollama" / "native"
        bootstrap_argv = (
            sys.executable,
            "-m",
            _BOOTSTRAP_MODULE,
            "ollama",
            str(destination),
        )
        return ServerPlan(
            server_id=server_id,
            via="native",
            automated=True,
            steps=(InstallStep("download-ollama", bootstrap_argv),),
            verify_argv=(str(destination / "bin" / "ollama"), "--version"),
            step_timeout_seconds=1800,
        )

    if definition.server_id == "vllm":
        if not gpu:
            raise ValueError("VLLM_REQUIRES_GPU")
        python_path = runtime_python(runtime_root / "vllm" / "native")
        executable = str(python_path)
        return ServerPlan(
            server_id=server_id,
            via="native",
            automated=True,
            steps=(
                InstallStep("upgrade-pip", (executable, "-m", "pip", "install", "--upgrade", "pip")),
                InstallStep("install-vllm", (executable, "-m", "pip", "install", VLLM_PIP_SPEC)),
            ),
            verify_argv=(executable, "-c", "import vllm; print(vllm.__version__)"),
            requires_gpu=True,
            venv_required=True,
            step_timeout_seconds=1800,
        )

    raise ValueError("UNKNOWN_SERVER")  # pragma: no cover


def build_docker_plan(
    server_id: str,
    *,
    gpu: bool,
    model_id: str | None,
    hf_cache: Path,
    daemon_status: str,
    gpu_status: str,
    variant: str = "desktop",
) -> ServerPlan:
    definition = get_server(server_id)
    if variant not in DOCKER_VARIANTS:
        raise ValueError("INVALID_PARAMS")
    if server_id != "lmstudio" and variant != "desktop":
        raise ValueError("INVALID_PARAMS")
    if daemon_status != "READY":
        raise ValueError("DOCKER_NOT_AVAILABLE")
    if definition.docker_requires_gpu:
        if not gpu:
            raise ValueError("VLLM_REQUIRES_GPU")
        if gpu_status != "READY":
            raise ValueError("NVIDIA_CONTAINER_TOOLKIT_NOT_DETECTED")
    elif gpu and gpu_status != "READY":
        raise ValueError("NVIDIA_CONTAINER_TOOLKIT_NOT_DETECTED")
    use_gpu = gpu and gpu_status == "READY"
    steps = _container_steps(
        definition,
        use_gpu=use_gpu,
        model_id=model_id,
        hf_cache=hf_cache,
        variant=variant,
    )
    image = definition.docker_image
    container_name = definition.container_name
    community_image = definition.community_image
    instructions: tuple[str, ...] = ()
    if server_id == "lmstudio":
        image, container_name, community_image = _lmstudio_identity(variant)
        if variant == "desktop":
            instructions = _LMSTUDIO_DESKTOP_START_HINTS
    return ServerPlan(
        server_id=server_id,
        via="docker",
        automated=True,
        steps=steps,
        verify_argv=("docker", "inspect", "-f", "{{.State.Status}}", container_name),
        image=image,
        community_image=community_image,
        container_name=container_name,
        requires_gpu=definition.docker_requires_gpu,
        instructions=instructions,
    )


def verify_container(container_name: str, *, run: RunFn | None = None) -> StepResult:
    runner = run if run is not None else _run_capture
    completed = runner(("docker", "inspect", "-f", "{{.State.Status}}", container_name), timeout=15)
    status = (completed.stdout or "").strip() if completed is not None else ""
    if completed is None or completed.returncode != 0 or status != "running":
        raise InstallStepFailed(
            "verify-container", (StepResult("verify-container", 1),)
        )
    return StepResult("verify-container", 0)


def execute_server_plan(
    plan: ServerPlan,
    *,
    runtime_root: Path,
    base_python: Path | None = None,
    run: RunFn | None = None,
) -> InstallExecutionResult:
    if not plan.automated:
        raise ValueError(plan.error_code or "INSTALL_VECTOR_NOT_AUTOMATED")
    runtime_dir = runtime_root / plan.server_id / plan.via
    runtime_python_path: Path | None = None
    python_version: str | None = None
    try:
        if plan.venv_required:
            if base_python is None:
                raise RuntimeError("RUNTIME_PYTHON_NOT_AVAILABLE")
            runtime_python_path = ensure_runtime_venv(runtime_dir, base_python=base_python)
            python_version = query_python_version(runtime_python_path)
            steps = execute_steps(plan.steps, timeout_seconds=plan.step_timeout_seconds)
            verification = verify_runtime(plan.verify_argv) if plan.verify_argv else None
        elif plan.via == "docker":
            steps = execute_steps(plan.steps, timeout_seconds=600)
            verification = verify_container(plan.container_name or "", run=run)
        else:
            steps = execute_steps(plan.steps, timeout_seconds=plan.step_timeout_seconds)
            verification = verify_runtime(plan.verify_argv) if plan.verify_argv else None
    except (InstallStepFailed, RuntimeError) as exc:
        failed = InstallExecutionResult(
            provider_id=plan.server_id,
            profile=plan.via,
            runtime_dir=str(runtime_dir),
            status="FAILED",
            steps=(),
            error_code=str(exc),
        )
        write_install_state(runtime_dir, failed)
        raise
    result = InstallExecutionResult(
        provider_id=plan.server_id,
        profile=plan.via,
        runtime_dir=str(runtime_dir),
        status="READY",
        steps=steps + ((verification,) if verification is not None else ()),
        runtime_python=str(runtime_python_path) if runtime_python_path else None,
        runtime_python_version=python_version,
    )
    write_install_state(runtime_dir, result)
    return result


def recommend_servers(
    *,
    vram_mib: int | None,
    tiers: dict[str, TierDefinition],
) -> list[dict[str, object]]:
    tier_id = resolve_tier(tiers, vram_mib)
    tier = tiers.get(tier_id)
    rows: list[dict[str, object]] = []
    for definition in list_servers():
        reasons: list[str] = []
        if tier is None:
            verdict = "UNKNOWN"
            reasons.append("VRAM_UNKNOWN" if vram_mib is None else "NO_TIER_BAND_MATCH")
        elif definition.server_id in tier.serve:
            verdict = "RECOMMENDED"
            reasons.append(f"TIER_MATCH:{tier_id}")
        else:
            verdict = "NOT_RECOMMENDED"
            reasons.append(f"TIER_NOT_ELIGIBLE:{tier_id}")
        rows.append(
            {
                "server_id": definition.server_id,
                "display_name": definition.display_name,
                "default_port": definition.default_port,
                "verdict": verdict,
                "reasons": reasons,
            }
        )
    return rows


def parse_vram_mib(value: str | None) -> int | None:
    """Parse `nvidia-smi` query output (e.g. 'GPU0, 12288 MiB') into MiB."""
    if not value:
        return None
    segment = value.rsplit(",", 1)[-1].strip()
    if not segment:
        return None
    token = segment.split()[0]
    try:
        number = int(token)
    except ValueError:
        try:
            number = int(float(token))
        except ValueError:
            return None
    return number if number > 0 else None
