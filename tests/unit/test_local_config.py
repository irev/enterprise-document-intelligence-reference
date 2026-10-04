import json
from pathlib import Path

from edi_reference.application.local_config import (
    LocalConfig,
    config_to_dict,
    load_config,
    save_config,
)


def test_load_missing_config_returns_empty_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "config.json")

    assert config == LocalConfig()
    assert config.schema_version == 1


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / ".edi" / "config.json"
    config = LocalConfig(
        runtime_root="/srv/edi/runtimes",
        model_root="/srv/edi/models",
        log_path="/srv/edi/log.jsonl",
        provider_id="paddle-ocr",
        profile="nvidia",
        model_id="pp-ocrv6-medium",
        model_source="BOS",
        web_port=8123,
        web_bind="0.0.0.0",
    )

    save_config(config, path)
    loaded = load_config(path)

    assert loaded == config
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert list(tmp_path.iterdir()) == [tmp_path / ".edi"]
    leftovers = [item for item in path.parent.iterdir() if item.name.startswith(".config-")]
    assert leftovers == []


def test_invalid_json_degrades_to_empty_with_warning(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")

    config = load_config(path)

    assert config == LocalConfig()
    assert "ignoring invalid JSON config" in capsys.readouterr().err


def test_unsupported_schema_version_is_ignored(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 99, "profile": "cpu"}), encoding="utf-8")

    config = load_config(path)

    assert config == LocalConfig()
    assert "unsupported schema_version" in capsys.readouterr().err


def test_invalid_values_are_dropped_with_warning(
    tmp_path: Path, capsys
) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "cpu",
                "web_port": 70000,
                "runtime_root": 42,
                "model_source": "CDN",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.profile == "cpu"
    assert config.web_port is None
    assert config.runtime_root is None
    assert config.model_source is None
    err = capsys.readouterr().err
    assert "web_port" in err
    assert "runtime_root" in err
    assert "model_source" in err


def test_config_to_dict_omits_unset_values() -> None:
    payload = config_to_dict(LocalConfig(profile="cpu"))

    assert payload == {"schema_version": 1, "profile": "cpu"}
