from pathlib import Path

import pytest

from edi_reference.application.tier_map import (
    UNKNOWN_TIER,
    load_tier_map,
    resolve_tier,
)


def test_default_tier_map_loads_all_bands() -> None:
    tiers = load_tier_map()

    assert set(tiers) == {"cpu", "gpu-low", "gpu-mid", "gpu-high"}
    assert tiers["gpu-mid"].vram_mib_min == 12288
    assert tiers["gpu-mid"].vram_mib_max == 20479
    assert tiers["gpu-high"].vram_mib_max is None
    assert "vllm" in tiers["gpu-high"].serve
    assert "vllm" not in tiers["gpu-mid"].serve


def test_resolve_tier_maps_expected_vram_values() -> None:
    tiers = load_tier_map()

    assert resolve_tier(tiers, None) == UNKNOWN_TIER
    assert resolve_tier(tiers, 4096) == "cpu"
    assert resolve_tier(tiers, 8191) == "cpu"
    assert resolve_tier(tiers, 8192) == "gpu-low"
    assert resolve_tier(tiers, 12288) == "gpu-mid"
    assert resolve_tier(tiers, 20479) == "gpu-mid"
    assert resolve_tier(tiers, 20480) == "gpu-high"
    assert resolve_tier(tiers, 24576) == "gpu-high"
    assert resolve_tier(tiers, 999999) == "gpu-high"


def test_gap_between_bands_resolves_to_unknown(tmp_path: Path) -> None:
    path = tmp_path / "tiers.toml"
    path.write_text(
        'schema_version = "1"\n'
        "[tier.cpu]\n"
        "vram_mib_max = 100\n"
        "[tier.big]\n"
        "vram_mib_min = 200\n",
        encoding="utf-8",
    )

    tiers = load_tier_map(path)

    assert resolve_tier(tiers, 150) == UNKNOWN_TIER
    assert resolve_tier(tiers, 50) == "cpu"
    assert resolve_tier(tiers, 300) == "big"


def test_overlapping_bands_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tiers.toml"
    path.write_text(
        'schema_version = "1"\n'
        "[tier.a]\n"
        "vram_mib_max = 200\n"
        "[tier.b]\n"
        "vram_mib_min = 100\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="TIER_BANDS_OVERLAP"):
        load_tier_map(path)


def test_inverted_band_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tiers.toml"
    path.write_text(
        'schema_version = "1"\n[tier.a]\nvram_mib_min = 500\nvram_mib_max = 100\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="INVALID_TIER_BAND"):
        load_tier_map(path)


def test_unsupported_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "tiers.toml"
    path.write_text('schema_version = "2"\n[tier.a]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="UNSUPPORTED_TIER_MAP_SCHEMA"):
        load_tier_map(path)
