from pathlib import Path
from unittest.mock import Mock

import pytest

from edi_reference.application.paddle_install import InstallStep
from edi_reference.application.runtime_installer import (\n    InstallStepFailed,\n    ensure_runtime_venv,\n    execute_steps,\n    runtime_python,\n)


def test_runtime_python_is_inside_runtime_directory(tmp_path: Path) -> None:
    python = runtime_python(tmp_path / "paddle-ocr" / "cpu")

    assert str(python).startswith(str(tmp_path))
    assert "venv" in python.parts


def test_execute_steps_uses_argv_without_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=Mock(returncode=0, stdout="ok", stderr=""))
    monkeypatch.setattr("subprocess.run", run)

    result = execute_steps((InstallStep("verify", ("python", "-V")),), timeout_seconds=10)

    assert result[0].returncode == 0
    assert run.call_args.kwargs["shell"] is False
    assert run.call_args.args[0] == ["python", "-V"]


def test_execute_steps_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    run = Mock(return_value=Mock(returncode=1, stdout="", stderr="failure"))
    monkeypatch.setattr("subprocess.run", run)

    with pytest.raises(InstallStepFailed, match="INSTALL_STEP_FAILED:install") as failure:
        execute_steps((InstallStep("install", ("python", "-m", "pip")),))

    assert failure.value.results[0].name == "install"
    assert failure.value.results[0].returncode == 1
    assert not hasattr(failure.value.results[0], "stderr")



def test_runtime_venv_uses_selected_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "python312"
    base.write_text("", encoding="utf-8")
    runtime_dir = tmp_path / "runtime"
    expected = runtime_python(runtime_dir)

    def run(argv, **kwargs):
        assert argv == [str(base), "-m", "venv", str(runtime_dir / "venv")]
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_text("", encoding="utf-8")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", run)

    assert ensure_runtime_venv(runtime_dir, base_python=base) == expected


def test_runtime_venv_rejects_missing_selected_interpreter(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="RUNTIME_PYTHON_NOT_AVAILABLE"):
        ensure_runtime_venv(
            tmp_path / "runtime",
            base_python=tmp_path / "missing-python",
        )
