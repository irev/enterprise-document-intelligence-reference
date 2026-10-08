"""Portable management CLI for runtime capability installation."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

from edi_reference.adapters.host_capabilities import inspect_host_capabilities
from edi_reference.adapters.web_panel import build_server
from edi_reference.application import servers
from edi_reference.application.file_processing import ProcessingLog, process_file
from edi_reference.application.local_config import (
    DEFAULT_CONFIG_PATH,
    MODEL_SOURCES,
    LocalConfig,
    config_to_dict,
    load_config,
    save_config,
)
from edi_reference.application.paddle_infer import run_local_ocr
from edi_reference.application.paddle_models import (
    resolve_paddle_model,
    verify_paddle_model,
    warm_paddle_model,
)
from edi_reference.application.provider_manifest import load_provider_manifest
from edi_reference.application.runtime_bootstrap import (
    Accelerator,
    CompatibilityStatus,
    ProviderRuntimeRequirement,
    ResolvedRuntime,
    RuntimeEnvironment,
    resolve_runtime,
)
from edi_reference.application.runtime_installer import read_install_state, runtime_python
from edi_reference.application.runtime_requirements import provider_runtime_requirement
from edi_reference.application.runtime_management import RuntimeManagementService
from edi_reference.application.tier_map import load_tier_map, resolve_tier
from edi_reference.domain.ocr import OcrResult


@dataclass(frozen=True, slots=True)
class HostInfo:
    os: str
    architecture: str
    docker: bool
    nvidia_smi: bool
    nvidia_driver_version: tuple[int, int, int] | None = None


class OperationError(Exception):
    """Operation failure carrying a stable machine-readable code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _nvidia_query(field: str) -> str | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, f"--query-gpu={field}", "--format=csv,noheader"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip().splitlines()
    return value[0].strip() if result.returncode == 0 and value else None


def _parse_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    try:
        parts = [int(part) for part in value.split(".")[:3]]
    except ValueError:
        return None
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def inspect_host() -> HostInfo:
    driver = _parse_version(_nvidia_query("driver_version"))
    return HostInfo(
        os=platform.system().lower(),
        architecture=platform.machine().lower(),
        docker=shutil.which("docker") is not None,
        nvidia_smi=shutil.which("nvidia-smi") is not None,
        nvidia_driver_version=driver,
    )


def resolve_install(
    provider: str,
    profile: str,
    host: HostInfo,
    *,
    python_executable: str = "<runtime-python>",
) -> dict[str, object]:
    service = RuntimeManagementService(load_provider_manifest())
    return service.plan_install(
        provider_id=provider,
        profile=profile,
        host=host,
        python_executable=python_executable,
    )


def _emit(payload: object) -> None:
    print(json.dumps(payload, indent=2))


def _stderr_is_tty() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, OSError, ValueError):
        return False


class _Progress:
    """Indeterminate install/download animation on stderr; silent when not a TTY.

    stdout is never touched: JSON/stdout contracts stay byte-identical, and
    non-interactive runs (tests, pipes, Docker) produce no extra output.
    """

    FRAMES = "|/-\\"

    def __init__(self, label: str) -> None:
        self._label = label
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _Progress:
        if not _stderr_is_tty():
            return self
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        index = 0
        while not self._stop.is_set():
            frame = self.FRAMES[index % len(self.FRAMES)]
            index += 1
            sys.stderr.write(f"\r{self._label} {frame}")
            sys.stderr.flush()
            self._stop.wait(0.12)

    def __exit__(self, *exc: object) -> Literal[False]:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=1.0)
            sys.stderr.write("\r" + " " * (len(self._label) + 2) + "\r")
            sys.stderr.flush()
        return False


def _doctor_payload(host: HostInfo) -> dict[str, object]:
    payload: dict[str, object] = asdict(host)
    payload["nvidia_gpu"] = _nvidia_query("name,memory.total")
    return payload


def _verify_model(*, model_id: str, model_root: Path) -> dict[str, object]:
    return asdict(verify_paddle_model(model_root / "paddle-ocr" / model_id))


def _pull_model(
    *,
    model_id: str,
    profile: str,
    source: str,
    runtime_root: Path,
    model_root: Path,
) -> dict[str, object]:
    artifact_dir = model_root / "paddle-ocr" / model_id
    runtime_dir = runtime_root / "paddle-ocr" / profile
    runtime_python_path = runtime_python(runtime_dir)
    try:
        runtime_state = read_install_state(runtime_dir)
    except (ValueError, OSError) as exc:
        raise OperationError(str(exc) or "RUNTIME_STATE_UNREADABLE") from exc
    if runtime_state.status != "READY" or not runtime_python_path.is_file():
        raise OperationError("PADDLE_RUNTIME_NOT_READY")
    try:
        with _Progress(f"Downloading model {model_id}"):
            state = warm_paddle_model(
                python_executable=str(runtime_python_path),
                model_id=model_id,
                artifact_dir=artifact_dir,
                source=source,
            )
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise OperationError(str(exc) or exc.__class__.__name__) from exc
    return asdict(state)


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except (AttributeError, OSError, ValueError):
        return False


def _select_model(
    candidates: list[str],
    *,
    read: Callable[[str], str] | None = None,
) -> str | None:
    if read is None:
        read = input
    print("Select a model to provision after installation:")
    for index, candidate in enumerate(candidates, start=1):
        print(f"  {index}. {candidate}")
    print("  q. skip model provisioning")
    attempts = 0
    while True:
        answer = read("Select model: ").strip().lower()
        if answer in {"", "q"}:
            return None
        try:
            selection = int(answer)
        except ValueError:
            selection = 0
        if 1 <= selection <= len(candidates):
            return candidates[selection - 1]
        attempts += 1
        if attempts >= 5:
            raise OperationError("INVALID_MODEL_SELECTION")
        print("INVALID_SELECTION")


