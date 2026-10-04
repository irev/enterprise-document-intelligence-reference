import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from edi_reference.application.paddle_infer import build_predict_command, run_local_ocr


def _warm_model_state(model_root: Path) -> None:
    artifact = model_root / "paddle-ocr" / "pp-ocrv6-medium"
    artifact.mkdir(parents=True)
    manifest = json.dumps(
        {"model_id": "pp-ocrv6-medium", "kind": "ocr", "names": ["a_det", "a_rec"]}
    )
    (artifact / "resolved-model.json").write_text(manifest, encoding="utf-8")
    digest = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    state = {
        "provider_id": "paddle-ocr",
        "model_id": "pp-ocrv6-medium",
        "source": "HUGGINGFACE",
        "artifact_dir": str(artifact),
        "storage": "UPSTREAM_CACHE",
        "status": "WARMED",
        "manifest_sha256": digest,
    }
    (artifact / "model-state.json").write_text(json.dumps(state), encoding="utf-8")


def test_build_predict_command_uses_trusted_argv(tmp_path) -> None:
    command = build_predict_command(
        python_executable="/runtimes/python",
        model_id="pp-ocrv6-medium",
        document_path=tmp_path / "doc",
        output_path=tmp_path / "out.json",
    )

    assert command[0] == "/runtimes/python"
    assert command[1] == "-c"
    payload = json.loads(command[3])
    assert payload["names"] == ["PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"]
    assert payload["document"].endswith("doc")
    assert payload["output"].endswith("out.json")


def test_build_predict_command_rejects_unknown_model(tmp_path) -> None:
    with pytest.raises(ValueError, match="UNKNOWN_PADDLE_MODEL"):
        build_predict_command(
            python_executable="py",
            model_id="no-such-model",
            document_path=tmp_path / "doc",
            output_path=tmp_path / "out.json",
        )


def test_build_predict_command_rejects_document_parser_model(tmp_path) -> None:
    with pytest.raises(ValueError, match="MODEL_NOT_SUPPORTED_BY_OCR_PIPELINE"):
        build_predict_command(
            python_executable="py",
            model_id="pp-structure-v3",
            document_path=tmp_path / "doc",
            output_path=tmp_path / "out.json",
        )


def test_run_local_ocr_converts_runtime_output_to_pages(monkeypatch, tmp_path) -> None:
    _warm_model_state(tmp_path / "models")

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        payload = json.loads(argv[3])
        Path(payload["output"]).write_text(
            json.dumps(
                [
                    {
                        "rec_texts": ["hello", "world"],
                        "rec_boxes": [[0, 0, 50, 20], [0, 30, 60, 50]],
                        "input_img_shape": [100, 60],
                    }
                ]
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = run_local_ocr(
        python_executable="runtime-python",
        model_id="pp-ocrv6-medium",
        model_root=tmp_path / "models",
        document_bytes=b"%PDF-1.4 synthetic",
    )

    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert [line.text for line in result.pages[0].lines] == ["hello", "world"]


def test_run_local_ocr_fails_on_nonzero_exit(monkeypatch, tmp_path) -> None:
    _warm_model_state(tmp_path / "models")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )

    with pytest.raises(RuntimeError, match="LOCAL_OCR_FAILED"):
        run_local_ocr(
            python_executable="runtime-python",
            model_id="pp-ocrv6-medium",
            model_root=tmp_path / "models",
            document_bytes=b"x",
        )


def test_run_local_ocr_fails_on_timeout(monkeypatch, tmp_path) -> None:
    _warm_model_state(tmp_path / "models")

    def timeout_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="py", timeout=1)

    monkeypatch.setattr("subprocess.run", timeout_run)

    with pytest.raises(RuntimeError, match="LOCAL_OCR_TIMEOUT"):
        run_local_ocr(
            python_executable="runtime-python",
            model_id="pp-ocrv6-medium",
            model_root=tmp_path / "models",
            document_bytes=b"x",
            timeout_seconds=1,
        )


def test_run_local_ocr_requires_usable_model_state(tmp_path) -> None:
    with pytest.raises(ValueError, match="MODEL_STATE_NOT_FOUND"):
        run_local_ocr(
            python_executable="runtime-python",
            model_id="pp-ocrv6-medium",
            model_root=tmp_path / "missing",
            document_bytes=b"x",
        )


def test_run_local_ocr_rejects_nonpositive_timeout(tmp_path) -> None:
    with pytest.raises(ValueError, match="INVALID_OCR_TIMEOUT"):
        run_local_ocr(
            python_executable="runtime-python",
            model_id="pp-ocrv6-medium",
            model_root=tmp_path,
            document_bytes=b"x",
            timeout_seconds=0,
        )
