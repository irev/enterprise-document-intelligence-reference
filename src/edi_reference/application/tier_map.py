"""Hardware VRAM tier map loaded from the code-owned tiers.toml resource.

The tier map is *advisory* documentation for operators and console output
(`edi ps`, `edi config`, `edi serve recommend`). It never gates execution:
resolving a tier failing to UNKNOWN preserves UNKNOWN instead of guessing.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

UNKNOWN_TIER = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TierDefinition:
    tier_id: str
    vram_mib_min: int | None
    vram_mib_max: int | None
    profiles: tuple[str, ...]
    models: tuple[str, ...]
    serve: tuple[str, ...]


def load_tier_map(path: Path | None = None) -> dict[str, TierDefinition]:
    if path is None:
        resource = resources.files("edi_reference").joinpath("runtime/tiers.toml")
        with resource.open("rb") as handle:
            raw = tomllib.load(handle)
    else:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

    if raw.get("schema_version") != "1":
        raise ValueError("UNSUPPORTED_TIER_MAP_SCHEMA")
    raw_tiers = raw.get("tier")
    if not isinstance(raw_tiers, dict) or not raw_tiers:
        raise ValueError("TIER_MAP_EMPTY")

    tiers: dict[str, TierDefinition] = {}
    for tier_id, value in raw_tiers.items():
        if not isinstance(value, dict):
            raise ValueError("INVALID_TIER_DEFINITION")
        minimum = value.get("vram_mib_min")
        maximum = value.get("vram_mib_max")
        for bound in (minimum, maximum):
            if bound is not None and (isinstance(bound, bool) or not isinstance(bound, int) or bound < 0):
                raise ValueError("INVALID_TIER_BAND")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("INVALID_TIER_BAND")
        tiers[str(tier_id)] = TierDefinition(
            tier_id=str(tier_id),
            vram_mib_min=minimum,
            vram_mib_max=maximum,
            profiles=tuple(str(item) for item in value.get("profiles", ())),
            models=tuple(str(item) for item in value.get("models", ())),
            serve=tuple(str(item) for item in value.get("serve", ())),
        )

    ordered = sorted(
        tiers.values(),
        key=lambda item: item.vram_mib_min if item.vram_mib_min is not None else -1,
    )
    for left, right in zip(ordered, ordered[1:], strict=False):
        if left.vram_mib_max is None:
            raise ValueError("TIER_BANDS_OVERLAP")
        if right.vram_mib_min is None or left.vram_mib_max >= right.vram_mib_min:
            raise ValueError("TIER_BANDS_OVERLAP")
    return tiers


def resolve_tier(tiers: dict[str, TierDefinition], vram_mib: int | None) -> str:
    """Map a VRAM size to exactly one tier; anything else resolves to UNKNOWN."""
    if vram_mib is None:
        return UNKNOWN_TIER
    matches = [
        tier.tier_id
        for tier in tiers.values()
        if (tier.vram_mib_min is None or vram_mib >= tier.vram_mib_min)
        and (tier.vram_mib_max is None or vram_mib <= tier.vram_mib_max)
    ]
    if len(matches) != 1:
        return UNKNOWN_TIER
    return matches[0]


def tier_definition(tiers: dict[str, TierDefinition], tier_id: str) -> TierDefinition | None:
    return tiers.get(tier_id)
