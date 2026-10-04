import json
from pathlib import Path

from edi_reference.application.provider_manifest import load_provider_manifest
from edi_reference.application.qwen3_vl_install import build_qwen3_vl_install_plan
from edi_reference.application.runtime_bootstrap import (
    Accelerator,
    CompatibilityStatus,
    HostCapabilities,
    PythonInterpreter,
    resolve_runtime,
)
from edi_reference.application.runtime_management import RuntimeManagementService
from edi_reference.application.runtime_requirements import provider_runtime_requirement
from edi_reference.cli import HostInfo, main, resolve_install


def test_manifest_exposes_new_provider_families() -> None:
    manifest = load_provider_manifest()

    paddle_vl = manifest.providers["paddleocr-vl"]
    assert paddle_vl.runtime_family == "paddle-vl"
    assert paddle_vl.profiles == ("cpu", "nvidia")
    assert paddle_vl.models == ("paddleocr-vl-1.6", "hpd-parsing")
    assert paddle_vl.required is False

    qwen = manifest.providers["qwen3-vl"]
    assert qwen.runtime_family == "pytorch-transformers"
    assert qwen.profiles == ("cpu", "nvidia", "quantized")
    assert qwen.models == ("qwen3-vl-4b", "qwen3-vl-8b", "qwen3-vl-30b-a3b")
    assert qwen.required is False


def test_qwen3_vl_runtime_requirements() -> None:
    cpu = provider_runtime_requirement("qwen3-vl", "cpu", host_os="linux")
    assert cpu.accelerator is Accelerator.CPU
    assert cpu.supported_os == frozenset({"linux", "windows", "darwin"})

    nvidia = provider_runtime_requirement("qwen3-vl", "nvidia", host_os="windows")
    assert nvidia.accelerator is Accelerator.NVIDIA
    assert nvidia.supported_os == frozenset({"linux", "windows"})

    quantized = provider_runtime_requirement("qwen3-vl", "quantized", host_os="linux")
    assert quantized.accelerator is Accelerator.NVIDIA
    assert quantized.profile == "quantized"

    try:
        provider_runtime_requirement("qwen3-vl", "mps", host_os="darwin")
    except ValueError as exc:
        assert str(exc) == "UNSUPPORTED_QWEN3_VL_PROFILE"
    else:
        raise AssertionError("expected unsupported qwen3-vl profile rejection")


def test_paddleocr_vl_installer_stays_fail_closed() -> None:
    try:
        provider_runtime_requirement("paddleocr-vl", "cpu", host_os="linux")
    except ValueError as exc:
        assert str(exc) == "RUNTIME_REQUIREMENT_NOT_IMPLEMENTED"
    else:
        raise AssertionError("expected fail-closed paddleocr-vl requirement")


def test_paddleocr_vl_install_guard_is_fail_closed() -> None:
    from edi_reference.application.runtime_bootstrap import ResolvedRuntime, RuntimeEnvironment

    service = RuntimeManagementService(load_provider_manifest())
    fake = ResolvedRuntime(
        provider_id="paddleocr-vl",
        profile="cpu",
        status=CompatibilityStatus.COMPATIBLE,
        environment=RuntimeEnvironment.NATIVE,
        accelerator=Accelerator.CPU,
        python=PythonInterpreter(Path("/usr/bin/python3"), (3, 12, 0)),
    )
    try:
        service.install_provider(
            provider_id="paddleocr-vl",
            profile="cpu",
            host=HostInfo("linux", "x86_64", False, False),
            runtime_root=Path(".edi/runtimes"),
            resolved_runtime=fake,
        )
    except ValueError as exc:
        assert str(exc) == "INSTALLER_NOT_IMPLEMENTED_FOR_PROVIDER"
    else:
        raise AssertionError("expected fail-closed paddleocr-vl installer")


