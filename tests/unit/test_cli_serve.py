import json
import subprocess
import sys
from pathlib import Path

from edi_reference.application import servers
from edi_reference.application.runtime_installer import StepResult
from edi_reference.cli import HostInfo, main, run_api_request


def _windows_host() -> HostInfo:
    return HostInfo("windows", "amd64", False, False)


def _linux_host() -> HostInfo:
    return HostInfo("linux", "x86_64", True, False)


def _linux_gpu_host() -> HostInfo:
    return HostInfo("linux", "x86_64", True, True, (616, 92, 0))


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["argv"], returncode, stdout, "")


def _patch_daemon(monkeypatch, status: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.servers.docker_daemon_status",
        lambda **_: status,
    )


def _patch_gpu(monkeypatch, status: str) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.servers.docker_gpu_status",
        lambda **_: status,
    )


# --- registry / detection ------------------------------------------------------


def test_native_vector_status_matrix() -> None:
    assert servers.native_vector_status("ollama", "windows").status == "AUTOMATED"
    assert servers.native_vector_status("ollama", "darwin").status == "AUTOMATED"

    linux_ollama = servers.native_vector_status("ollama", "linux")
    assert linux_ollama.status == "AUTOMATED"
    assert linux_ollama.error_code is None
    assert servers.native_vector_status("ollama", "freebsd").status == "UNSUPPORTED"
    assert (
        servers.native_vector_status("ollama", "freebsd").error_code
        == "INSTALL_VECTOR_UNSUPPORTED"
    )

    windows_vllm = servers.native_vector_status("vllm", "windows")
    assert windows_vllm.status == "UNSUPPORTED"
    assert windows_vllm.error_code == "VLLM_UNSUPPORTED_ON_HOST"
    assert servers.native_vector_status("vllm", "linux").status == "AUTOMATED"

    lmstudio = servers.native_vector_status("lmstudio", "windows")
    assert lmstudio.status == "MANUAL"
    assert lmstudio.error_code == "INSTALL_VECTOR_NOT_AUTOMATED"
    assert servers.native_vector_status("lmstudio", "linux").status == "MANUAL"


def test_unknown_server_is_rejected() -> None:
    try:
        servers.get_server("nope")
    except ValueError as exc:
        assert str(exc) == "UNKNOWN_SERVER"
    else:
        raise AssertionError("expected UNKNOWN_SERVER")


def test_detect_server_without_executable_is_not_installed() -> None:
    detection = servers.detect_server("ollama", which=lambda _: None)

    assert detection.status == "NOT_INSTALLED"
    assert detection.version is None


def test_detect_server_probes_version(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.servers._run_capture",
        lambda argv, timeout: _completed(0, "ollama 0.9.1\n"),
    )

    detection = servers.detect_server("ollama", which=lambda _: "/usr/bin/ollama")

    assert detection.status == "INSTALLED"
    assert detection.version == "ollama 0.9.1"


def test_detect_server_probe_failure_is_unknown(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.servers._run_capture",
        lambda argv, timeout: _completed(1),
    )

    detection = servers.detect_server("ollama", which=lambda _: "/usr/bin/ollama")

    assert detection.status == "UNKNOWN"


def test_parse_vram_mib_handles_query_output() -> None:
    assert servers.parse_vram_mib("NVIDIA GeForce RTX 3060, 12288 MiB") == 12288
    assert servers.parse_vram_mib("16256 MiB") == 16256
    assert servers.parse_vram_mib("4096") == 4096
    assert servers.parse_vram_mib(None) is None
    assert servers.parse_vram_mib("") is None
    assert servers.parse_vram_mib("0 MiB") is None
    assert servers.parse_vram_mib("garbage") is None


# --- serve plan (native vectors) ----------------------------------------------


