"""Local operator configuration file (.edi/config.json), standard library only.

The config file stores *defaults* for console commands. Explicit command-line
flags always win over stored values, and stored values always win over built-in
defaults. Unknown or invalid entries are dropped with a warning instead of
failing command execution (fail-safe read); execution commands keep validating
their own inputs fail-closed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(".edi/config.json")
SCHEMA_VERSION = 1

MODEL_SOURCES = ("HUGGINGFACE", "BOS")

_STRING_FIELDS = (
    "runtime_root",
    "model_root",
    "log_path",
    "provider_id",
    "profile",
    "model_id",
    "model_source",
)


@dataclass(frozen=True, slots=True)
class LocalConfig:
    schema_version: int = SCHEMA_VERSION
    runtime_root: str | None = None
    model_root: str | None = None
    log_path: str | None = None
    provider_id: str | None = None
    profile: str | None = None
    model_id: str | None = None
    model_source: str | None = None
    web_port: int | None = None
    web_bind: str | None = None


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _field_names() -> tuple[str, ...]:
    return tuple(item.name for item in fields(LocalConfig) if item.name != "schema_version")


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> LocalConfig:
    """Read the config file; missing or invalid files degrade to empty defaults."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return LocalConfig()
    except OSError as exc:
        _warn(f"ignoring unreadable config at {path}: {exc}")
        return LocalConfig()
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        _warn(f"ignoring invalid JSON config at {path}")
        return LocalConfig()
    if not isinstance(raw, dict):
        _warn(f"ignoring non-object config at {path}")
        return LocalConfig()
    version = raw.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        _warn(f"ignoring config with unsupported schema_version {version!r} at {path}")
        return LocalConfig()
    values: dict[str, object] = {}
    for name in _field_names():
        value = raw.get(name)
        if value is None:
            continue
        if name in _STRING_FIELDS and isinstance(value, str) and value:
            values[name] = value
        elif name == "web_port" and isinstance(value, int) and not isinstance(value, bool) and 0 < value < 65536:
            values[name] = value
        elif name == "web_bind" and isinstance(value, str) and value:
            values[name] = value
        else:
            _warn(f"ignoring invalid config value for {name!r} in {path}")
    if values.get("model_source") is not None and values["model_source"] not in MODEL_SOURCES:
        _warn(f"ignoring invalid model_source in {path}")
        values.pop("model_source", None)
    return LocalConfig(**values)  # type: ignore[arg-type]


def save_config(config: LocalConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Persist the config atomically (temporary file + os.replace)."""
    payload = {name: getattr(config, name) for name in _field_names()}
    payload["schema_version"] = SCHEMA_VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def config_to_dict(config: LocalConfig) -> dict[str, object]:
    payload: dict[str, object] = {"schema_version": config.schema_version}
    for name in _field_names():
        value = getattr(config, name)
        if value is not None:
            payload[name] = value
    return payload
