"""击杀成本计算测试（口径：带内平均期望发数 × 单发均价，四舍五入）。"""

import pytest

from src.engine.tiering import BandResult, GunRanking, compute_kill_cost


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
