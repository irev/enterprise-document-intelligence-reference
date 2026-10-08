from edi_reference.cli import HostInfo, main, resolve_install


def test_resolve_cpu_provider_without_accelerator() -> None:
    host = HostInfo("linux", "x86_64", False, False)

    plan = resolve_install("paddle-ocr", "cpu", host)

    assert plan["provider"] == "paddle-ocr"
    assert plan["profile"] == "cpu"
    assert plan["status"] == "PLANNED"


def test_reject_nvidia_profile_without_nvidia_runtime() -> None:
    host = HostInfo("windows", "amd64", True, False)

    try:
        resolve_install("qwen25-vl-7b", "nvidia", host)
    except ValueError as exc:
        assert str(exc) == "NVIDIA_RUNTIME_NOT_DETECTED"
    else:
        raise AssertionError("expected NVIDIA runtime rejection")


def test_reject_mps_outside_macos() -> None:
    host = HostInfo("linux", "x86_64", False, False)

    try:
        resolve_install("surya", "mps", host)
    except ValueError as exc:
        assert str(exc) == "MPS_REQUIRES_MACOS"
    else:
        raise AssertionError("expected MPS platform rejection")


def test_cli_install_requires_explicit_confirmation(capsys) -> None:
    result = main(["install", "--provider", "paddle-ocr", "--profile", "cpu"])

    assert result == 2
    assert "INSTALL_CONFIRMATION_REQUIRED_USE_YES" in capsys.readouterr().out


def test_cli_dry_run_rejects_windows_nvidia_before_planning(monkeypatch, capsys) -> None:
    from edi_reference.application.runtime_bootstrap import HostCapabilities, PythonInterpreter
    from pathlib import Path

    monkeypatch.setattr(
        "edi_reference.cli.inspect_host",
        lambda: HostInfo("windows", "amd64", False, True, (616, 92, 0)),
    )
    monkeypatch.setattr(
        "edi_reference.cli.inspect_host_capabilities",
        lambda **_: HostCapabilities(
            os="windows",
            architecture="amd64",
            python_interpreters=(PythonInterpreter(Path("C:/Python312/python.exe"), (3, 12, 0)),),
            nvidia=True,
            nvidia_driver_version=(616, 92, 0),
        ),
    )

    result = main(
        ["install", "--provider", "paddle-ocr", "--profile", "nvidia", "--dry-run"]
    )

    assert result == 2
    assert "PADDLE_NVIDIA_REQUIRES_LINUX_RUNTIME" in capsys.readouterr().out


def test_program_name_follows_invoked_alias(monkeypatch):
    from edi_reference import cli

    monkeypatch.setattr("sys.argv", ["C:/venv/Scripts/tlkdoc.exe"])
    assert cli._parser().prog == "tlkdoc"
    monkeypatch.setattr("sys.argv", ["/usr/local/bin/edi"])
    assert cli._parser().prog == "edi"
    monkeypatch.setattr("sys.argv", ["-m"])
    assert cli._parser().prog == "tlkdoc"
