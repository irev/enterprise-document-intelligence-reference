import json
from pathlib import Path

from edi_reference.application import servers
from edi_reference.application.local_config import save_config, LocalConfig
from edi_reference.cli import HostInfo, main, run_api_request


def _patch_detect(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.servers.detect_server",
        lambda server_id, **_: servers.ServerDetection(
            server_id, "NOT_INSTALLED", None, None
        ),
    )


def _patch_gpu(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.cli._nvidia_query",
        lambda field: "NVIDIA GeForce RTX 3060, 12288 MiB"
        if field == "memory.total"
        else None,
    )


def _write_config(tmp_path: Path, **values: object) -> Path:
    path = tmp_path / ".edi" / "config.json"
    save_config(LocalConfig(**values), path)  # type: ignore[arg-type]
    return path


# --- edi config ----------------------------------------------------------------


def test_config_json_defaults(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _patch_detect(monkeypatch)
    _patch_gpu(monkeypatch)

    code = main(["config", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["config_exists"] is False
    assert payload["effective"]["runtime_root"] == str(Path(".edi/runtimes"))
    assert payload["effective"]["model_source"] == "HUGGINGFACE"
    assert payload["effective"]["web_port"] == 4099
    assert payload["tier"] == "gpu-mid"
    assert payload["host"]["os"]
    assert len(payload["runtime_status"]) > 0
    assert [row["server_id"] for row in payload["servers"]] == ["ollama", "lmstudio", "vllm"]


def test_config_text_output(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _patch_detect(monkeypatch)
    _patch_gpu(monkeypatch)

    code = main(["config"])
    out = capsys.readouterr().out

    assert code == 0
    assert "config: " in out
    assert "(missing)" in out
    assert f"runtime_root: {Path('.edi/runtimes')}" in out
    assert "tier: gpu-mid" in out
    assert "paddle-ocr/cpu:" in out
    assert "server ollama: NOT_INSTALLED" in out


def test_config_reads_stored_values(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _patch_detect(monkeypatch)
    _patch_gpu(monkeypatch)
    _write_config(
        tmp_path,
        profile="nvidia",
        provider_id="paddle-ocr",
        web_port=8123,
        web_bind="0.0.0.0",
    )

    code = main(["config", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["config_exists"] is True
    assert payload["effective"]["profile"] == "nvidia"
    assert payload["effective"]["web_port"] == 8123
    assert payload["effective"]["web_bind"] == "0.0.0.0"


def test_config_wizard_requires_tty(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: False)

    code = main(["config", "--wizard"])

    assert code == 2
    assert "WIZARD_REQUIRES_TTY" in capsys.readouterr().out


def _scripted_input(script: list[str]):  # type: ignore[no-untyped-def]
    answers = iter(script)

    def read(prompt: str) -> str:  # type: ignore[no-untyped-def]
        try:
            return next(answers)
        except StopIteration as exc:  # pragma: no cover
            raise AssertionError(f"unexpected prompt: {prompt}") from exc

    return read


def test_config_wizard_writes_file(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        _scripted_input(
            [
                "",  # runtime root (keep)
                "",  # model root (keep)
                "",  # log path (keep)
                "1",  # provider -> paddle-ocr
                "1",  # profile -> cpu
                "1",  # model -> pp-ocrv6-medium
                "1",  # source -> HUGGINGFACE
                "",  # web port (keep 4099)
                "",  # web bind (keep 127.0.0.1)
                "y",  # confirm
            ]
        ),
    )

    code = main(["config", "--wizard"])
    out = capsys.readouterr().out

    assert code == 0
    assert "SAVED" in out
    raw = json.loads(
        (tmp_path / ".edi" / "config.json").read_text(encoding="utf-8")
    )
    assert raw["provider_id"] == "paddle-ocr"
    assert raw["profile"] == "cpu"
    assert raw["model_id"] == "pp-ocrv6-medium"
    assert raw["model_source"] == "HUGGINGFACE"
    assert raw["web_port"] == 4099
    assert raw["runtime_root"] == ".edi/runtimes"


def test_config_wizard_declined_save_cancels(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: True)
    monkeypatch.setattr(
        "builtins.input",
        _scripted_input(["", "", "", "1", "1", "1", "1", "", "", "n"]),
    )

    code = main(["config", "--wizard"])

    assert code == 2
    assert "WIZARD_CANCELLED" in capsys.readouterr().out
    assert not (tmp_path / ".edi" / "config.json").exists()


# --- edi log -------------------------------------------------------------------


def test_log_missing_file_fails_closed(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    code = main(["log"])

    assert code == 2
    assert "LOG_NOT_FOUND" in capsys.readouterr().out


def test_log_tail_defaults_and_pretty(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    log_path = tmp_path / ".edi" / "logs" / "processing.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text(
        '{"seq": 1}\n{"seq": 2}\nnot-json\n', encoding="utf-8"
    )

    assert main(["log"]) == 0
    out = capsys.readouterr().out
    assert '"seq": 1' in out
    assert "not-json" in out

    assert main(["log", "--tail", "1", "--pretty"]) == 0
    out = capsys.readouterr().out
    assert "seq" not in out or '"seq": 1' not in out
    assert "not-json" in out


def test_log_tail_one_prints_last_line(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    log_path = tmp_path / "log.jsonl"
    log_path.write_text('{"seq": 1}\n{"seq": 2}\n', encoding="utf-8")

    code = main(["log", "--path", str(log_path), "--tail", "1"])
    out = capsys.readouterr().out

    assert code == 0
    assert '"seq": 1' not in out
    assert '"seq": 2' in out


def test_log_negative_tail_is_invalid(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    code = main(["log", "--tail", "-1"])

    assert code == 2
    assert "INVALID_PARAMS" in capsys.readouterr().out


def test_log_uses_configured_path(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, log_path="/tmp/custom-edi-log.jsonl")

    code = main(["log", "--tail", "0"])
    assert code == 2
    assert "LOG_NOT_FOUND" in capsys.readouterr().out
    assert "custom-edi-log" not in capsys.readouterr().out  # no extra output


def test_log_follow_stops_on_interrupt(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    log_path = tmp_path / "log.jsonl"
    log_path.write_text('{"seq": 1}\n', encoding="utf-8")

    class _FakeTime:
        @staticmethod
        def sleep(seconds: float) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr("edi_reference.cli.time", _FakeTime)

    code = main(["log", "--path", str(log_path), "--tail", "1", "--follow"])

    assert code == 0
    assert '"seq": 1' in capsys.readouterr().out


# --- edi ps / status.summary ---------------------------------------------------


def test_ps_json_summary(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _patch_detect(monkeypatch)
    _patch_gpu(monkeypatch)

    code = main(["ps", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["tier"] == "gpu-mid"
    assert payload["vram_mib"] == 12288
    assert any(
        row["provider_id"] == "paddle-ocr" and row["profile"] == "cpu"
        for row in payload["providers"]
    )
    assert any(
        row["model_id"] == "pp-ocrv6-medium" and row["status"] == "NOT_PROVISIONED"
        for row in payload["models"]
    )
    assert [row["server_id"] for row in payload["servers"]] == ["ollama", "lmstudio", "vllm"]


def test_ps_text_output(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _patch_detect(monkeypatch)
    _patch_gpu(monkeypatch)

    code = main(["ps"])
    out = capsys.readouterr().out

    assert code == 0
    assert "tier: gpu-mid" in out
    assert "providers:" in out
    assert "paddle-ocr/cpu: NOT_INSTALLED" in out
    assert "models:" in out
    assert "servers:" in out
    assert "ollama: NOT_INSTALLED" in out


def test_api_status_summary(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_detect(monkeypatch)
    _patch_gpu(monkeypatch)

    payload, status = run_api_request(json.dumps({"operation": "status.summary"}))

    assert status == 0
    result = payload["result"]
    assert result["tier"] == "gpu-mid"  # type: ignore[index]
    assert len(result["providers"]) > 0  # type: ignore[index]
    assert len(result["servers"]) == 3  # type: ignore[index]


# --- alias / config precedence / web bind --------------------------------------


def test_model_alias_behaves_like_models(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    code = main(["model", "list"])
    out = capsys.readouterr().out

    assert code == 0
    assert "paddle-ocr: pp-ocrv6-medium" in out


def test_pull_without_model_id_requires_config_or_argument(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    code = main(["models", "pull", "--yes"])

    assert code == 2
    assert "MODEL_ID_REQUIRED" in capsys.readouterr().out


def test_config_model_id_feeds_pull(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, model_id="pp-structure-v3")
    pulls: list[dict] = []
    monkeypatch.setattr("edi_reference.cli._pull_model", lambda **kwargs: pulls.append(kwargs) or {"status": "WARMED"})

    code = main(["models", "pull", "--yes"])

    assert code == 0
    assert pulls and pulls[0]["model_id"] == "pp-structure-v3"


def test_install_requires_provider(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    code = main(["install", "--dry-run"])

    assert code == 2
    assert "PROVIDER_REQUIRED" in capsys.readouterr().out


def test_config_feeds_install_provider_and_profile(
    monkeypatch, tmp_path, capsys
) -> None:  # type: ignore[no-untyped-def]
    from edi_reference.application.runtime_bootstrap import HostCapabilities, PythonInterpreter

    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, provider_id="paddle-ocr", profile="cpu")
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

    code = main(["install", "--dry-run"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["provider"] == "paddle-ocr"
    assert payload["profile"] == "cpu"


def test_web_bind_flag_overrides(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    class _FakeServer:
        server_address = ("0.0.0.0", 4099)

        def serve_forever(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    def fake_build(host: str, port: int, *, api, runtime_root: str):  # type: ignore[no-untyped-def]
        captured.update(host=host, port=port)
        return _FakeServer()

    monkeypatch.setattr("edi_reference.cli.build_server", fake_build)

    code = main(["web", "--bind", "0.0.0.0"])

    assert code == 0
    assert captured["host"] == "0.0.0.0"


def test_web_uses_config_bind_and_port(monkeypatch, tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, web_bind="0.0.0.0", web_port=9001)
    captured: dict[str, object] = {}

    class _FakeServer:
        server_address = ("0.0.0.0", 9001)

        def serve_forever(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    def fake_build(host: str, port: int, *, api, runtime_root: str):  # type: ignore[no-untyped-def]
        captured.update(host=host, port=port)
        return _FakeServer()

    monkeypatch.setattr("edi_reference.cli.build_server", fake_build)

    code = main(["web"])

    assert code == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9001