def _model_candidates(
    service: RuntimeManagementService,
    provider_id: str,
) -> list[str]:
    candidates: list[str] = []
    for model in service.models():
        if model["provider_id"] != provider_id:
            continue
        try:
            resolve_paddle_model(model["model_id"])
        except ValueError:
            continue
        candidates.append(model["model_id"])
    return candidates


def _vram_mib() -> int | None:
    return servers.parse_vram_mib(_nvidia_query("memory.total"))


def _tier_id(vram_mib: int | None) -> str:
    try:
        tiers = load_tier_map()
    except (ValueError, OSError):
        return "UNKNOWN"
    return resolve_tier(tiers, vram_mib)


def _runtime_status_rows(runtime_root: Path) -> list[dict[str, object]]:
    manifest = load_provider_manifest()
    rows: list[dict[str, object]] = []
    for provider in manifest.providers.values():
        for profile in provider.profiles:
            state_path = runtime_root / provider.provider_id / profile / "install-state.json"
            if not state_path.is_file():
                status: str = "NOT_INSTALLED"
            else:
                try:
                    status = read_install_state(state_path.parent).status
                except (ValueError, OSError, KeyError, TypeError):
                    status = "UNKNOWN"
            rows.append(
                {"provider_id": provider.provider_id, "profile": profile, "status": status}
            )
    return rows


def _model_status_rows(model_root: Path, service: RuntimeManagementService) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model in service.models():
        state_path = model_root / model["provider_id"] / model["model_id"] / "model-state.json"
        if not state_path.is_file():
            status: str = "NOT_PROVISIONED"
        else:
            try:
                raw = json.loads(state_path.read_text(encoding="utf-8"))
                value = raw.get("status") if isinstance(raw, dict) else None
            except (OSError, json.JSONDecodeError):
                value = None
            status = value if isinstance(value, str) and value else "UNKNOWN"
        rows.append(
            {
                "provider_id": model["provider_id"],
                "model_id": model["model_id"],
                "status": status,
            }
        )
    return rows


