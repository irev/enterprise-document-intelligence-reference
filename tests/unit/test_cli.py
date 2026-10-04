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


def test_cli_install_requires_dry_run(capsys) -> None:
    result = main(["install", "--provider", "paddle-ocr", "--profile", "cpu"])

    assert result == 2
    assert "INSTALL_EXECUTION_NOT_IMPLEMENTED_USE_DRY_RUN" in capsys.readouterr().out