def test_serve_plan_native_windows_ollama(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _windows_host)

    code = main(["serve", "plan", "--server", "ollama", "--via", "native"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["via"] == "native"
    assert payload["automated"] is True
    assert payload["steps"][0]["argv"][:2] == ["winget", "install"]
    assert payload["verify_argv"] == ["ollama", "--version"]


def test_serve_auto_on_linux_without_docker_uses_native_bootstrap(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    _patch_daemon(monkeypatch, "NOT_INSTALLED")

    code = main(["serve", "plan", "--server", "ollama"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["via"] == "native"
    assert payload["automated"] is True
    argv = payload["steps"][0]["argv"]
    assert argv[:4] == [
        sys.executable,
        "-m",
        "edi_reference.application.server_bootstrap",
        "ollama",
    ]
    assert argv[4] == str(Path(".edi/runtimes/ollama/native"))
    assert payload["verify_argv"] == [
        str(Path(".edi/runtimes/ollama/native/bin/ollama")),
        "--version",
    ]
    assert payload["start_hint"] == "ollama serve"


def test_serve_install_manual_vector_fails_closed(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    monkeypatch.setattr(
        "edi_reference.application.servers.detect_server",
        lambda server_id, **_: servers.ServerDetection(
            server_id, "NOT_INSTALLED", None, None
        ),
    )

    code = main(["serve", "install", "--server", "lmstudio", "--via", "native", "--yes"])

    assert code == 2
    assert "INSTALL_VECTOR_NOT_AUTOMATED" in capsys.readouterr().out
    assert not (tmp_path / ".edi").exists()


def test_serve_install_requires_yes(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _windows_host)

    code = main(["serve", "install", "--server", "ollama", "--via", "native"])

    assert code == 2
    assert "INSTALL_CONFIRMATION_REQUIRED_USE_YES" in capsys.readouterr().out


def test_serve_plan_vllm_native_requires_gpu(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)

    code = main(["serve", "plan", "--server", "vllm", "--via", "native"])

    assert code == 2
    assert "VLLM_REQUIRES_GPU" in capsys.readouterr().out


def test_serve_plan_vllm_native_on_windows_is_unsupported(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _windows_host)

    code = main(["serve", "plan", "--server", "vllm", "--via", "native"])

    assert code == 2
    assert "VLLM_UNSUPPORTED_ON_HOST" in capsys.readouterr().out


# --- serve plan (docker vectors) ----------------------------------------------


def test_serve_plan_docker_vllm_builds_whitelisted_gpu_vector(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_gpu_host)
    _patch_daemon(monkeypatch, "READY")
    _patch_gpu(monkeypatch, "READY")

    code = main(
        [
            "serve", "plan", "--server", "vllm", "--via", "docker",
            "--model", "org/model-v1",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["image"] == "vllm/vllm-openai:latest"
    assert payload["community_image"] is False
    argv = payload["steps"][0]["argv"]
    assert argv[:3] == ["docker", "run", "-d"]
    assert "--gpus=all" in argv
    assert "--ipc=host" in argv
    assert argv[-2:] == ["--model", "org/model-v1"]
    assert payload["verify_argv"][-1] == "edi-vllm"


def test_serve_plan_docker_vllm_rejects_missing_model(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_gpu_host)
    _patch_daemon(monkeypatch, "READY")
    _patch_gpu(monkeypatch, "READY")

    code = main(["serve", "plan", "--server", "vllm", "--via", "docker"])

    assert code == 2
    assert "INVALID_MODEL_ID" in capsys.readouterr().out


def test_serve_plan_docker_labels_lmstudio_community_image(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    _patch_daemon(monkeypatch, "READY")

    code = main(["serve", "plan", "--server", "lmstudio", "--via", "docker"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["image"] == "linuxserver/lm-studio:latest"
    assert payload["community_image"] is True
    assert "--gpus=all" not in payload["steps"][0]["argv"]


def test_serve_plan_docker_without_daemon_is_unavailable(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    _patch_daemon(monkeypatch, "NOT_INSTALLED")

    code = main(["serve", "plan", "--server", "ollama", "--via", "docker"])

    assert code == 2
    assert "DOCKER_NOT_AVAILABLE" in capsys.readouterr().out


def test_serve_plan_docker_gpu_host_without_toolkit_fails_closed(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_gpu_host)
    _patch_daemon(monkeypatch, "READY")
    _patch_gpu(monkeypatch, "NOT_AVAILABLE")

    code = main(["serve", "plan", "--server", "ollama", "--via", "docker"])

    assert code == 2
    assert "NVIDIA_CONTAINER_TOOLKIT_NOT_DETECTED" in capsys.readouterr().out


def test_serve_plan_gpu_on_without_toolkit_fails_closed(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_gpu_host)
    _patch_daemon(monkeypatch, "READY")
    _patch_gpu(monkeypatch, "NOT_AVAILABLE")

    code = main(["serve", "plan", "--server", "ollama", "--via", "docker", "--gpu", "on"])

    assert code == 2
    assert "NVIDIA_CONTAINER_TOOLKIT_NOT_DETECTED" in capsys.readouterr().out


def test_serve_plan_gpu_off_skips_toolkit_fail_closed(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_gpu_host)
    _patch_daemon(monkeypatch, "READY")
    _patch_gpu(monkeypatch, "NOT_AVAILABLE")

    code = main(
        ["serve", "plan", "--server", "ollama", "--via", "docker", "--gpu", "off"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["automated"] is True
    argv = payload["steps"][0]["argv"]
    assert argv[:3] == ["docker", "run", "-d"]
    assert "--gpus=all" not in argv


def test_serve_plan_gpu_off_forces_vllm_gpu_requirement(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_gpu_host)
    _patch_daemon(monkeypatch, "READY")
    _patch_gpu(monkeypatch, "READY")

    code = main(
        [
            "serve", "plan", "--server", "vllm", "--via", "docker",
            "--model", "org/model-v1", "--gpu", "off",
        ]
    )

    assert code == 2
    assert "VLLM_REQUIRES_GPU" in capsys.readouterr().out


def test_serve_plan_lmstudio_headless_docker_uses_official_image(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    _patch_daemon(monkeypatch, "READY")

    code = main(
        [
            "serve", "plan", "--server", "lmstudio", "--via", "docker",
            "--variant", "headless",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["image"] == "lmstudio/llmster-preview:latest"
    assert payload["container_name"] == "edi-lm-studio-headless"
    assert payload["community_image"] is False
    argv = payload["steps"][0]["argv"]
    assert "-p" in argv and "1234:1234" in argv
    assert "3000:3000" not in argv
    assert "3001:3001" not in argv
    assert payload["verify_argv"] == [
        "docker", "inspect", "-f", "{{.State.Status}}", "edi-lm-studio-headless",
    ]


def test_serve_plan_variant_headless_rejected_for_non_lmstudio(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)

    code = main(
        ["serve", "plan", "--server", "ollama", "--via", "docker", "--variant", "headless"]
    )

    assert code == 2
    assert "INVALID_PARAMS" in capsys.readouterr().out


def test_detect_server_reads_runtime_state_without_path_entry(tmp_path) -> None:
    state_dir = tmp_path / "lmstudio" / "docker"
    state_dir.mkdir(parents=True)
    (state_dir / "install-state.json").write_text(
        json.dumps({"status": "READY"}), encoding="utf-8"
    )

    detection = servers.detect_server(
        "lmstudio", which=lambda _: None, runtime_root=tmp_path
    )

    assert detection.status == "INSTALLED"
    assert detection.version is None


def test_detect_server_probes_runtime_binary_not_on_path(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    binary_dir = tmp_path / "ollama" / "native" / "bin"
    binary_dir.mkdir(parents=True)
    binary = binary_dir / "ollama"
    binary.write_bytes(b"")
    monkeypatch.setattr(
        "edi_reference.application.servers._run_capture",
        lambda argv, timeout: _completed(0, "ollama 0.11.1\n"),
    )

    detection = servers.detect_server(
        "ollama", which=lambda _: None, runtime_root=tmp_path
    )

    assert detection.status == "INSTALLED"
    assert detection.version == "ollama 0.11.1"
    assert detection.executable == str(binary)


def test_detect_server_runtime_binary_probe_failure_is_unknown(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    binary_dir = tmp_path / "ollama" / "native" / "bin"
    binary_dir.mkdir(parents=True)
    (binary_dir / "ollama").write_bytes(b"")
    monkeypatch.setattr(
        "edi_reference.application.servers._run_capture",
        lambda argv, timeout: _completed(1),
    )

    detection = servers.detect_server(
        "ollama", which=lambda _: None, runtime_root=tmp_path
    )

    assert detection.status == "UNKNOWN"


def test_serve_list_passes_runtime_root_to_detection(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    seen: list[object] = []

    def fake_detect(server_id, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(kwargs.get("runtime_root"))
        return servers.ServerDetection(server_id, "NOT_INSTALLED", None, None)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    monkeypatch.setattr("edi_reference.application.servers.detect_server", fake_detect)

    runtime_root = tmp_path / "custom-runtimes"
    code = main(["serve", "list", "--json", "--runtime-root", str(runtime_root)])
    capsys.readouterr()

    assert code == 0
    assert seen and all(entry == runtime_root for entry in seen)


def test_serve_install_linux_ollama_writes_state_after_bootstrap_steps(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    executed: list[tuple[str, ...]] = []

    def fake_steps(steps, **kwargs):  # type: ignore[no-untyped-def]
        for step in steps:
            executed.append(tuple(step.argv))
        return tuple(StepResult(step.name, 0) for step in steps)

    monkeypatch.setattr("edi_reference.application.servers.execute_steps", fake_steps)
    monkeypatch.setattr(
        "edi_reference.application.servers.verify_runtime",
        lambda argv, **_: StepResult("verify-runtime", 0),
    )

    code = main(["serve", "install", "--server", "ollama", "--via", "native", "--yes"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "READY"
    assert executed and executed[0][1:3] == (
        "-m",
        "edi_reference.application.server_bootstrap",
    )
    state_path = tmp_path / ".edi" / "runtimes" / "ollama" / "native" / "install-state.json"
    assert state_path.is_file()
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "READY"


# --- serve execute -------------------------------------------------------------


def test_serve_execute_native_writes_install_state(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _windows_host)
    monkeypatch.setattr(
        "edi_reference.application.servers.execute_steps",
        lambda steps, **_: tuple(StepResult(step.name, 0) for step in steps),
    )
    monkeypatch.setattr(
        "edi_reference.application.servers.verify_runtime",
        lambda argv, **_: StepResult("verify-runtime", 0),
    )

    code = main(
        ["serve", "install", "--server", "ollama", "--via", "native", "--yes"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "READY"
    assert payload["provider_id"] == "ollama"
    assert payload["profile"] == "native"
    state_path = tmp_path / ".edi" / "runtimes" / "ollama" / "native" / "install-state.json"
    assert state_path.is_file()


def test_serve_execute_docker_runs_whitelisted_vector(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    _patch_daemon(monkeypatch, "READY")
    executed: list[tuple[str, ...]] = []

    def fake_steps(steps, **kwargs):  # type: ignore[no-untyped-def]
        for step in steps:
            executed.append(tuple(step.argv))
        return tuple(StepResult(step.name, 0) for step in steps)

    monkeypatch.setattr("edi_reference.application.servers.execute_steps", fake_steps)
    monkeypatch.setattr(
        "edi_reference.application.servers.verify_container",
        lambda name, **_: StepResult("verify-container", 0),
    )

    code = main(
        ["serve", "install", "--server", "ollama", "--via", "docker", "--yes"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "READY"
    assert payload["profile"] == "docker"
    assert executed and executed[0][:3] == ("docker", "run", "-d")
    assert "ollama/ollama:latest" in executed[0]
    assert "--gpus=all" not in executed[0]
    state_path = tmp_path / ".edi" / "runtimes" / "ollama" / "docker" / "install-state.json"
    assert state_path.is_file()


def test_serve_execute_failed_step_writes_failed_state(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    from edi_reference.application.runtime_installer import InstallStepFailed

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _windows_host)

    def failing_steps(steps, **kwargs):  # type: ignore[no-untyped-def]
        results = (StepResult(steps[0].name, 1),)
        raise InstallStepFailed(steps[0].name, results)

    monkeypatch.setattr("edi_reference.application.servers.execute_steps", failing_steps)

    code = main(
        ["serve", "install", "--server", "ollama", "--via", "native", "--yes"]
    )

    assert code == 2
    assert "INSTALL_STEP_FAILED" in capsys.readouterr().out
    state_path = tmp_path / ".edi" / "runtimes" / "ollama" / "native" / "install-state.json"
    assert state_path.is_file()
    assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "FAILED"


# --- list / recommend ----------------------------------------------------------


def test_serve_list_reports_registry_and_detection(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli.inspect_host", _linux_host)
    monkeypatch.setattr(
        "edi_reference.application.servers.detect_server",
        lambda server_id, **_: servers.ServerDetection(
            server_id, "NOT_INSTALLED", None, None
        ),
    )

    code = main(["serve", "list", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    ids = [row["server_id"] for row in payload["servers"]]
    assert ids == ["ollama", "lmstudio", "vllm"]
    lmstudio = payload["servers"][1]
    assert lmstudio["community_image"] is True
    assert lmstudio["default_port"] == 1234
    assert lmstudio["detection"]["status"] == "NOT_INSTALLED"
    assert lmstudio["native_vector"] == "MANUAL"


def test_serve_recommend_uses_tier_map(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "edi_reference.cli._nvidia_query",
        lambda field: "NVIDIA GeForce RTX 3060, 12288 MiB"
        if field == "memory.total"
        else None,
    )

    code = main(["serve", "recommend", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["tier"] == "gpu-mid"
    assert payload["vram_mib"] == 12288
    verdicts = {row["server_id"]: row["verdict"] for row in payload["recommendations"]}
    assert verdicts["ollama"] == "RECOMMENDED"
    assert verdicts["lmstudio"] == "RECOMMENDED"
    assert verdicts["vllm"] == "NOT_RECOMMENDED"


def test_serve_recommend_text_output(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli._nvidia_query", lambda field: None)

    code = main(["serve", "recommend"])
    out = capsys.readouterr().out

    assert code == 0
    assert "tier: UNKNOWN" in out
    assert "ollama: UNKNOWN" in out


# --- API parity ----------------------------------------------------------------


def test_api_serve_plan_unknown_server() -> None:
    payload, status = run_api_request(
        json.dumps({"operation": "serve.plan", "params": {"server_id": "nope"}})
    )

    assert status == 2
    assert payload["error"]["code"] == "UNKNOWN_SERVER"


def test_api_serve_plan_rejects_unknown_via() -> None:
    payload, status = run_api_request(
        json.dumps(
            {"operation": "serve.plan", "params": {"server_id": "ollama", "via": "shell"}}
        )
    )

    assert status == 2
    assert payload["error"]["code"] == "INVALID_PARAMS"


def test_api_serve_plan_rejects_invalid_gpu() -> None:
    payload, status = run_api_request(
        json.dumps(
            {"operation": "serve.plan", "params": {"server_id": "ollama", "gpu": "yes"}}
        )
    )

    assert status == 2
    assert payload["error"]["code"] == "INVALID_PARAMS"


def test_api_serve_plan_rejects_invalid_variant() -> None:
    payload, status = run_api_request(
        json.dumps(
            {
                "operation": "serve.plan",
                "params": {"server_id": "lmstudio", "variant": "minimal"},
            }
        )
    )

    assert status == 2
    assert payload["error"]["code"] == "INVALID_PARAMS"


def test_api_serve_plan_rejects_headless_variant_for_non_lmstudio() -> None:
    payload, status = run_api_request(
        json.dumps(
            {
                "operation": "serve.plan",
                "params": {
                    "server_id": "ollama",
                    "via": "docker",
                    "variant": "headless",
                },
            }
        )
    )

    assert status == 2
    assert payload["error"]["code"] == "INVALID_PARAMS"


def test_api_serve_plan_returns_start_hint() -> None:
    payload, status = run_api_request(
        json.dumps({"operation": "serve.plan", "params": {"server_id": "ollama"}})
    )

    assert status == 0
    assert payload["ok"] is True
    assert payload["result"]["start_hint"] == "ollama serve"  # type: ignore[index]


def test_api_serve_execute_requires_confirm() -> None:
    payload, status = run_api_request(
        json.dumps({"operation": "serve.execute", "params": {"server_id": "ollama"}})
    )

    assert status == 2
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_api_serve_list_returns_registry(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.servers.detect_server",
        lambda server_id, **_: servers.ServerDetection(
            server_id, "NOT_INSTALLED", None, None
        ),
    )

    payload, status = run_api_request(json.dumps({"operation": "serve.list"}))

    assert status == 0
    assert payload["ok"] is True
    assert len(payload["result"]["servers"]) == 3  # type: ignore[index]
