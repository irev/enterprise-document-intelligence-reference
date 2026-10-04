"""Trusted PaddleOCR model catalog and local artifact lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PaddleModelDefinition:
    model_id: str
    kind: str
    upstream_names: tuple[str, ...]


_MODELS = {
    "pp-ocrv6-medium": PaddleModelDefinition(
        "pp-ocrv6-medium",
        "ocr",
        ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"),
    ),
    "pp-ocrv5-server": PaddleModelDefinition(
        "pp-ocrv5-server",
        "ocr",
        ("PP-OCRv5_server_det", "PP-OCRv5_server_rec"),
    ),
    "pp-structure-v3": PaddleModelDefinition(
        "pp-structure-v3",
        "document-parser",
        ("PP-StructureV3",),
    ),
}


@dataclass(frozen=True, slots=True)
class ModelArtifactState:
    provider_id: str
    model_id: str
    source: str
    artifact_dir: str
    storage: str
    status: str
    manifest_sha256: str


def resolve_paddle_model(model_id: str) -> PaddleModelDefinition:
    try:
        return _MODELS[model_id]
    except KeyError as exc:
        raise ValueError("UNKNOWN_PADDLE_MODEL") from exc


def build_warm_command(
    *,
    python_executable: str,
    model_id: str,
    artifact_dir: Path,
) -> tuple[str, ...]:
    model = resolve_paddle_model(model_id)
    payload = json.dumps(
        {
            "model_id": model.model_id,
            "kind": model.kind,
            "names": model.upstream_names,
            "artifact_dir": str(artifact_dir),
        }
    )
    script = (
        "import json,sys; "
        "from pathlib import Path; "
        "p=json.loads(sys.argv[1]); root=Path(p['artifact_dir']); root.mkdir(parents=True,exist_ok=True); "
        "from paddleocr import PaddleOCR, PPStructureV3; "
        "obj=(PaddleOCR(text_detection_model_name=p['names'][0], text_recognition_model_name=p['names'][1]) "
        "if p['kind']=='ocr' else PPStructureV3()); "
        "(root/'resolved-model.json').write_text(json.dumps({'model_id':p['model_id'],'kind':p['kind'],'names':p['names']}),encoding='utf-8')"
    )
    return (python_executable, "-c", script, payload)


def warm_paddle_model(
    *,
    python_executable: str,
    model_id: str,
    artifact_dir: Path,
    source: str = "HUGGINGFACE",
    timeout_seconds: int = 1800,
) -> ModelArtifactState:
    if source not in {"HUGGINGFACE", "BOS"}:
        raise ValueError("UNSUPPORTED_PADDLE_MODEL_SOURCE")
    command = build_warm_command(
        python_executable=python_executable,
        model_id=model_id,
        artifact_dir=artifact_dir,
    )
    env = os.environ.copy()
    if source == "BOS":
        env["PADDLE_PDX_MODEL_SOURCE"] = "BOS"
    else:
        env.pop("PADDLE_PDX_MODEL_SOURCE", None)
    completed = subprocess.run(
        list(command),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
        shell=False,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError("MODEL_WARM_FAILED")

    manifest_path = artifact_dir / "resolved-model.json"
    if not manifest_path.is_file():
        raise RuntimeError("MODEL_WARM_MANIFEST_MISSING")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    state = ModelArtifactState(
        provider_id="paddle-ocr",
        model_id=model_id,
        source=source,
        artifact_dir=str(artifact_dir),
        storage="UPSTREAM_CACHE",
        status="WARMED",
        manifest_sha256=digest,
    )
    _write_state(artifact_dir, state)
    return state


def verify_paddle_model(artifact_dir: Path) -> ModelArtifactState:
    state_path = artifact_dir / "model-state.json"
    if not state_path.is_file():
        raise ValueError("MODEL_STATE_NOT_FOUND")
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    state = ModelArtifactState(**{key: raw[key] for key in ModelArtifactState.__dataclass_fields__})
    manifest_path = artifact_dir / "resolved-model.json"
    if not manifest_path.is_file():
        raise ValueError("MODEL_ARTIFACT_MANIFEST_NOT_FOUND")
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    if digest != state.manifest_sha256:
        raise ValueError("MODEL_ARTIFACT_INTEGRITY_MISMATCH")
    return state


def _write_state(artifact_dir: Path, state: ModelArtifactState) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(state), "recorded_at": datetime.now(UTC).isoformat()}
    fd, temporary = tempfile.mkstemp(prefix=".model-state-", suffix=".json", dir=artifact_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, artifact_dir / "model-state.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
