"""Versioned runtime provider manifest used by management interfaces."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider_id: str
    capabilities: tuple[str, ...]
    runtime_family: str
    required: bool
    profiles: tuple[str, ...]
    models: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    schema_version: str
    providers: dict[str, ProviderDefinition]


def load_provider_manifest(path: Path | None = None) -> ProviderManifest:
    if path is None:
        resource = resources.files("edi_reference").joinpath("runtime/providers.toml")
        with resource.open("rb") as handle:
            raw = tomllib.load(handle)
    else:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

    schema_version = raw.get("schema_version")
    if schema_version != "1":
        raise ValueError("UNSUPPORTED_PROVIDER_MANIFEST_SCHEMA")

    raw_providers = raw.get("providers")
    if not isinstance(raw_providers, dict) or not raw_providers:
        raise ValueError("PROVIDER_MANIFEST_EMPTY")

    providers: dict[str, ProviderDefinition] = {}
    for provider_id, value in raw_providers.items():
        if not isinstance(value, dict):
            raise ValueError("INVALID_PROVIDER_DEFINITION")
        providers[provider_id] = ProviderDefinition(
            provider_id=provider_id,
            capabilities=tuple(value.get("capabilities", ())),
            runtime_family=str(value.get("runtime_family", "")),
            required=bool(value.get("required", False)),
            profiles=tuple(value.get("profiles", ())),
            models=tuple(value.get("models", ())),
        )
    return ProviderManifest(schema_version=schema_version, providers=providers)
