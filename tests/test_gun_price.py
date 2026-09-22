"""起枪预估价（裸枪 + 180 发备弹）与枪价装配测试。"""

import os

import pytest

from src.engine.ammo_pricing import AmmoPriceTable
from src.engine.game_data import load_game_data
from src.engine.tiering import (
    BAND_NAMES,
    SPARE_AMMO_ROUNDS,
    compute_full_price,
    rank_weapons_for_scenario,
    to_export,
)
from src.engine.weapon_pricing import WeaponPriceTable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------- #
# 纯计算
# --------------------------------------------------------------------------- #

def test_basic_full_price():
    # 87591 + 180 × 4442 = 887,451
    assert compute_full_price(87591, 4442) == 87591 + 180 * 4442


def test_full_price_uses_declared_rounds():
    assert SPARE_AMMO_ROUNDS == 180
    assert compute_full_price(100, 10) == 100 + SPARE_AMMO_ROUNDS * 10
    # 备弹数可显式覆盖（口径调整时无需改公式）
    assert compute_full_price(100, 10, rounds=60) == 700


def test_full_price_missing_inputs_yield_none():
    assert compute_full_price(None, 100) is None
    assert compute_full_price(87591, None) is None
    assert compute_full_price(None, None) is None


# --------------------------------------------------------------------------- #
# 装配层（真实官方数据）
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def _run(gd, keys, weapon_prices=None, ammo_prices=None):
    ammo_table = AmmoPriceTable(prices=ammo_prices) if ammo_prices else None
    weapon_table = WeaponPriceTable(prices=weapon_prices) if weapon_prices else None
    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=8,
        profile_keys=keys, price_table=ammo_table,
        weapon_price_table=weapon_table,
    )
    payload = to_export(
        rankings, thresholds, "armor-5-ammo-5-default", excluded,
        price_table=ammo_table, weapon_price_table=weapon_table,
    )
    return rankings, payload


def test_ranking_without_weapon_table_still_works(gd):
    """不传枪价表：TTK 与弹药成本照常，裸枪价列为 None（榜单完全可用）。"""
    rankings, payload = _run(gd, ["18050000003:base"])  # VSS
    entry = rankings[0]
    assert entry.gun_price_daily is None
    assert entry.full_price_180rd is None
    assert payload["weapon_price_meta"]["available"] is False
    weapon = payload["weapons"][0]
    assert weapon["gun_price_daily"] is None
    assert weapon["full_price_180rd"] is None


def test_gun_price_attaches_to_all_states_of_the_gun(gd):
    """裸枪价按本体计：同枪全部状态行（本体/预装态/改装态）同价。"""
    rankings, payload = _run(
        gd,
        ["18020000012:base", "18020000012:13020000563"],  # MK4 本体 + 击剑手枪管预装态
        weapon_prices={"18020000012": 142801},
    )
    assert rankings, "MK4 本体与预装态都应成行"
    for entry in rankings:
        assert entry.weapon_id == "18020000012"
        assert entry.gun_price_daily == 142801
    # 预装态行与本体行共用本体价（变体不是独立的枪）
    variant_rows = [e for e in rankings if e.entry_kind == "variant"]
    assert variant_rows, "MK4-击剑手枪管预装态应成行"
    assert all(e.gun_price_daily == 142801 for e in variant_rows)
    assert payload["weapon_price_meta"]["available"] is True
    assert payload["weapon_price_meta"]["spare_ammo_rounds"] == 180


def test_full_price_uses_row_own_ammo_price(gd):
    """180 发备弹按**该行所配弹药**的单发价计——配件改伤害不改口径，各行弹药一致时同价。"""
    rankings, _payload = _run(
        gd,
        ["18020000012:base"],
        weapon_prices={"18020000012": 142801},
    )
    entry = rankings[0]
    assert entry.ammo_price_daily is None  # 未配弹药价 → 预估价缺位
    assert entry.full_price_180rd is None

    real_ammo_id = entry.ammo_item_id
    rankings2, _p2 = _run(
        gd,
        ["18020000012:base"],
        weapon_prices={"18020000012": 142801},
        ammo_prices={real_ammo_id: 1000},
    )
    entry2 = rankings2[0]
    assert entry2.full_price_180rd == 142801 + 180 * 1000


def test_unknown_weapon_price_yields_none(gd):
    """枪价表里没有该枪（如交易行未上架）→ 只缺该枪的裸枪价列。"""
    rankings, _payload = _run(
        gd,
        ["18050000003:base"],  # VSS 不在价格表
        weapon_prices={"18010000001": 87591},
    )
    entry = rankings[0]
    assert entry.gun_price_daily is None
    assert entry.full_price_180rd is None
    # 其他枪有价不影响本枪缺价（缺价不猜测）
    assert entry.bands["贴脸"].mean_ms > 0


def test_to_export_emits_gun_price_fields(gd):
    rankings, payload = _run(
        gd,
        ["18050000003:base"],
        weapon_prices={"18050000003": 45030},
    )
    meta = payload["weapon_price_meta"]
    assert meta["available"] is True
    assert meta["currency"] == "哈夫币"
    assert meta["spare_ammo_rounds"] == 180
    weapon = payload["weapons"][0]
    assert weapon["gun_price_daily"] == 45030
    if weapon["ammo"]["price_daily"] is not None:
        expected = 45030 + 180 * weapon["ammo"]["price_daily"]
        assert weapon["full_price_180rd"] == expected
    else:
        assert weapon["full_price_180rd"] is None


def test_bands_untouched_by_gun_price(gd):
    """枪价对战斗链路零侵入：有无枪价表，各带 TTK / 期望发数逐位一致。"""
    base_rankings, _ = _run(gd, ["18050000003:base"])
    priced_rankings, _ = _run(gd, ["18050000003:base"], weapon_prices={"18050000003": 45030})
    for bare, priced in zip(base_rankings, priced_rankings):
        for band in BAND_NAMES:
            assert bare.bands[band].mean_ms == priced.bands[band].mean_ms
            assert bare.bands[band].mean_expected_shots == priced.bands[band].mean_expected_shots
