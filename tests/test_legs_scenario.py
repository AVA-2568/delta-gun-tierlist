"""修脚情景（legs-only）语义回归。

口径（2026-10-16 榜单新增）：

- 命中分布 = 全腿部（大腿 50% / 小腿 50%）。腿部位在任何护甲等级下都不被覆盖，
  修脚结果**与护甲等级无关**（护甲仅名义存在，不进结算）；
- 弹药候选 = **3/4/5 级有价弹同榜**（穿深不影响腿部伤害，只比肉伤与价格）；
- 候选等级集合由情景的 ``ammo_levels`` 声明（:func:`src.engine.engagement.scenario_ammo_levels`），
  官方情景仍为单等级——行为逐位不变。
"""

import os

import pytest

from src.engine import engagement as eg
from src.engine.ammo_pricing import AmmoPriceTable
from src.engine.game_data import load_game_data
from src.engine.ranking import pick_priced_ammos, rank_weapons_for_scenario
from src.engine.tiering import BAND_NAMES
from src.engine.weapon_state import WeaponStateResolver

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M4A1 = "18010000001:base"
SCENARIO = "legs-only"
M855 = "37100300001"      # 5.56x45mm 3 级
M855A1 = "37100400001"    # 5.56x45mm 4 级
M995 = "37100500001"      # 5.56x45mm 5 级


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def _run(gd, price_table, key=M4A1, beam_width=8):
    return rank_weapons_for_scenario(
        gd, SCENARIO, beam_width=beam_width, profile_keys=[key],
        price_table=price_table,
    )


# --------------------------------------------------------------------------- #
# 情景定义与弹药等级集合
# --------------------------------------------------------------------------- #

def test_legs_scenario_declares_multi_level_ammo(gd):
    scenario = eg.resolve_scenario(gd, SCENARIO)
    assert scenario["probability_preset"] == "legs-only"
    assert eg.scenario_ammo_levels(scenario) == (3, 4, 5)
    probs = scenario["hit_probabilities"]
    assert probs["thigh"] == 0.5 and probs["calf"] == 0.5
    assert sum(probs.values()) == pytest.approx(1.0)
    for part in ("head", "chest", "abdomen", "upperArm", "lowerArm"):
        assert probs[part] == 0.0


def test_official_scenario_levels_unchanged(gd):
    """官方情景仍是单等级集合（「逐位不变」的前提）。"""
    scenario = eg.resolve_scenario(gd, "armor-5-ammo-5-default")
    assert eg.scenario_ammo_levels(scenario) == (5,)


# --------------------------------------------------------------------------- #
# 护甲无关性（腿部不被任何护甲覆盖）
# --------------------------------------------------------------------------- #

def test_legs_ttk_is_armor_independent(gd):
    """同一武器/弹在全腿命中下，甲 4/5/6 的期望击杀发数完全相同。"""
    resolver = WeaponStateResolver(gd)
    state = resolver.resolve(M4A1, loadout={}, tuning=None)
    ammo = gd.ammo_at_level(gd.get_weapon(M4A1), 5)
    legs = {"thigh": 0.5, "calf": 0.5}
    results = []
    for level in (4, 5, 6):
        armor = eg.scenario_armor(gd, {"armor_level": str(level)})
        results.append(eg.ttk_at(state, ammo, armor, legs, 0.0).expected_shots)
    assert results[0] == results[1] == results[2]


# --------------------------------------------------------------------------- #
# 3/4/5 同榜候选
# --------------------------------------------------------------------------- #

def test_pick_priced_ammos_multi_level_candidates(gd):
    """候选集合 = 3/4/5 级有价弹并集（按 ammo_item_id 升序，跨级同榜）。"""
    table = AmmoPriceTable(prices={M855: 316, M855A1: 1521})
    ammos = pick_priced_ammos(gd, M4A1, (3, 4, 5), table)
    assert [a["ammo_item_id"] for a in ammos] == [M855, M855A1]
    assert {a["penetration_level"] for a in ammos} == {3, 4}


def test_legs_rank_includes_all_levels(gd):
    """修脚榜：3/4/5 级有价弹各成行、统一起排名分层。"""
    table = AmmoPriceTable(prices={M855: 316, M855A1: 1521, M995: 4992})
    rankings, _thresholds, excluded = _run(gd, table)
    assert excluded == []
    base_rows = [r for r in rankings if r.entry_kind == "base"]
    by_id = {r.ammo_item_id: r for r in base_rows}
    assert set(by_id) == {M855, M855A1, M995}
    assert by_id[M855].ammo_price_daily == 316
    assert by_id[M995].ammo_name == "M995"
    for entry in rankings:
        for band in BAND_NAMES:
            assert entry.bands[band].rank > 0
            assert entry.bands[band].tier in {"T0", "T1", "T2", "T3"}


def test_legs_all_unpriced_excludes_weapon(gd):
    """3/4/5 全部缺价 → 该枪无行，进 excluded（与「口径无任一级弹药」同语义）。"""
    table = AmmoPriceTable(prices={"__unrelated__": 1})
    rankings, _thresholds, excluded = _run(gd, table)
    assert rankings == []
    assert len(excluded) == 1
    assert excluded[0]["profile_key"] == M4A1
    assert "缺价" in excluded[0]["reason"]


def test_legs_no_price_table_falls_back_per_level(gd):
    """价格维度未激活：每个候选等级回退官方池单弹（各级 ammo_item_id 最小者）。"""
    rankings, _thresholds, excluded = _run(gd, None)
    assert excluded == []
    base_rows = [r for r in rankings if r.entry_kind == "base"]
    assert [r.ammo_item_id for r in base_rows] == [M855, M855A1, M995]
    assert all(r.ammo_price_daily is None for r in base_rows)
