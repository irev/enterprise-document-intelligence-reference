import io
import json
from pathlib import Path

from edi_reference.application.runtime_bootstrap import HostCapabilities, PythonInterpreter
from edi_reference.application.runtime_installer import (
    InstallExecutionResult,
    StepResult,
    runtime_python,
    write_install_state,
)
from edi_reference.cli import HostInfo, main
from edi_reference.domain.document_structure import BoundingBox
from edi_reference.domain.ocr import OcrPage, OcrResult, OcrTextLine


def _patch_linux_host(monkeypatch) -> None:
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
            nvidia=False,
            nvidia_driver_version=None,
        ),
    )


def _write_ready_runtime(runtime_root: Path) -> Path:
    runtime_dir = runtime_root / "paddle-ocr" / "cpu"
    executable = runtime_python(runtime_dir)
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"")
    write_install_state(
        runtime_dir,
        InstallExecutionResult(
            provider_id="paddle-ocr",
            profile="cpu",
            runtime_dir=str(runtime_dir),
            status="READY",
            steps=(StepResult("install", 0),),
            runtime_python=str(executable),
            runtime_python_version="3.12.0",
        ),
    )
    return executable


def _fake_page() -> OcrResult:
    box = BoundingBox(0.0, 0.0, 1.0, 1.0)
    return OcrResult((OcrPage(1, 10.0, 10.0, (OcrTextLine("line one", box),)),))


def _api(capsys, request_text: str) -> tuple[int, dict]:  # type: ignore[no-untyped-def]
    code = main(["api", request_text])
    payload = json.loads(capsys.readouterr().out)
    return code, payload


def _read_json_output(capsys) -> dict:  # type: ignore[no-untyped-def]
    """Parse the JSON document from output that may be preceded by menu text."""
    out = capsys.readouterr().out
    return json.loads(out[out.index("{") :])


# --- edi install: model selection -------------------------------------------------


