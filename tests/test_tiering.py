"""分层与距离带聚合测试（Task #6）。

口径：起枪状态榜——每行 = 一个起枪配置状态（本体裸枪 / 变体出厂预装态 /
束搜索枚举的改装状态），全部一起排名分层。
"""

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
        beam_width=8,
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
        beam_width=8,
        profile_keys=["18050000003:base", "18020000001:base"],  # VSS 可用 / MP5 被排除
    )
    assert rankings
    assert len(excluded) == 1
    for entry in rankings:
        assert entry.weapon_id == "18050000003"
    base_rows = [e for e in rankings if e.entry_kind == "base"]
    assert len(base_rows) == 1
    entry = base_rows[0]
    for band in BAND_NAMES:
        assert band in entry.bands
        assert entry.bands[band].mean_ms > 0
        assert entry.bands[band].worst_ms >= entry.bands[band].mean_ms - 1e-9
    assert set(thresholds) == set(BAND_NAMES)
    assert entry.bands["贴脸"].tier in {"T0", "T1", "T2", "T3"}


def test_states_deduplicated_and_all_ranked(gd):
    """同一把枪的多状态行：TTK 互异（签名去重），且全部有排名与层级。"""
    rankings, thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=16, profile_keys=["18020000012:base"]  # MK4
    )
    assert len(rankings) >= 2  # 至少裸枪 + 一个改装状态
    kinds = {e.entry_kind for e in rankings}
    assert "base" in kinds
    signatures = [
        tuple(round(e.bands[b].mean_ms, 6) for b in BAND_NAMES) for e in rankings
    ]
    assert len(signatures) == len(set(signatures))  # 四带签名互异
    for entry in rankings:
        for band in BAND_NAMES:
            assert entry.bands[band].rank > 0
            assert entry.bands[band].tier


def test_ttk_by_distance_samples_cover_official_range(gd):
    """每状态携带 0–80m 每 10m 采样 TTK（距离维度明细）。"""
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=16, profile_keys=["18020000012:base"]
    )
    for entry in rankings:
        assert set(entry.ttk_by_distance_ms) == {str(d) for d in range(0, 81, 10)}
        values = list(entry.ttk_by_distance_ms.values())
        assert all(v > 0 for v in values)


def test_to_export_payload_shape(gd):
    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=8, profile_keys=["18050000003:base"]
    )
    payload = to_export(rankings, thresholds, "armor-5-ammo-5-default", excluded)
    assert payload["scenario_id"] == "armor-5-ammo-5-default"
    assert payload["ranking_key"] == "band_mean_ttk_ms"
    assert payload["robustness_key"] == "band_worst_ttk_ms"
    assert payload["eligible_weapon_count"] == len(payload["weapons"])
    assert payload["excluded_weapon_count"] == 0
    assert payload["weapon_pool_count"] == payload["eligible_weapon_count"]
    assert payload["ranked_entry_count"] == len(rankings)
    assert "贴脸" in payload["tier_thresholds_ms"]
    weapon = payload["weapons"][0]
    for key in ("profile_key", "name", "loadout", "overall_mean_ms", "bands",
                "expected_shots_0m", "rpm", "ads_ms_reference", "muzzle_velocity_mps",
                "stock_bands", "loadout_effects", "entry_kind", "ttk_by_distance_ms"):
        assert key in weapon


def test_effective_loadout_drops_defaults():
    """配装只列玩家需要改装的件；与默认件相同的选择不列出。"""
    from src.engine.tiering import _effective_loadout

    weapon = {"default_items": {"2": "stock_barrel", "6": "stock_muzzle"}}
    assert _effective_loadout({"2": "stock_barrel", "6": "silencer"}, weapon) == {"6": "silencer"}
    assert _effective_loadout({"2": "stock_barrel"}, weapon) == {}
    assert _effective_loadout({"2": "long_barrel"}, weapon) == {"2": "long_barrel"}


def test_ttk_relevant_variant_ranks_as_factory_state(gd):
    """预装件影响 TTK 的变体（MK4-击剑手枪管）以出厂态成行，与本体各状态一起参赛。"""
    rankings, thresholds, _excluded = rank_weapons_for_scenario(
        gd,
        "armor-5-ammo-5-default",
        beam_width=16,
        profile_keys=["18020000012:base", "18020000012:13020000563"],
    )
    variant_rows = [r for r in rankings if r.entry_kind == "variant"]
    assert any(r.display_name == "MK4-击剑手枪管" for r in variant_rows)
    variant = next(r for r in variant_rows if r.display_name == "MK4-击剑手枪管")
    assert variant.loadout == {}  # 出厂态：无玩家改装
    assert variant.bands["贴脸"].mean_ms > 0
    assert variant.bands["贴脸"].rank > 0  # 参与排名
    assert variant.bands["贴脸"].tier  # 参与分层
    assert thresholds["贴脸"]


def test_battle_axe_variant_ranks_as_factory_state(gd):
    """ASh-12-战斧重型枪管（预装件改射速 500→400 + 伤害档案）以出厂态成行。"""
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd,
        "armor-5-ammo-5-default",
        beam_width=16,
        profile_keys=["18010000012:base", "18010000012:13020000569"],
    )
    variant_rows = [r for r in rankings if r.entry_kind == "variant"]
    assert any(r.display_name == "ASh-12-战斧重型枪管" for r in variant_rows)
    variant = next(r for r in variant_rows if r.display_name == "ASh-12-战斧重型枪管")
    assert variant.is_variant and variant.loadout == {}
    assert variant.rpm == pytest.approx(400.0)  # 出厂预装态：射速 500→400
    assert variant.bands["贴脸"].tier


def test_real_qjb201_states_have_no_internal_parts(gd):
    """真实数据校验：QJB201 的改装状态行不应装配原厂内部件。"""
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=16, profile_keys=["18040000004:base"]
    )
    weapon = gd.get_weapon("18040000004:base")
    defaults = {str(v) for v in (weapon.get("default_items") or {}).values()}
    for entry in rankings:
        for item_id in entry.loadout.values():
            assert item_id not in defaults, f"配装里出现了默认件 {item_id}"
