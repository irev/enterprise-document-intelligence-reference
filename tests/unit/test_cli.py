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


def test_app_command_creates_application_and_one_time_key(tmp_path, capsys):
    from edi_reference import cli

    state = str(tmp_path)
    assert cli.main(["app", "add", "app-demo", "--tenant", "tenant-demo", "--state-dir", state]) == 0
    assert cli.main(["app", "key", "app-demo", "--state-dir", state]) == 0
    out = capsys.readouterr().out
    token = next(line.split()[1] for line in out.splitlines() if line.startswith("token:"))
    assert token.startswith("tlk_k")
    assert cli.main(["app", "list", "--state-dir", state]) == 0
    listing = capsys.readouterr().out
    assert "app-demo\ttenant=tenant-demo\tactive" in listing and token.split(".")[1] not in listing
    assert cli.main(["app", "add", "app-demo", "--tenant", "tenant-demo", "--state-dir", state]) == 2


def test_app_profiles_command(tmp_path, capsys):
    from edi_reference import cli
    from edi_reference.adapters.sqlite_api_store import SqliteApiStore

    state = str(tmp_path)
    assert cli.main(["app", "add", "app-demo", "--tenant", "tenant-demo", "--state-dir", state]) == 0
    assert cli.main(["app", "profiles", "app-demo", "--allowed", "default,careful", "--default", "careful",
                     "--state-dir", state]) == 0
    assert cli.main(["app", "profiles", "app-demo", "--allowed", "default", "--default", "careful",
                     "--state-dir", state]) == 2
    store = SqliteApiStore(tmp_path / "api.sqlite3")
    app = store.application("app-demo")
    store.close()
    assert app["allowed_profiles"] == ["careful", "default"] and app["default_profile"] == "careful"


def test_storage_command_registers_connection_and_one_time_secret(tmp_path, capsys):
    from edi_reference import cli

    state = str(tmp_path)
    base = ["storage", "add", "store-demo", "--tenant", "tenant-demo", "--broker-url", "https://broker.example.test/grants",
            "--origin", "https://objects.example.test", "--state-dir", state]
    assert cli.main(base) == 0
    secret = next(line.split()[2] for line in capsys.readouterr().out.splitlines() if line.startswith("broker secret:"))
    assert (tmp_path / "storage-secrets" / "store-demo.key").read_text(encoding="ascii") == secret
    assert cli.main(base) == 2  # already exists
    assert cli.main(["storage", "disable", "store-demo", "--state-dir", state]) == 0
    assert cli.main(["storage", "list", "--state-dir", state]) == 0
    listing = capsys.readouterr().out
    assert "store-demo\ttenant=tenant-demo\tdisabled" in listing and secret not in listing
    assert "origins=https://objects.example.test:443" in listing
    for bad in (["--broker-url", "http://broker.example.test/g"], ["--origin", "https://objects.example.test/path"]):
        args = ["storage", "add", "store-two", "--tenant", "tenant-demo", "--broker-url", "https://b.example.test/g",
                "--origin", "https://objects.example.test", "--state-dir", state]
        args[args.index(bad[0]) + 1] = bad[1]
        assert cli.main(args) == 2
    assert not (tmp_path / "storage-secrets" / "store-two.key").exists()
