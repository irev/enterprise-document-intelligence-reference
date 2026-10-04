import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from edi_reference.application.paddle_models import (
    build_warm_command,
    resolve_paddle_model,
    verify_paddle_model,
    warm_paddle_model,
)


def test_resolve_v6_medium_to_explicit_upstream_models() -> None:
    model = resolve_paddle_model("pp-ocrv6-medium")

    assert model.upstream_names == ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")


def test_warm_command_uses_argv_and_explicit_model_names(tmp_path: Path) -> None:
    command = build_warm_command(
        python_executable="runtime-python",
        model_id="pp-ocrv6-medium",
        artifact_dir=tmp_path,
    )

    assert command[0] == "runtime-python"
    assert command[1] == "-c"
    assert "PP-OCRv6_medium_det" in command[-1]


def test_warm_records_upstream_cache_without_claiming_local_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(*args, **kwargs):
        payload = json.loads(args[0][-1])
        artifact = Path(payload["artifact_dir"])
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "resolved-model.json").write_text(
            json.dumps({"model_id": payload["model_id"], "names": payload["names"]}),
            encoding="utf-8",
        )
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", run)
    state = warm_paddle_model(
        python_executable="runtime-python",
        model_id="pp-ocrv6-medium",
        artifact_dir=tmp_path,
    )

    assert state.status == "WARMED"
    assert state.storage == "UPSTREAM_CACHE"
    assert verify_paddle_model(tmp_path) == state


def test_verify_detects_manifest_tampering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def run(*args, **kwargs):
        payload = json.loads(args[0][-1])
        artifact = Path(payload["artifact_dir"])
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "resolved-model.json").write_text("{}", encoding="utf-8")
        return Mock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", run)
    warm_paddle_model(
        python_executable="runtime-python",
        model_id="pp-ocrv6-medium",
        artifact_dir=tmp_path,
    )
    (tmp_path / "resolved-model.json").write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="MODEL_ARTIFACT_INTEGRITY_MISMATCH"):
        verify_paddle_model(tmp_path)