def _server_status_rows(runtime_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for definition in servers.list_servers():
        detection = servers.detect_server(definition.server_id, runtime_root=runtime_root)
        rows.append(
            {
                "server_id": definition.server_id,
                "display_name": definition.display_name,
                "default_port": definition.default_port,
                "status": detection.status,
                "version": detection.version,
            }
        )
    return rows


def _status_summary(
    host: HostInfo,
    *,
    runtime_root: Path,
    model_root: Path,
) -> dict[str, object]:
    service = RuntimeManagementService(load_provider_manifest())
    vram_mib = _vram_mib()
    return {
        "host": _doctor_payload(host),
        "vram_mib": vram_mib,
        "tier": _tier_id(vram_mib),
        "providers": _runtime_status_rows(runtime_root),
        "models": _model_status_rows(model_root, service),
        "servers": _server_status_rows(runtime_root),
    }


def _config_payload(
    host: HostInfo,
    *,
    config: LocalConfig,
    config_path: Path,
    runtime_root: Path,
    model_root: Path,
    log_path: Path,
) -> dict[str, object]:
    vram_mib = _vram_mib()
    return {
        "config_path": str(config_path),
        "config_exists": config_path.is_file(),
        "config": config_to_dict(config),
        "effective": {
            "runtime_root": str(runtime_root),
            "model_root": str(model_root),
            "log_path": str(log_path),
            "provider_id": config.provider_id,
            "profile": config.profile,
            "model_id": config.model_id,
            "model_source": config.model_source or "HUGGINGFACE",
            "web_bind": config.web_bind or "127.0.0.1",
            "web_port": config.web_port or 4099,
        },
        "host": _doctor_payload(host),
        "vram_mib": vram_mib,
        "tier": _tier_id(vram_mib),
        "runtime_status": _runtime_status_rows(runtime_root),
        "servers": _server_status_rows(runtime_root),
    }



def _wizard_text(
    read: Callable[[str], str],
    label: str,
    current: str | None,
    default: str,
) -> str:
    answer = read(f"{label} [{current or default}]: ").strip()
    if answer.lower() == "q":
        raise OperationError("WIZARD_CANCELLED")
    return answer or (current or default)


def _wizard_choice(
    read: Callable[[str], str],
    label: str,
    options: tuple[str, ...],
    current: str | None,
) -> str | None:
    print(f"{label}:")
    for index, option in enumerate(options, start=1):
        print(f"  {index}. {option}")
    attempts = 0
    while True:
        answer = read(f"Select [{current or '(none)'}]: ").strip().lower()
        if answer == "q":
            raise OperationError("WIZARD_CANCELLED")
        if answer == "":
            return current
        try:
            selection = int(answer)
        except ValueError:
            selection = 0
        if 1 <= selection <= len(options):
            return options[selection - 1]
        attempts += 1
        if attempts >= 5:
            raise OperationError("INVALID_SELECTION")
        print("INVALID_SELECTION")


def _wizard_port(read: Callable[[str], str], current: int) -> int:
    attempts = 0
    while True:
        answer = read(f"Web port [{current}]: ").strip()
        if answer.lower() == "q":
            raise OperationError("WIZARD_CANCELLED")
        if not answer:
            return current
        try:
            value = int(answer)
        except ValueError:
            value = 0
        if 0 < value < 65536:
            return value
        attempts += 1
        if attempts >= 5:
            raise OperationError("INVALID_SELECTION")
        print("INVALID_SELECTION")


def _run_config_wizard(
    *,
    config: LocalConfig,
    config_path: Path,
    service: RuntimeManagementService,
    read: Callable[[str], str] | None = None,
) -> None:
    if read is None:
        read = input
    if not _stdin_is_tty():
        raise OperationError("WIZARD_REQUIRES_TTY")
    print("Local configuration wizard - Enter keeps the shown default, q cancels.")
    runtime_root = _wizard_text(read, "Runtime root", config.runtime_root, ".edi/runtimes")
    model_root = _wizard_text(read, "Model root", config.model_root, ".edi/models")
    log_path = _wizard_text(
        read, "Processing log path", config.log_path, ".edi/logs/processing.jsonl"
    )
    manifest = load_provider_manifest()
    provider_options = tuple(manifest.providers)
    provider_id = _wizard_choice(read, "Provider", provider_options, config.provider_id)
    profile = config.profile
    if provider_id is not None:
        definition = manifest.providers.get(provider_id)
        profiles = definition.profiles if definition is not None else ()
        if profiles:
            current_profile = config.profile if config.profile in profiles else None
            profile = _wizard_choice(read, "Profile", profiles, current_profile)
        else:
            profile = None
    model_id: str | None
    if provider_id is None:
        model_id = config.model_id
    else:
        model_candidates = tuple(_model_candidates(service, provider_id))
        if model_candidates:
            current_model = config.model_id if config.model_id in model_candidates else None
            model_id = _wizard_choice(
                read, "Model (provision after install)", model_candidates, current_model
            )
        else:
            print("No installable models for this provider; model selection cleared.")
            model_id = None
    model_source = _wizard_choice(read, "Model source", MODEL_SOURCES, config.model_source)
    web_port = _wizard_port(read, config.web_port or 4099)
    web_bind = _wizard_text(read, "Web bind address", config.web_bind, "127.0.0.1")
    new_config = LocalConfig(
        runtime_root=runtime_root,
        model_root=model_root,
        log_path=log_path,
        provider_id=provider_id,
        profile=profile,
        model_id=model_id,
        model_source=model_source,
        web_port=web_port,
        web_bind=web_bind,
    )
    print("Review:")
    for key, value in config_to_dict(new_config).items():
        print(f"  {key}: {value}")
    confirm = read(f"Save to {config_path}? [y/N]: ").strip().lower()
    if confirm not in {"y", "yes"}:
        raise OperationError("WIZARD_CANCELLED")
    save_config(new_config, config_path)
    print(f"SAVED {config_path}")


def _log_lines(path: Path, tail: int) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if tail > 0:
        lines = lines[-tail:]
    return lines


def _format_log_line(line: str, *, pretty: bool) -> str:
    if not pretty:
        return line
    try:
        return json.dumps(json.loads(line), indent=2)
    except json.JSONDecodeError:
        return line


def _serve_list_payload(host: HostInfo, runtime_root: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for definition in servers.list_servers():
        detection = servers.detect_server(definition.server_id, runtime_root=runtime_root)
        vector = servers.native_vector_status(definition.server_id, host.os)
        rows.append(
            {
                "server_id": definition.server_id,
                "display_name": definition.display_name,
                "default_port": definition.default_port,
                "image": definition.docker_image,
                "community_image": definition.community_image,
                "detection": {"status": detection.status, "version": detection.version},
                "native_vector": vector.status,
            }
        )
    return {"servers": rows}


def _serve_recommend_payload() -> dict[str, object]:
    vram_mib = _vram_mib()
    tiers = load_tier_map()
    tier = resolve_tier(tiers, vram_mib)
    return {
        "tier": tier,
        "vram_mib": vram_mib,
        "recommendations": servers.recommend_servers(vram_mib=vram_mib, tiers=tiers),
    }


def _resolve_serve_via(server_id: str, via: str, host: HostInfo, runtime_root: Path) -> str:
    if via in {"native", "docker"}:
        return via
    if server_id == "lmstudio" and servers.detect_server(
        server_id, runtime_root=runtime_root
    ).status == "INSTALLED":
        return "native"
    vector = servers.native_vector_status(server_id, host.os)
    if vector.status == servers.NATIVE_AUTOMATED:
        return "native"
    if servers.docker_daemon_status() == "READY":
        return "docker"
    if vector.status == servers.NATIVE_MANUAL:
        return "native"
    raise OperationError("DOCKER_NOT_AVAILABLE")


def _gpu_intent(gpu_mode: str, host: HostInfo) -> bool:
    if gpu_mode == "on":
        return True
    if gpu_mode == "off":
        return False
    return host.nvidia_smi


def _build_serve_plan(
    server_id: str,
    *,
    via: str,
    host: HostInfo,
    runtime_root: Path,
    model: str | None,
    model_root: Path,
    gpu_mode: str = "auto",
    variant: str = "desktop",
) -> servers.ServerPlan:
    try:
        servers.get_server(server_id)
    except ValueError as exc:
        raise OperationError(str(exc)) from exc
    if gpu_mode not in servers.GPU_MODES:
        raise OperationError("INVALID_PARAMS")
    if variant not in servers.DOCKER_VARIANTS:
        raise OperationError("INVALID_PARAMS")
    resolved_via = _resolve_serve_via(server_id, via, host, runtime_root)
    if variant != "desktop" and (server_id != "lmstudio" or resolved_via != "docker"):
        raise OperationError("INVALID_PARAMS")
    gpu = _gpu_intent(gpu_mode, host)
    if resolved_via == "native":
        try:
            return servers.build_native_plan(
                server_id,
                host_os=host.os,
                gpu=gpu,
                runtime_root=runtime_root,
            )
        except ValueError as exc:
            raise OperationError(str(exc)) from exc
    daemon = servers.docker_daemon_status()
    gpu_status = (
        servers.docker_gpu_status()
        if daemon == "READY" and gpu
        else "NOT_AVAILABLE"
    )
    try:
        return servers.build_docker_plan(
            server_id,
            gpu=gpu,
            model_id=model,
            hf_cache=model_root / "huggingface",
            daemon_status=daemon,
            gpu_status=gpu_status,
            variant=variant,
        )
    except ValueError as exc:
        raise OperationError(str(exc)) from exc


def _server_plan_payload(plan: servers.ServerPlan) -> dict[str, object]:
    payload: dict[str, object] = {
        "server_id": plan.server_id,
        "via": plan.via,
        "automated": plan.automated,
        "steps": [{"name": step.name, "argv": list(step.argv)} for step in plan.steps],
        "requires_gpu": plan.requires_gpu,
        "venv_required": plan.venv_required,
        "start_hint": servers.get_server(plan.server_id).start_hint,
    }
    if plan.verify_argv is not None:
        payload["verify_argv"] = list(plan.verify_argv)
    if plan.image is not None:
        payload["image"] = plan.image
        payload["community_image"] = plan.community_image
        if plan.container_name is not None:
            payload["container_name"] = plan.container_name
    if plan.error_code is not None:
        payload["error_code"] = plan.error_code
    if plan.instructions:
        payload["instructions"] = list(plan.instructions)
    return payload


def _serve_plan_op(
    server_id: str,
    *,
    via: str,
    host: HostInfo,
    runtime_root: Path,
    model: str | None,
    model_root: Path,
    gpu_mode: str = "auto",
    variant: str = "desktop",
) -> dict[str, object]:
    plan = _build_serve_plan(
        server_id,
        via=via,
        host=host,
        runtime_root=runtime_root,
        model=model,
        model_root=model_root,
        gpu_mode=gpu_mode,
        variant=variant,
    )
    return _server_plan_payload(plan)


def _select_base_python(host: HostInfo) -> Path:
    try:
        capabilities = inspect_host_capabilities(
            nvidia_driver_version=host.nvidia_driver_version
        )
        requirement = ProviderRuntimeRequirement(
            provider_id="vllm",
            profile="native",
            supported_os=frozenset({"linux"}),
            python_min=(3, 12),
            python_max_exclusive=(3, 14),
            accelerator=Accelerator.NVIDIA,
            environments=frozenset({RuntimeEnvironment.NATIVE}),
        )
        resolved = resolve_runtime(capabilities, requirement)
    except ValueError as exc:
        raise OperationError(str(exc)) from exc
    if resolved.status is not CompatibilityStatus.COMPATIBLE or resolved.python is None:
        raise OperationError(resolved.reason or "RUNTIME_INCOMPATIBLE")
    return resolved.python.executable


def _serve_execute_op(
    server_id: str,
    *,
    via: str,
    host: HostInfo,
    runtime_root: Path,
    model: str | None,
    model_root: Path,
    gpu_mode: str = "auto",
    variant: str = "desktop",
) -> dict[str, object]:
    plan = _build_serve_plan(
        server_id,
        via=via,
        host=host,
        runtime_root=runtime_root,
        model=model,
        model_root=model_root,
        gpu_mode=gpu_mode,
        variant=variant,
    )
    if not plan.automated:
        raise OperationError(plan.error_code or "INSTALL_VECTOR_NOT_AUTOMATED")
    base_python = _select_base_python(host) if plan.venv_required else None
    try:
        with _Progress(f"Installing server {server_id} via {plan.via}"):
            result = servers.execute_server_plan(
                plan,
                runtime_root=runtime_root,
                base_python=base_python,
            )
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise OperationError(str(exc) or exc.__class__.__name__) from exc
    payload: dict[str, object] = asdict(result)
    payload["server_id"] = plan.server_id
    payload["via"] = plan.via
    return payload


def _plan_install_op(
    provider: str,
    profile: str,
    host: HostInfo,
    *,
    runtime_root: Path,
) -> tuple[dict[str, object], ResolvedRuntime]:
    try:
        capabilities = inspect_host_capabilities(
            nvidia_driver_version=host.nvidia_driver_version
        )
        requirement = provider_runtime_requirement(
            provider, profile, host_os=capabilities.os
        )
        resolved_runtime = resolve_runtime(capabilities, requirement)
    except ValueError as exc:
        raise OperationError(str(exc)) from exc
    if resolved_runtime.status is not CompatibilityStatus.COMPATIBLE:
        raise OperationError(resolved_runtime.reason or "RUNTIME_INCOMPATIBLE")
    runtime_dir = runtime_root / provider / profile
    planned_python_executable = str(runtime_python(runtime_dir))
    try:
        plan = resolve_install(
            provider,
            profile,
            host,
            python_executable=planned_python_executable,
        )
    except ValueError as exc:
        raise OperationError(str(exc)) from exc
    return plan, resolved_runtime


def _execute_install_op(
    *,
    provider: str,
    profile: str,
    host: HostInfo,
    runtime_root: Path,
    model_root: Path,
    model: str | None,
    model_source: str,
    select_model: bool,
    resolved_runtime: ResolvedRuntime,
) -> dict[str, object]:
    if model is not None:
        try:
            resolve_paddle_model(model)
        except ValueError as exc:
            raise OperationError(str(exc)) from exc
    service = RuntimeManagementService(load_provider_manifest())
    try:
        with _Progress(f"Installing {provider}/{profile} runtime"):
            result = service.install_provider(
                provider_id=provider,
                profile=profile,
                host=host,
                runtime_root=runtime_root,
                resolved_runtime=resolved_runtime,
            )
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise OperationError(str(exc) or exc.__class__.__name__) from exc
    payload: dict[str, object] = asdict(result)
    selected = model
    if selected is None and select_model:
        candidates = _model_candidates(service, provider)
        if candidates:
            selected = _select_model(candidates)
    if selected is None:
        return payload
    model_payload = _pull_model(
        model_id=selected,
        profile=profile,
        source=model_source,
        runtime_root=runtime_root,
        model_root=model_root,
    )
    return {"install": payload, "model": model_payload}


def _run_document_ocr(
    *,
    python_executable: str,
    model_id: str,
    model_root: Path,
    document_bytes: bytes,
    timeout_seconds: int,
) -> OcrResult:
    return run_local_ocr(
        python_executable=python_executable,
        model_id=model_id,
        model_root=model_root,
        document_bytes=document_bytes,
        timeout_seconds=timeout_seconds,
    )


def _process_document(
    *,
    path: Path,
    profile: str,
    model: str,
    runtime_root: Path,
    model_root: Path,
    log_path: Path,
    timeout: int,
) -> dict[str, object]:
    if not path.is_file():
        raise OperationError("DOCUMENT_NOT_FOUND")
    try:
        document_bytes = path.read_bytes()
    except OSError as exc:
        raise OperationError(str(exc) or "DOCUMENT_READ_FAILED") from exc
    runtime_dir = runtime_root / "paddle-ocr" / profile
    python_path = runtime_python(runtime_dir)
    try:
        state = read_install_state(runtime_dir)
    except (ValueError, OSError) as exc:
        raise OperationError(str(exc) or "RUNTIME_STATE_UNREADABLE") from exc
    if state.status != "READY" or not python_path.is_file():
        raise OperationError("PADDLE_RUNTIME_NOT_READY")
    log = ProcessingLog(sink_path=log_path)

    def analyze(data: bytes) -> OcrResult:
        return _run_document_ocr(
            python_executable=str(python_path),
            model_id=model,
            model_root=model_root,
            document_bytes=data,
            timeout_seconds=timeout,
        )

    try:
        report = process_file(
            source_name=path.name,
            document_bytes=document_bytes,
            analyze=analyze,
            log=log,
        )
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        raise OperationError(str(exc) or exc.__class__.__name__) from exc
    return {**report.to_dict(), "log_path": str(log_path)}


def _require_confirm(params: dict[str, object]) -> None:
    if params.get("confirm") is not True:
        raise OperationError("CONFIRMATION_REQUIRED")


def _required_str(params: dict[str, object], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise OperationError("INVALID_PARAMS")
    return value


def _optional_str(params: dict[str, object], key: str, default: str) -> str:
    value = params.get(key, default)
    if not isinstance(value, str):
        raise OperationError("INVALID_PARAMS")
    return value


def _optional_str_or_none(params: dict[str, object], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise OperationError("INVALID_PARAMS")
    return value


def _optional_path(params: dict[str, object], key: str, default: str) -> Path:
    return Path(_optional_str(params, key, default))


def _optional_int(params: dict[str, object], key: str, default: int) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OperationError("INVALID_PARAMS")
    return value


def _dispatch_api(operation: str, params: dict[str, object]) -> dict[str, object]:
    if operation == "doctor":
        return _doctor_payload(inspect_host())
    service = RuntimeManagementService(load_provider_manifest())
    if operation == "providers.list":
        return {"providers": service.providers()}
    if operation == "models.list":
        return {"models": service.models()}
    if operation == "models.verify":
        return _verify_model(
            model_id=_required_str(params, "model_id"),
            model_root=_optional_path(params, "model_root", ".edi/models"),
        )
    if operation == "models.pull":
        _require_confirm(params)
        return _pull_model(
            model_id=_required_str(params, "model_id"),
            profile=_optional_str(params, "profile", "cpu"),
            source=_optional_str(params, "source", "HUGGINGFACE"),
            runtime_root=_optional_path(params, "runtime_root", ".edi/runtimes"),
            model_root=_optional_path(params, "model_root", ".edi/models"),
        )
    if operation == "status.summary":
        return _status_summary(
            inspect_host(),
            runtime_root=_optional_path(params, "runtime_root", ".edi/runtimes"),
            model_root=_optional_path(params, "model_root", ".edi/models"),
        )
    if operation == "serve.list":
        return _serve_list_payload(
            inspect_host(),
            runtime_root=_optional_path(params, "runtime_root", ".edi/runtimes"),
        )
    if operation == "serve.recommend":
        return _serve_recommend_payload()
    if operation in {"serve.plan", "serve.execute"}:
        via = _optional_str(params, "via", "auto")
        if via not in {"auto", "native", "docker"}:
            raise OperationError("INVALID_PARAMS")
        gpu_mode = _optional_str(params, "gpu", "auto")
        if gpu_mode not in {"auto", "on", "off"}:
            raise OperationError("INVALID_PARAMS")
        variant = _optional_str(params, "variant", "desktop")
        if variant not in {"desktop", "headless"}:
            raise OperationError("INVALID_PARAMS")
        server_id = _required_str(params, "server_id")
        if operation == "serve.plan":
            return _serve_plan_op(
                server_id,
                via=via,
                host=inspect_host(),
                runtime_root=_optional_path(params, "runtime_root", ".edi/runtimes"),
                model=_optional_str_or_none(params, "model"),
                model_root=_optional_path(params, "model_root", ".edi/models"),
                gpu_mode=gpu_mode,
                variant=variant,
            )
        _require_confirm(params)
        return _serve_execute_op(
            server_id,
            via=via,
            host=inspect_host(),
            runtime_root=_optional_path(params, "runtime_root", ".edi/runtimes"),
            model=_optional_str_or_none(params, "model"),
            model_root=_optional_path(params, "model_root", ".edi/models"),
            gpu_mode=gpu_mode,
            variant=variant,
        )
    if operation in {"install.plan", "install.execute"}:
        host = inspect_host()
        provider = _required_str(params, "provider_id")
        profile = _required_str(params, "profile")
        runtime_root = _optional_path(params, "runtime_root", ".edi/runtimes")
        plan, resolved_runtime = _plan_install_op(
            provider, profile, host, runtime_root=runtime_root
        )
        if operation == "install.plan":
            return plan
        _require_confirm(params)
        return _execute_install_op(
            provider=provider,
            profile=profile,
            host=host,
            runtime_root=runtime_root,
            model_root=_optional_path(params, "model_root", ".edi/models"),
            model=_optional_str_or_none(params, "model"),
            model_source=_optional_str(params, "model_source", "HUGGINGFACE"),
            select_model=False,
            resolved_runtime=resolved_runtime,
        )
    if operation == "process.file":
        return _process_document(
            path=Path(_required_str(params, "path")),
            profile=_optional_str(params, "profile", "cpu"),
            model=_optional_str(params, "model", "pp-ocrv6-medium"),
            runtime_root=_optional_path(params, "runtime_root", ".edi/runtimes"),
            model_root=_optional_path(params, "model_root", ".edi/models"),
            log_path=_optional_path(params, "log", ".edi/logs/processing.jsonl"),
            timeout=_optional_int(params, "timeout", 300),
        )
    raise OperationError("UNKNOWN_OPERATION")


def run_api_request(text: str) -> tuple[dict[str, object], int]:
    """Execute one standard JSON request; returns (response payload, exit code)."""
    try:
        request = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "operation": None, "error": {"code": "INVALID_REQUEST"}}, 2
    if not isinstance(request, dict):
        return {"ok": False, "operation": None, "error": {"code": "INVALID_REQUEST"}}, 2
    operation = request.get("operation")
    params = request.get("params", {})
    if not isinstance(operation, str) or not isinstance(params, dict):
        return {"ok": False, "operation": None, "error": {"code": "INVALID_REQUEST"}}, 2
    try:
        result = _dispatch_api(operation, params)
    except OperationError as exc:
        return {"ok": False, "operation": operation, "error": {"code": exc.code}}, 2
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        code = str(exc) or exc.__class__.__name__
        return {"ok": False, "operation": operation, "error": {"code": code}}, 2
    except Exception:
        return {"ok": False, "operation": operation, "error": {"code": "INTERNAL_ERROR"}}, 2
    return {"ok": True, "operation": operation, "result": result}, 0


def _parser(config: LocalConfig | None = None) -> argparse.ArgumentParser:
    cfg = config if config is not None else LocalConfig()
    default_runtime_root = Path(cfg.runtime_root) if cfg.runtime_root else Path(".edi/runtimes")
    default_model_root = Path(cfg.model_root) if cfg.model_root else Path(".edi/models")
    default_log = Path(cfg.log_path) if cfg.log_path else Path(".edi/logs/processing.jsonl")
    default_profile = cfg.profile or "cpu"
    default_source = cfg.model_source or "HUGGINGFACE"
    parser = argparse.ArgumentParser(prog="edi")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")

    config_parser = commands.add_parser(
        "config",
        help="show the effective local configuration, or edit it with --wizard",
    )
    config_parser.add_argument(
        "--wizard", action="store_true", help="interactive step-by-step editor (requires a TTY)"
    )
    config_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    config_parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="config file path"
    )

    log_parser = commands.add_parser("log", help="read the processing JSONL log")
    log_parser.add_argument("--path", type=Path, default=None, help="log file (defaults to config log_path)")
    log_parser.add_argument("--tail", type=int, default=50, help="show the last N lines (0 = all)")
    log_parser.add_argument("--follow", action="store_true", help="keep streaming new lines")
    log_parser.add_argument("--pretty", action="store_true", help="pretty-print JSON lines")

    ps_parser = commands.add_parser("ps", help="status summary: host, tier, providers, models, servers")
    ps_parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ps_parser.add_argument("--runtime-root", type=Path, default=default_runtime_root)
    ps_parser.add_argument("--model-root", type=Path, default=default_model_root)

    providers = commands.add_parser("providers")
    provider_commands = providers.add_subparsers(dest="provider_command", required=True)
    provider_commands.add_parser("list")

    models = commands.add_parser("models", aliases=["model"])
    model_commands = models.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("list")
    model_pull = model_commands.add_parser("pull")
    model_pull.add_argument("model_id", nargs="?", default=None)
    model_pull.add_argument("--profile", default=default_profile)
    model_pull.add_argument("--source", choices=("HUGGINGFACE", "BOS"), default=default_source)
    model_pull.add_argument("--yes", action="store_true")
    model_pull.add_argument("--runtime-root", type=Path, default=default_runtime_root)
    model_pull.add_argument("--model-root", type=Path, default=default_model_root)
    model_verify = model_commands.add_parser("verify")
    model_verify.add_argument("model_id")
    model_verify.add_argument("--model-root", type=Path, default=default_model_root)

    serve = commands.add_parser(
        "serve",
        help="local inference servers (ollama, lmstudio, vllm): detect, recommend, plan, install",
    )
    serve_commands = serve.add_subparsers(dest="serve_command", required=True)
    serve_list = serve_commands.add_parser("list", help="registry, ports and detection status")
    serve_list.add_argument("--json", action="store_true")
    serve_list.add_argument("--runtime-root", type=Path, default=default_runtime_root)
    serve_recommend = serve_commands.add_parser(
        "recommend", help="advisory VRAM-tier recommendations (never selects execution paths)"
    )
    serve_recommend.add_argument("--json", action="store_true")
    for serve_action in ("plan", "install"):
        sub = serve_commands.add_parser(
            serve_action, help="show the typed install vector" if serve_action == "plan" else "run the install vector (--yes required)"
        )
        sub.add_argument("--server", required=True, choices=tuple(servers.SERVER_DEFINITIONS))
        sub.add_argument("--via", choices=("auto", "native", "docker"), default="auto")
        sub.add_argument(
            "--gpu",
            choices=("auto", "on", "off"),
            default="auto",
            help="GPU intent for the vector: auto (host probe, default), on (require GPU, fail-closed), off (CPU vector)",
        )
        sub.add_argument(
            "--variant",
            choices=("desktop", "headless"),
            default="desktop",
            help="lmstudio docker image: desktop (linuxserver GUI, default) or headless (official API image)",
        )
        sub.add_argument("--model", default=None, help="model id for the vllm server image")
        sub.add_argument("--runtime-root", type=Path, default=default_runtime_root)
        sub.add_argument("--model-root", type=Path, default=default_model_root)
        if serve_action == "install":
            sub.add_argument("--yes", action="store_true")

    install = commands.add_parser("install")
    install.add_argument("--provider", default=cfg.provider_id)
    install.add_argument("--profile", default=cfg.profile)
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--yes", action="store_true")
    install.add_argument(
        "--model",
        default=cfg.model_id,
        help="provision this model after a successful install",
    )
    install.add_argument("--model-source", choices=("HUGGINGFACE", "BOS"), default=default_source)
    install.add_argument("--runtime-root", type=Path, default=default_runtime_root)
    install.add_argument("--model-root", type=Path, default=default_model_root)

    process = commands.add_parser("process")
    process.add_argument("path", type=Path)
    process.add_argument("--profile", default=default_profile)
    process.add_argument("--model", default=cfg.model_id or "pp-ocrv6-medium")
    process.add_argument("--runtime-root", type=Path, default=default_runtime_root)
    process.add_argument("--model-root", type=Path, default=default_model_root)
    process.add_argument("--log", type=Path, default=default_log)
    process.add_argument("--timeout", type=int, default=300)

    api = commands.add_parser(
        "api",
        help="standard JSON-over-stdio API: one request on stdin (or as argument), one response on stdout",
    )
    api.add_argument("request", nargs="?", default=None, help="JSON request; reads standard input when omitted")

    web = commands.add_parser(
        "web",
        help="read-only local web panel (stdlib http.server): host/provider/model views and install plans only",
    )
    web.add_argument(
        "--bind",
        "--hostname",
        dest="hostname",
        default=cfg.web_bind or "127.0.0.1",
        help="bind address (default 127.0.0.1; config key web_bind)",
    )
    web.add_argument("--port", type=int, default=cfg.web_port or 4099, help="listen port (default 4099)")
    web.add_argument("--runtime-root", type=Path, default=default_runtime_root)
    return parser


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    args = _parser(config).parse_args(argv)
    if args.command == "model":
        args.command = "models"

    if args.command == "api":
        text = args.request if args.request is not None else sys.stdin.read()
        payload, status = run_api_request(text)
        _emit(payload)
        return status

    if args.command == "web":
        server = build_server(
            args.hostname,
            args.port,
            api=run_api_request,
            runtime_root=str(args.runtime_root),
        )
        bound_port = server.server_address[1]
        print(
            f"edi web listening on http://{args.hostname}:{bound_port}/ "
            "(read-only, no authentication; Ctrl+C to stop)"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nedi web stopped")
        finally:
            server.server_close()
        return 0

    if args.command == "log":
        log_path = args.path if args.path is not None else Path(config.log_path or ".edi/logs/processing.jsonl")
        if args.tail < 0:
            print("INVALID_PARAMS")
            return 2
        if not log_path.is_file():
            print("LOG_NOT_FOUND")
            return 2
        try:
            lines = _log_lines(log_path, args.tail)
        except OSError as exc:
            print(str(exc) or "LOG_READ_FAILED")
            return 2
        for line in lines:
            print(_format_log_line(line, pretty=args.pretty))
        if args.follow:
            try:
                handle = log_path.open("r", encoding="utf-8", errors="replace")
            except OSError as exc:
                print(str(exc) or "LOG_READ_FAILED")
                return 2
            with handle:
                handle.seek(0, 2)
                try:
                    while True:
                        chunk = handle.readline()
                        if chunk:
                            print(_format_log_line(chunk.rstrip("\n"), pretty=args.pretty))
                        else:
                            time.sleep(1)
                except KeyboardInterrupt:
                    return 0
        return 0

    host = inspect_host()
    service = RuntimeManagementService(load_provider_manifest())

    if args.command == "doctor":
        _emit(_doctor_payload(host))
        return 0

    if args.command == "config":
        if args.wizard:
            try:
                _run_config_wizard(
                    config=load_config(args.config),
                    config_path=args.config,
                    service=service,
                )
            except OperationError as exc:
                print(exc.code)
                return 2
            return 0
        payload = _config_payload(
            host,
            config=config,
            config_path=args.config,
            runtime_root=Path(config.runtime_root or ".edi/runtimes"),
            model_root=Path(config.model_root or ".edi/models"),
            log_path=Path(config.log_path or ".edi/logs/processing.jsonl"),
        )
        if args.json:
            _emit(payload)
            return 0
        print(f"config: {payload['config_path']} ({'present' if payload['config_exists'] else 'missing'})")
        effective = payload["effective"]
        assert isinstance(effective, dict)
        for key in (
            "runtime_root", "model_root", "log_path", "provider_id",
            "profile", "model_id", "model_source", "web_bind", "web_port",
        ):
            print(f"{key}: {effective.get(key)}")
        host_payload = payload["host"]
        assert isinstance(host_payload, dict)
        print(
            f"host: os={host_payload.get('os')} arch={host_payload.get('architecture')} "
            f"docker={host_payload.get('docker')} nvidia_smi={host_payload.get('nvidia_smi')}"
        )
        print(f"tier: {payload['tier']} (vram_mib={payload['vram_mib']})")
        runtime_status = payload["runtime_status"]
        assert isinstance(runtime_status, list)
        for row in runtime_status:
            assert isinstance(row, dict)
            print(f"{row['provider_id']}/{row['profile']}: {row['status']}")
        server_rows = payload["servers"]
        assert isinstance(server_rows, list)
        for row in server_rows:
            assert isinstance(row, dict)
            print(f"server {row['server_id']}: {row['status']}")
        return 0

    if args.command == "ps":
        payload = _status_summary(
            host,
            runtime_root=args.runtime_root,
            model_root=args.model_root,
        )
        if args.json:
            _emit(payload)
            return 0
        print(f"tier: {payload['tier']} (vram_mib={payload['vram_mib']})")
        host_payload = payload["host"]
        assert isinstance(host_payload, dict)
        print(
            f"host: os={host_payload.get('os')} arch={host_payload.get('architecture')} "
            f"docker={host_payload.get('docker')} nvidia_smi={host_payload.get('nvidia_smi')}"
        )
        providers = payload["providers"]
        models = payload["models"]
        server_rows = payload["servers"]
        assert isinstance(providers, list) and isinstance(models, list) and isinstance(server_rows, list)
        print("providers:")
        for row in providers:
            assert isinstance(row, dict)
            print(f"  {row['provider_id']}/{row['profile']}: {row['status']}")
        print("models:")
        for row in models:
            assert isinstance(row, dict)
            print(f"  {row['provider_id']}/{row['model_id']}: {row['status']}")
        print("servers:")
        for row in server_rows:
            assert isinstance(row, dict)
            print(f"  {row['server_id']}: {row['status']}")
        return 0

    if args.command == "serve":
        if args.serve_command == "list":
            payload = _serve_list_payload(host, args.runtime_root)
            if args.json:
                _emit(payload)
                return 0
            servers_rows = payload["servers"]
            assert isinstance(servers_rows, list)
            for row in servers_rows:
                assert isinstance(row, dict)
                detection = row["detection"]
                assert isinstance(detection, dict)
                suffix = " (community image)" if row["community_image"] else ""
                print(
                    f"{row['server_id']}: port={row['default_port']} "
                    f"detect={detection['status']} native={row['native_vector']} "
                    f"image={row['image']}{suffix}"
                )
            return 0
        if args.serve_command == "recommend":
            payload = _serve_recommend_payload()
            if args.json:
                _emit(payload)
                return 0
            print(f"tier: {payload['tier']} (vram_mib={payload['vram_mib']})")
            recommendations = payload["recommendations"]
            assert isinstance(recommendations, list)
            for row in recommendations:
                assert isinstance(row, dict)
                reasons = ",".join(str(item) for item in row["reasons"])
                print(f"{row['server_id']}: {row['verdict']} ({reasons})")
            return 0
        if args.serve_command == "plan":
            try:
                payload = _serve_plan_op(
                    args.server,
                    via=args.via,
                    host=host,
                    runtime_root=args.runtime_root,
                    model=args.model,
                    model_root=args.model_root,
                    gpu_mode=args.gpu,
                    variant=args.variant,
                )
            except OperationError as exc:
                print(exc.code)
                return 2
            _emit(payload)
            return 0
        if not args.yes:
            print("INSTALL_CONFIRMATION_REQUIRED_USE_YES")
            return 2
        try:
            payload = _serve_execute_op(
                args.server,
                via=args.via,
                host=host,
                runtime_root=args.runtime_root,
                model=args.model,
                model_root=args.model_root,
                gpu_mode=args.gpu,
                variant=args.variant,
            )
        except OperationError as exc:
            print(exc.code)
            return 2
        _emit(payload)
        return 0

    if args.command == "providers":
        for provider in service.providers():
            profiles = provider["profiles"]
            assert isinstance(profiles, list)
            print(f"{provider['provider_id']}: {', '.join(str(item) for item in profiles)}")
        return 0

    if args.command == "models":
        if args.model_command == "list":
            for model in service.models():
                print(f"{model['provider_id']}: {model['model_id']}")
            return 0
        if args.model_command == "verify":
            try:
                payload = _verify_model(model_id=args.model_id, model_root=args.model_root)
            except (ValueError, OSError) as exc:
                print(str(exc))
                return 2
            _emit(payload)
            return 0
        model_id = args.model_id if args.model_id is not None else config.model_id
        if model_id is None:
            print("MODEL_ID_REQUIRED")
            return 2
        if not args.yes:
            print("MODEL_PULL_CONFIRMATION_REQUIRED_USE_YES")
            return 2
        try:
            payload = _pull_model(
                model_id=model_id,
                profile=args.profile,
                source=args.source,
                runtime_root=args.runtime_root,
                model_root=args.model_root,
            )
        except OperationError as exc:
            print(exc.code)
            return 2
        _emit(payload)
        return 0

    if args.command == "process":
        try:
            payload = _process_document(
                path=args.path,
                profile=args.profile,
                model=args.model,
                runtime_root=args.runtime_root,
                model_root=args.model_root,
                log_path=args.log,
                timeout=args.timeout,
            )
        except OperationError as exc:
            print(exc.code)
            return 2
        _emit(payload)
        return 0

    if args.command == "install":
        if args.provider is None:
            print("PROVIDER_REQUIRED")
            return 2
        if args.profile is None:
            print("PROFILE_REQUIRED")
            return 2
        try:
            plan, resolved_runtime = _plan_install_op(
                args.provider, args.profile, host, runtime_root=args.runtime_root
            )
        except OperationError as exc:
            print(exc.code)
            return 2
        if args.dry_run:
            _emit(plan)
            return 0
        if not args.yes:
            print("INSTALL_CONFIRMATION_REQUIRED_USE_YES")
            return 2
        try:
            payload = _execute_install_op(
                provider=args.provider,
                profile=args.profile,
                host=host,
                runtime_root=args.runtime_root,
                model_root=args.model_root,
                model=args.model,
                model_source=args.model_source,
                select_model=_stdin_is_tty(),
                resolved_runtime=resolved_runtime,
            )
        except OperationError as exc:
            print(exc.code)
            return 2
        _emit(payload)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