def test_qwen3_vl_plan_steps_per_profile() -> None:
    cpu = build_qwen3_vl_install_plan(python_executable="/venv/python", profile="cpu")
    cpu_text = " ".join(" ".join(step.argv) for step in cpu.steps)
    assert "torch>=2.4" in cpu_text
    assert "cu126" not in cpu_text
    assert "bitsandbytes" not in cpu_text
    assert "transformers>=4.57.0" in cpu_text
    assert "qwen-vl-utils" in cpu_text
    assert cpu.verify_argv[-1].startswith("import torch, transformers")

    nvidia = build_qwen3_vl_install_plan(python_executable="/venv/python", profile="nvidia")
    nvidia_text = " ".join(" ".join(step.argv) for step in nvidia.steps)
    assert "https://download.pytorch.org/whl/cu126" in nvidia_text

    quantized = build_qwen3_vl_install_plan(
        python_executable="/venv/python", profile="quantized"
    )
    quantized_text = " ".join(" ".join(step.argv) for step in quantized.steps)
    assert "bitsandbytes>=0.43" in quantized_text

    try:
        build_qwen3_vl_install_plan(python_executable="/venv/python", profile="mps")
    except ValueError as exc:
        assert str(exc) == "UNSUPPORTED_QWEN3_VL_PROFILE"
    else:
        raise AssertionError("expected unsupported profile rejection")


def test_qwen3_vl_plan_install_exposes_steps() -> None:
    plan = resolve_install("qwen3-vl", "cpu", HostInfo("linux", "x86_64", False, False))

    assert plan["provider"] == "qwen3-vl"
    assert plan["status"] == "PLANNED"
    steps = plan["steps"]
    assert isinstance(steps, list) and len(steps) >= 3
    assert steps[0]["name"] == "upgrade-pip"
    assert "verify_argv" in plan


def test_qwen3_vl_nvidia_plan_requires_nvidia_runtime() -> None:
    try:
        resolve_install("qwen3-vl", "nvidia", HostInfo("windows", "amd64", True, False))
    except ValueError as exc:
        assert str(exc) == "NVIDIA_RUNTIME_NOT_DETECTED"
    else:
        raise AssertionError("expected NVIDIA runtime rejection")


def test_qwen3_vl_resolves_compatible_runtime() -> None:
    capabilities = HostCapabilities(
        os="linux",
        architecture="x86_64",
        python_interpreters=(PythonInterpreter(Path("/usr/bin/python3"), (3, 12, 0)),),
        nvidia=True,
        nvidia_driver_version=(616, 92, 0),
    )
    requirement = provider_runtime_requirement("qwen3-vl", "nvidia", host_os="linux")

    resolved = resolve_runtime(capabilities, requirement)

    assert resolved.status is CompatibilityStatus.COMPATIBLE
    assert resolved.accelerator is Accelerator.NVIDIA
    assert resolved.python is not None


def test_cli_dry_run_qwen3_vl_cpu(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    from edi_reference.application.runtime_bootstrap import HostCapabilities, PythonInterpreter

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "edi_reference.cli.inspect_host",
        lambda: HostInfo("linux", "x86_64", False, False),
    )
    monkeypatch.setattr(
        "edi_reference.cli.inspect_host_capabilities",
        lambda **_: HostCapabilities(
            os="linux",
            architecture="x86_64",
            python_interpreters=(
                PythonInterpreter(Path("/usr/bin/python3"), (3, 12, 0)),
            ),
        ),
    )

    code = main(["install", "--provider", "qwen3-vl", "--profile", "cpu", "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["provider"] == "qwen3-vl"
    step_names = [step["name"] for step in payload["steps"]]
    assert "install-qwen3-vl" in step_names


def test_cli_install_paddleocr_vl_fails_closed(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "edi_reference.cli.inspect_host",
        lambda: HostInfo("linux", "x86_64", False, False),
    )

    code = main(
        ["install", "--provider", "paddleocr-vl", "--profile", "cpu", "--dry-run"]
    )

    assert code == 2
    assert "RUNTIME_REQUIREMENT_NOT_IMPLEMENTED" in capsys.readouterr().out