def test_install_with_model_provisions_after_install(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)
    installs: list[dict] = []
    pulls: list[dict] = []

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        installs.append(kwargs)
        return InstallExecutionResult(
            provider_id=kwargs["provider_id"],
            profile=kwargs["profile"],
            runtime_dir="runtime",
            status="READY",
            steps=(StepResult("install", 0),),
        )

    def fake_pull(**kwargs):  # type: ignore[no-untyped-def]
        pulls.append(kwargs)
        return {"model_id": kwargs["model_id"], "status": "WARMED"}

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )
    monkeypatch.setattr("edi_reference.cli._pull_model", fake_pull)
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: False)

    code = main(
        [
            "install",
            "--provider", "paddle-ocr",
            "--profile", "cpu",
            "--yes",
            "--model", "pp-ocrv6-medium",
            "--runtime-root", str(tmp_path / "rt"),
            "--model-root", str(tmp_path / "m"),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["install"]["status"] == "READY"
    assert payload["model"]["model_id"] == "pp-ocrv6-medium"
    assert len(installs) == 1
    assert pulls[0]["profile"] == "cpu"
    assert pulls[0]["model_id"] == "pp-ocrv6-medium"


def test_install_interactive_selection_provisions_chosen_model(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)
    pulls: list[dict] = []

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        return InstallExecutionResult(
            provider_id=kwargs["provider_id"],
            profile=kwargs["profile"],
            runtime_dir="runtime",
            status="READY",
            steps=(StepResult("install", 0),),
        )

    def fake_pull(**kwargs):  # type: ignore[no-untyped-def]
        pulls.append(kwargs)
        return {"model_id": kwargs["model_id"], "status": "WARMED"}

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )
    monkeypatch.setattr("edi_reference.cli._pull_model", fake_pull)
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: True)
    answers = iter(["1\n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(
        [
            "install",
            "--provider", "paddle-ocr",
            "--profile", "cpu",
            "--yes",
            "--runtime-root", str(tmp_path / "rt"),
            "--model-root", str(tmp_path / "m"),
        ]
    )

    assert code == 0
    payload = _read_json_output(capsys)
    assert payload["model"]["model_id"] == "pp-ocrv6-medium"
    assert len(pulls) == 1


def test_install_interactive_skip_keeps_runtime_only(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)
    pulls: list[dict] = []

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        return InstallExecutionResult(
            provider_id=kwargs["provider_id"],
            profile=kwargs["profile"],
            runtime_dir="runtime",
            status="READY",
            steps=(StepResult("install", 0),),
        )

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )
    monkeypatch.setattr("edi_reference.cli._pull_model", lambda **kwargs: pulls.append(kwargs))
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: True)
    answers = iter(["q\n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(
        [
            "install",
            "--provider", "paddle-ocr",
            "--profile", "cpu",
            "--yes",
            "--runtime-root", str(tmp_path / "rt"),
            "--model-root", str(tmp_path / "m"),
        ]
    )

    assert code == 0
    payload = _read_json_output(capsys)
    assert payload["provider_id"] == "paddle-ocr"
    assert "model" not in payload
    assert pulls == []


def test_install_non_tty_without_model_keeps_runtime_only(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)
    pulls: list[dict] = []

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        return InstallExecutionResult(
            provider_id=kwargs["provider_id"],
            profile=kwargs["profile"],
            runtime_dir="runtime",
            status="READY",
            steps=(StepResult("install", 0),),
        )

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )
    monkeypatch.setattr("edi_reference.cli._pull_model", lambda **kwargs: pulls.append(kwargs))
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: False)

    code = main(
        [
            "install",
            "--provider", "paddle-ocr",
            "--profile", "cpu",
            "--yes",
            "--runtime-root", str(tmp_path / "rt"),
            "--model-root", str(tmp_path / "m"),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["provider_id"] == "paddle-ocr"
    assert pulls == []


def test_install_rejects_unknown_model_before_executing(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)
    installs: list[dict] = []

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        installs.append(kwargs)
        raise AssertionError("must not install")

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: False)

    code = main(
        [
            "install",
            "--provider", "paddle-ocr",
            "--profile", "cpu",
            "--yes",
            "--model", "bogus-model",
            "--runtime-root", str(tmp_path / "rt"),
            "--model-root", str(tmp_path / "m"),
        ]
    )

    assert code == 2
    assert "UNKNOWN_PADDLE_MODEL" in capsys.readouterr().out
    assert installs == []


def test_install_interactive_invalid_selection_fails_closed(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        return InstallExecutionResult(
            provider_id=kwargs["provider_id"],
            profile=kwargs["profile"],
            runtime_dir="runtime",
            status="READY",
            steps=(StepResult("install", 0),),
        )

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )
    monkeypatch.setattr("edi_reference.cli._stdin_is_tty", lambda: True)
    answers = iter(["x\n", "99\n", "x\n", "99\n", "x\n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    code = main(
        [
            "install",
            "--provider", "paddle-ocr",
            "--profile", "cpu",
            "--yes",
            "--runtime-root", str(tmp_path / "rt"),
            "--model-root", str(tmp_path / "m"),
        ]
    )

    assert code == 2
    assert "INVALID_MODEL_SELECTION" in capsys.readouterr().out


# --- edi process -----------------------------------------------------------------


def test_process_fails_closed_without_runtime_state(capsys, tmp_path) -> None:
    document = tmp_path / "doc.txt"
    document.write_bytes(b"hello")

    code = main(
        [
            "process", str(document),
            "--runtime-root", str(tmp_path / "runtimes"),
            "--model-root", str(tmp_path / "models"),
            "--log", str(tmp_path / "log.jsonl"),
        ]
    )

    assert code == 2
    assert "RUNTIME_STATE_NOT_FOUND" in capsys.readouterr().out


def test_process_emits_page_analysis_and_writes_log(monkeypatch, capsys, tmp_path) -> None:
    runtime_root = tmp_path / "runtimes"
    _write_ready_runtime(runtime_root)
    document = tmp_path / "invoice.txt"
    document.write_bytes(b"content")
    log_path = tmp_path / "logs" / "processing.jsonl"
    captured: dict[str, object] = {}

    def fake_ocr(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return _fake_page()

    monkeypatch.setattr("edi_reference.cli._run_document_ocr", fake_ocr)

    code = main(
        [
            "process", str(document),
            "--runtime-root", str(runtime_root),
            "--model-root", str(tmp_path / "models"),
            "--log", str(log_path),
            "--timeout", "42",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "COMPLETED"
    assert payload["total_pages"] == 1
    assert payload["pages"][0] == {
        "page_number": 1,
        "line_count": 1,
        "character_count": len("line one"),
    }
    assert payload["source_name"] == "invoice.txt"
    assert payload["log_path"] == str(log_path)
    assert captured["timeout_seconds"] == 42

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [entry["event"] for entry in events] == [
        "FILE_PROCESSING_STARTED",
        "PAGE_ANALYZED",
        "FILE_PROCESSING_COMPLETED",
    ]
    assert events[0]["source_name"] == "invoice.txt"


def test_process_ocr_failure_is_logged_and_fails_closed(monkeypatch, capsys, tmp_path) -> None:
    runtime_root = tmp_path / "runtimes"
    _write_ready_runtime(runtime_root)
    document = tmp_path / "doc.txt"
    document.write_bytes(b"content")
    log_path = tmp_path / "processing.jsonl"

    def fail_ocr(**kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("LOCAL_OCR_FAILED")

    monkeypatch.setattr("edi_reference.cli._run_document_ocr", fail_ocr)

    code = main(
        [
            "process", str(document),
            "--runtime-root", str(runtime_root),
            "--model-root", str(tmp_path / "models"),
            "--log", str(log_path),
        ]
    )

    assert code == 2
    assert "LOCAL_OCR_FAILED" in capsys.readouterr().out
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event"] == "FILE_PROCESSING_FAILED"
    assert events[-1]["error_code"] == "LOCAL_OCR_FAILED"


def test_process_missing_document_fails_closed(capsys, tmp_path) -> None:
    code = main(
        [
            "process", str(tmp_path / "absent.txt"),
            "--runtime-root", str(tmp_path / "runtimes"),
            "--log", str(tmp_path / "log.jsonl"),
        ]
    )

    assert code == 2
    assert "DOCUMENT_NOT_FOUND" in capsys.readouterr().out


# --- edi api (standard JSON-over-stdio) -------------------------------------------


def test_api_doctor_returns_host_payload(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "edi_reference.cli.inspect_host",
        lambda: HostInfo("linux", "x86_64", False, False),
    )
    monkeypatch.setattr("edi_reference.cli._nvidia_query", lambda field: None)

    code, payload = _api(capsys, json.dumps({"operation": "doctor"}))

    assert code == 0
    assert payload["ok"] is True
    assert payload["operation"] == "doctor"
    assert payload["result"]["os"] == "linux"
    assert payload["result"]["nvidia_gpu"] is None


def test_api_invalid_json_fails_closed(capsys) -> None:
    code, payload = _api(capsys, "{not json")

    assert code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_REQUEST"


def test_api_unknown_operation_fails_closed(capsys) -> None:
    code, payload = _api(capsys, json.dumps({"operation": "nope"}))

    assert code == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "UNKNOWN_OPERATION"


def test_api_models_list(capsys) -> None:
    code, payload = _api(capsys, json.dumps({"operation": "models.list"}))

    assert code == 0
    models = payload["result"]["models"]
    assert {"provider_id": "paddle-ocr", "model_id": "pp-ocrv6-medium"} in models
    assert len(models) >= 5


def test_api_providers_list(capsys) -> None:
    code, payload = _api(capsys, json.dumps({"operation": "providers.list"}))

    assert code == 0
    provider_ids = [entry["provider_id"] for entry in payload["result"]["providers"]]
    assert "paddle-ocr" in provider_ids


def test_api_models_pull_requires_confirmation(capsys) -> None:
    code, payload = _api(
        capsys,
        json.dumps({"operation": "models.pull", "params": {"model_id": "pp-ocrv6-medium"}}),
    )

    assert code == 2
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"


def test_api_install_execute_requires_confirmation(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)
    installs: list[dict] = []

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        installs.append(kwargs)
        raise AssertionError("must not install without confirm")

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )

    code, payload = _api(
        capsys,
        json.dumps(
            {
                "operation": "install.execute",
                "params": {"provider_id": "paddle-ocr", "profile": "cpu"},
            }
        ),
    )

    assert code == 2
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert installs == []


def test_api_install_plan_returns_plan(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)

    code, payload = _api(
        capsys,
        json.dumps(
            {
                "operation": "install.plan",
                "params": {
                    "provider_id": "paddle-ocr",
                    "profile": "cpu",
                    "runtime_root": str(tmp_path / "rt"),
                },
            }
        ),
    )

    assert code == 0
    assert payload["result"]["status"] == "PLANNED"


def test_api_install_execute_with_model(monkeypatch, capsys, tmp_path) -> None:
    _patch_linux_host(monkeypatch)

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        return InstallExecutionResult(
            provider_id=kwargs["provider_id"],
            profile=kwargs["profile"],
            runtime_dir="runtime",
            status="READY",
            steps=(StepResult("install", 0),),
        )

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )
    monkeypatch.setattr(
        "edi_reference.cli._pull_model",
        lambda **kwargs: {"model_id": kwargs["model_id"], "status": "WARMED"},
    )

    code, payload = _api(
        capsys,
        json.dumps(
            {
                "operation": "install.execute",
                "params": {
                    "provider_id": "paddle-ocr",
                    "profile": "cpu",
                    "confirm": True,
                    "model": "pp-ocrv6-medium",
                    "runtime_root": str(tmp_path / "rt"),
                    "model_root": str(tmp_path / "m"),
                },
            }
        ),
    )

    assert code == 0
    assert payload["result"]["install"]["status"] == "READY"
    assert payload["result"]["model"]["model_id"] == "pp-ocrv6-medium"


def test_api_process_file_returns_page_analysis(monkeypatch, capsys, tmp_path) -> None:
    runtime_root = tmp_path / "runtimes"
    _write_ready_runtime(runtime_root)
    document = tmp_path / "doc.txt"
    document.write_bytes(b"content")
    log_path = tmp_path / "api-processing.jsonl"
    monkeypatch.setattr(
        "edi_reference.cli._run_document_ocr",
        lambda **kwargs: _fake_page(),
    )

    code, payload = _api(
        capsys,
        json.dumps(
            {
                "operation": "process.file",
                "params": {
                    "path": str(document),
                    "runtime_root": str(runtime_root),
                    "model_root": str(tmp_path / "models"),
                    "log": str(log_path),
                },
            }
        ),
    )

    assert code == 0
    result = payload["result"]
    assert result["total_pages"] == 1
    assert result["pages"][0]["page_number"] == 1
    assert result["log_path"] == str(log_path)
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [entry["event"] for entry in events] == [
        "FILE_PROCESSING_STARTED",
        "PAGE_ANALYZED",
        "FILE_PROCESSING_COMPLETED",
    ]


def test_api_process_file_fails_closed_without_runtime(capsys, tmp_path) -> None:
    document = tmp_path / "doc.txt"
    document.write_bytes(b"content")

    code, payload = _api(
        capsys,
        json.dumps(
            {
                "operation": "process.file",
                "params": {
                    "path": str(document),
                    "runtime_root": str(tmp_path / "runtimes"),
                    "model_root": str(tmp_path / "models"),
                    "log": str(tmp_path / "log.jsonl"),
                },
            }
        ),
    )

    assert code == 2
    assert payload["error"]["code"] == "RUNTIME_STATE_NOT_FOUND"


def test_api_invalid_params_fail_closed(capsys) -> None:
    code, payload = _api(
        capsys,
        json.dumps({"operation": "models.verify", "params": {"model_id": 42}}),
    )

    assert code == 2
    assert payload["error"]["code"] == "INVALID_PARAMS"


def test_api_reads_standard_input(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"operation": "models.list"})))

    code = main(["api"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["ok"] is True
    assert payload["operation"] == "models.list"


# --- progress animation ---------------------------------------------------------


def test_progress_is_silent_when_stderr_is_not_tty(capsys) -> None:  # type: ignore[no-untyped-def]
    from edi_reference.cli import _Progress

    with _Progress("Installing paddle-ocr/cpu runtime"):
        pass

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_progress_animates_and_clears_line_on_tty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sys as sys_module
    import time as time_module

    from edi_reference.cli import _Progress

    class FakeTty:
        def __init__(self) -> None:
            self.data = ""

        def isatty(self) -> bool:
            return True

        def write(self, text: str) -> int:
            self.data += text
            return len(text)

        def flush(self) -> None:
            pass

    fake = FakeTty()
    monkeypatch.setattr(sys_module, "stderr", fake)

    label = "Downloading model pp-ocrv6-medium"
    with _Progress(label):
        time_module.sleep(0.3)

    assert label in fake.data
    assert any(frame in fake.data for frame in _Progress.FRAMES)
    assert fake.data.endswith("\r")
    assert fake.data.count("\r") >= 2
