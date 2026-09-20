"""分层与距离带聚合测试（Task #6）。"""

import os

import pytest

from src.engine import engagement as eg
from src.engine.game_data import load_game_data
from src.engine.tiering import (
    BAND_NAMES,
    TIER_QUANTILES,
    BandResult,
    GunRanking,
    _quantile,
    assign_tiers,
    rank_weapons_for_scenario,
    to_export,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def _entry(name: str, ms: float) -> GunRanking:
    return GunRanking(
        profile_key=f"{name}:base",
        weapon_id=name,
        display_name=name,
        base_name=name,
        category="突击步枪",
        is_variant=False,
        variant_item_name=None,
        loadout={},
        tuning={},
        bands={"贴脸": BandResult(band="贴脸", mean_ms=ms, worst_ms=ms, best_ms=ms)},
    )


def test_quantile_matches_linear_interpolation():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _quantile(values, 0.0) == 1.0
    assert _quantile(values, 1.0) == 5.0
    assert _quantile(values, 0.5) == 3.0
    assert _quantile(values, 0.25) == pytest.approx(2.0)
    assert _quantile(values, 0.15) == pytest.approx(1.6)


def test_quantile_handles_single_value():
    assert _quantile([7.5], 0.9) == 7.5
    assert _quantile([], 0.5) == 0.0


def test_assign_tiers_uses_quantiles_and_covers_all():
    entries = [_entry(f"g{i}", float(i * 10)) for i in range(1, 11)]  # 10..100
    thresholds = assign_tiers(entries, "贴脸")
    assert set(thresholds) == {"T0", "T1", "T2"}
    # 单调：T0 阈值 < T1 阈值 < T2 阈值
    assert thresholds["T0"] < thresholds["T1"] < thresholds["T2"]
    # 每把枪都必须拿到层级，且最慢的落在 T3
    tiers = [e.bands["贴脸"].tier for e in entries]
    assert all(tiers)
    assert tiers[-1] == "T3"
    assert "T0" in tiers


def test_tier_quantiles_are_declared():
    assert TIER_QUANTILES == (0.15, 0.40, 0.70)


def test_band_definitions_match_engine():
    from src.engine.tiering import BAND_NAMES as names

    assert list(names) == ["贴脸", "近距", "中距", "远距"]
    assert eg.DISTANCE_BANDS["远距"] == (50.0, 80.0)


def test_unsupported_caliber_is_excluded(gd):
    """9x19mm 无 5 级弹 → MP5 在 5-5 情景应被排除（与官方 excluded 口径一致）。"""
    rankings, _thresholds, excluded = rank_weapons_for_scenario(
        gd,
        "armor-5-ammo-5-default",
        beam_width=2,
        top_k=1,
        profile_keys=["18020000001:base"],  # MP5
    )
    assert rankings == []
    assert len(excluded) == 1
    assert excluded[0]["profile_key"] == "18020000001:base"
    assert "5" in excluded[0]["reason"]


def test_ranking_produces_bands_and_thresholds(gd):
    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd,
        "armor-5-ammo-5-default",
        beam_width=2,
        top_k=1,
        profile_keys=["18050000003:base", "18020000001:base"],  # VSS 可用 / MP5 被排除
    )
    assert len(rankings) == 1
    assert len(excluded) == 1
    entry = rankings[0]
    for band in BAND_NAMES:
        assert band in entry.bands
        assert entry.bands[band].mean_ms > 0
        assert entry.bands[band].worst_ms >= entry.bands[band].mean_ms - 1e-9
    assert set(thresholds) == set(BAND_NAMES)
    assert entry.bands["贴脸"].rank == 1
    assert entry.bands["贴脸"].tier in {"T0", "T1", "T2", "T3"}


def test_to_export_payload_shape(gd):
    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1, profile_keys=["18050000003:base"]
    )
    payload = to_export(rankings, thresholds, "armor-5-ammo-5-default", excluded)
    assert payload["scenario_id"] == "armor-5-ammo-5-default"
    assert payload["ranking_key"] == "band_mean_ttk_ms"
    assert payload["robustness_key"] == "band_worst_ttk_ms"
    assert payload["eligible_weapon_count"] == 1
    assert payload["excluded_weapon_count"] == 0
    assert payload["weapon_pool_count"] == 1
    assert payload["ranked_entry_count"] == 1
    assert payload["folded_variant_count"] == 0
    assert "贴脸" in payload["tier_thresholds_ms"]
    weapon = payload["weapons"][0]
    for key in ("profile_key", "name", "loadout", "overall_mean_ms", "bands",
                "expected_shots_0m", "rpm", "ads_ms_reference", "muzzle_velocity_mps",
                "equivalent_variants"):
        assert key in weapon


def test_effective_loadout_drops_defaults():
    """配装只列玩家需要改装的件；与默认件相同的选择不列出。"""
    from src.engine.tiering import _effective_loadout

    weapon = {"default_items": {"2": "stock_barrel", "6": "stock_muzzle"}}
    assert _effective_loadout({"2": "stock_barrel", "6": "silencer"}, weapon) == {"6": "silencer"}
    assert _effective_loadout({"2": "stock_barrel"}, weapon) == {}
    assert _effective_loadout({"2": "long_barrel"}, weapon) == {"2": "long_barrel"}


def test_equivalent_variants_are_folded():
    """与 base 成绩完全一致的变体应折叠，不重复占榜。"""
    from src.engine.tiering import _merge_equivalent_variants

    def entry(name, weapon_id, variant, loadout, ms):
        return GunRanking(
            profile_key=name,
            weapon_id=weapon_id,
            display_name=name,
            base_name=weapon_id,
            category="突击步枪",
            is_variant=variant,
            variant_item_name=name if variant else None,
            loadout=loadout,
            tuning={},
            bands={"贴脸": BandResult(band="贴脸", mean_ms=ms, worst_ms=ms, best_ms=ms)},
        )

    base = entry("GUN", "g1", False, {"2": "barrel"}, 300.0)
    same = entry("GUN-barrel", "g1", True, {"2": "barrel"}, 300.0)
    better = entry("GUN-special", "g1", True, {"2": "other"}, 280.0)
    merged = _merge_equivalent_variants([base, same, better])
    names = {e.display_name for e in merged}
    assert "GUN-barrel" not in names  # 等价变体被折叠
    assert base.equivalent_variants == ["GUN-barrel"]
    assert "GUN-special" in names  # 成绩不同的变体保留


def test_real_qjb201_loadout_has_no_internal_parts(gd):
    """真实数据校验：QJB201 的最优配装不应列出原厂内部件。"""
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=4, top_k=2, profile_keys=["18040000004:base"]
    )
    weapon = gd.get_weapon("18040000004:base")
    defaults = {str(v) for v in (weapon.get("default_items") or {}).values()}
    for item_id in rankings[0].loadout.values():
        assert item_id not in defaults, f"配装里出现了默认件 {item_id}"
