"""击杀成本计算测试（口径：带内平均期望发数 × 单发均价，四舍五入）。"""

import os

import pytest

from src.engine.ammo_pricing import AmmoPriceTable
from src.engine.game_data import load_game_data
from src.engine.tiering import (
    BAND_NAMES,
    BandResult,
    GunRanking,
    compute_kill_cost,
    rank_weapons_for_scenario,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_basic_cost():
    # 5.543 × 4579 = 25380.797 → int(+0.5) = 25381
    assert compute_kill_cost(5.543, 4579) == 25381


def test_rounds_half_up_not_bankers():
    """内建 round() 会把 2.5 舍成 2；成本必须向上取整到 3。"""
    assert compute_kill_cost(2.5, 1) == 3
    assert compute_kill_cost(3.5, 1) == 4
    assert round(2.5) == 2  # 佐证为何禁用 round()


def test_missing_inputs_yield_none():
    assert compute_kill_cost(None, 100) is None
    assert compute_kill_cost(5.0, None) is None
    assert compute_kill_cost(None, None) is None


def test_band_result_new_fields_have_defaults():
    band = BandResult(band="贴脸", mean_ms=286.92, worst_ms=286.92, best_ms=286.92)
    assert band.mean_expected_shots == 0.0
    assert band.kill_cost is None


def test_gun_ranking_new_fields_have_defaults():
    entry = GunRanking(
        profile_key="p", weapon_id="w", display_name="GUN", base_name="GUN",
        category="突击步枪", is_variant=False, variant_item_name=None,
        loadout={}, tuning={},
    )
    assert entry.ammo_item_id == ""
    assert entry.ammo_name == ""
    assert entry.ammo_caliber == ""
    assert entry.ammo_price_avg_30d is None


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def test_ranking_attaches_ammo_and_cost(gd):
    """VSS 在 5-5 情景可用；给了价格表后每带都应有成本。"""
    table = AmmoPriceTable(prices={"__any__": 1000})
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"], price_table=table,
    )
    entry = rankings[0]
    assert entry.ammo_item_id, "应带出实际使用的弹药主键"
    assert entry.ammo_name
    for band in BAND_NAMES:
        assert band in entry.bands
        assert entry.bands[band].mean_expected_shots > 0
    # 价格表里没有该弹药 → 缺价 → 全 None
    assert all(entry.bands[b].kill_cost is None for b in entry.bands)


def test_cost_uses_band_mean_shots(gd):
    """成本必须等于该带 mean_expected_shots × 单价（四舍五入）。"""
    price = 2000
    table = AmmoPriceTable(prices={"__any__": price})
    rankings, _t, _e = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"], price_table=table,
    )
    entry = rankings[0]
    assert entry.ammo_price_avg_30d is None  # 该弹未配价

    # 用真实 id 再跑一次，确认成本公式
    real_id = entry.ammo_item_id
    table2 = AmmoPriceTable(prices={real_id: price})
    rankings2, _t2, _e2 = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"], price_table=table2,
    )
    entry2 = rankings2[0]
    assert entry2.ammo_price_avg_30d == price
    for band in BAND_NAMES:
        expected = compute_kill_cost(entry2.bands[band].mean_expected_shots, price)
        assert entry2.bands[band].kill_cost == expected


def test_ranking_without_price_table_still_works(gd):
    """不传价格表：TTK 与发数照常，成本为 None（榜单完全可用）。"""
    rankings, _t, _e = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"],
    )
    entry = rankings[0]
    assert entry.bands["贴脸"].mean_ms > 0
    assert entry.bands["贴脸"].mean_expected_shots > 0
    assert entry.bands["贴脸"].kill_cost is None
    assert entry.ammo_price_avg_30d is None
