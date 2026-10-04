from pathlib import Path
from unittest.mock import Mock

import pytest

from edi_reference.application.paddle_install import InstallStep
from edi_reference.application.runtime_installer import execute_steps, runtime_python


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

    with pytest.raises(RuntimeError, match="INSTALL_STEP_FAILED:install"):
        execute_steps((InstallStep("install", ("python", "-m", "pip")),))
