"""弹维度展开测试：同枪多款有效弹各出一行；缺价弹与过期赛季限定弹不上榜。

口径（2026-10-05 榜单改造）：

- 候选弹 = 该口径该等级全部弹药中 ``price_daily`` 非 null（有价 = 玩家市场可得）
  **且非过期赛季限定**（常驻恒有效；赛季限定仅当前赛季有效，见
  ranking.CURRENT_SEASON 常量）；
- 每款有效弹独立束搜索、独立出状态行（行自带弹药名 / 单发价 / 成本）；
- 该等级全部弹无效 → 该枪排除（与「口径无该等级弹药」同语义）；
- 价格表未配置（``None`` / 空表）→ 价格维度不激活，回退官方池单弹。

数据锚点：5.56x45mm 4 级 = M855A1（``37100400001``，常驻）+ M855A1 APC+
（``37100400002``，S9 赛季限定——即使配价也被赛季过滤排除）；4.6x30mm 4 级 =
FMJ SX + FMJ ST（真实价格表两款均有价）。多弹展开测试用 monkeypatch 将
APC+ 模拟为常驻弹（隔离赛季维度，专注展开逻辑）。
"""

import os

import pytest

from src.engine.ammo_pricing import AmmoPriceTable, load_ammo_prices
from src.engine.engagement import ScenarioError
from src.engine.game_data import load_game_data
from src.engine.ranking import pick_priced_ammos, rank_weapons_for_scenario
from src.engine.tiering import BAND_NAMES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M4A1 = "18010000001:base"
MP7 = "18020000010:base"
M855A1 = "37100400001"
M855A1_APC = "37100400002"
SCENARIO_44 = "armor-4-ammo-4-default"


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def _force_regular(gd, ammo_item_id):
    """把指定弹模拟为常驻（剥除赛季限定标注），隔离赛季维度测展开逻辑。"""
    for record in gd.ammo:
        if record["ammo_item_id"] == ammo_item_id:
            record["is_season_limited"] = False
            record["season_note"] = None
            return


def _run(gd, price_table, key=M4A1, scenario=SCENARIO_44, beam_width=8):
    return rank_weapons_for_scenario(
        gd, scenario, beam_width=beam_width, profile_keys=[key],
        price_table=price_table,
    )


# --------------------------------------------------------------------------- #
# pick_priced_ammos：候选集口径
# --------------------------------------------------------------------------- #

def test_pick_priced_ammos_filters_unpriced(gd):
    """只保留 price_daily 非 null 的弹：APC+ 未配价 → 被过滤。"""
    table = AmmoPriceTable(prices={M855A1: 1641})
    ammos = pick_priced_ammos(gd, M4A1, 4, table)
    assert [a["ammo_item_id"] for a in ammos] == [M855A1]


def test_pick_priced_ammos_all_priced_sorted_by_item_id(gd):
    """多款有效弹全部返回，按 ammo_item_id 升序（确定性枚举顺序）。"""
    _force_regular(gd, M855A1_APC)
    table = AmmoPriceTable(prices={M855A1_APC: 2000, M855A1: 1641})
    ammos = pick_priced_ammos(gd, M4A1, 4, table)
    assert [a["ammo_item_id"] for a in ammos] == [M855A1, M855A1_APC]


def test_pick_priced_ammos_filters_expired_season(gd):
    """过期赛季限定弹即使配价也被过滤（当前 S11，S9 赛季限定子弹排除）。"""
    for record in gd.ammo:
        if record["ammo_item_id"] == M855A1_APC:
            record["is_season_limited"] = True
            record["season_note"] = "S9赛季限定子弹"
            break
    table = AmmoPriceTable(prices={M855A1_APC: 2000, M855A1: 1641})
    ammos = pick_priced_ammos(gd, M4A1, 4, table)
    assert [a["ammo_item_id"] for a in ammos] == [M855A1]
    # 恢复常驻模拟供后续多弹展开测试使用
    _force_regular(gd, M855A1_APC)


def test_pick_priced_ammos_no_level_ammo_raises(gd):
    """口径无该等级弹药 → ScenarioError（与 pick_ammo 同语义）。"""
    table = AmmoPriceTable(prices={M855A1: 1641})
    with pytest.raises(ScenarioError):
        pick_priced_ammos(gd, "18020000001:base", 5, table)  # MP5 9x19mm 无 5 级弹


def test_pick_priced_ammos_inactive_price_dimension_returns_empty(gd):
    """价格表未配置（None / 空表）→ []：价格维度不激活，调用方回退官方池单弹。"""
    assert pick_priced_ammos(gd, M4A1, 4, None) == []
    assert pick_priced_ammos(gd, M4A1, 4, AmmoPriceTable()) == []


# --------------------------------------------------------------------------- #
# 展开：每款有价弹独立成行
# --------------------------------------------------------------------------- #

def test_multi_ammo_expands_base_rows(gd):
    """两款有价弹 → 本体两行，各带自己的弹药名与单价。"""
    _force_regular(gd, M855A1_APC)
    table = AmmoPriceTable(prices={M855A1: 1641, M855A1_APC: 2000})
    rankings, _thresholds, excluded = _run(gd, table)
    assert excluded == []
    base_rows = [r for r in rankings if r.entry_kind == "base"]
    assert len(base_rows) == 2
    by_id = {r.ammo_item_id: r for r in base_rows}
    assert set(by_id) == {M855A1, M855A1_APC}
    assert by_id[M855A1].ammo_name == "M855A1"
    assert by_id[M855A1].ammo_price_daily == 1641
    assert by_id[M855A1_APC].ammo_name == "M855A1 APC+"
    assert by_id[M855A1_APC].ammo_price_daily == 2000


def test_multi_ammo_expands_beam_states_per_ammo(gd):
    """每款弹独立束搜索：改装状态行按弹各成一套，行自带所属弹。"""
    _force_regular(gd, M855A1_APC)
    table = AmmoPriceTable(prices={M855A1: 1641, M855A1_APC: 2000})
    rankings, _thresholds, _excluded = _run(gd, table)
    state_rows = [r for r in rankings if r.entry_kind == "state"]
    assert state_rows, "束搜索应枚举出改装状态"
    per_ammo = {ammo_id: [r for r in state_rows if r.ammo_item_id == ammo_id]
                for ammo_id in (M855A1, M855A1_APC)}
    assert all(rows for rows in per_ammo.values()), "每款弹都应有自己的改装状态行"
    # 不同弹的同名状态是不同行：签名含弹药维度，两套状态行互不吞并
    for rows in per_ammo.values():
        signatures = [
            tuple(round(r.bands[b].mean_ms, 6) for b in BAND_NAMES) for r in rows
        ]
        assert len(signatures) == len(set(signatures))


def test_multi_ammo_rows_carry_own_cost(gd):
    """击杀成本 / 起枪预估价按该行所配弹药的单发价计。"""
    _force_regular(gd, M855A1_APC)
    table = AmmoPriceTable(prices={M855A1: 1000, M855A1_APC: 2000})
    rankings, _thresholds, _excluded = _run(gd, table, beam_width=8)
    for entry in rankings:
        unit = 1000 if entry.ammo_item_id == M855A1 else 2000
        for band in BAND_NAMES:
            stats = entry.bands[band]
            assert stats.kill_cost == int(stats.mean_expected_shots * unit + 0.5)


def test_all_ammos_ranked_and_tiered_together(gd):
    """同枪多弹的行合并统一排名与 T0–T3 分层（同弹内 TTK 互异行全都有层级）。"""
    _force_regular(gd, M855A1_APC)
    table = AmmoPriceTable(prices={M855A1: 1641, M855A1_APC: 2000})
    rankings, thresholds, _excluded = _run(gd, table)
    assert rankings
    for entry in rankings:
        for band in BAND_NAMES:
            assert entry.bands[band].rank > 0
            assert entry.bands[band].tier in {"T0", "T1", "T2", "T3"}
    assert set(thresholds) == set(BAND_NAMES)


# --------------------------------------------------------------------------- #
# 过滤与排除
# --------------------------------------------------------------------------- #

def test_real_price_table_apc_plus_unpriced_single_ammo(gd):
    """真实价格表：APC+ 当前无价 → 4-4 情景 M4A1 全部行只用 M855A1，本体仅一行。

    数据锚点断言：APC+ 在当前 ammo_prices.json 中缺价（价格表每日更新，
    若将来上架，本测试的前置断言会先失败提醒更换样例）。
    """
    table = load_ammo_prices(os.path.join(ROOT, "data", "reference", "ammo_prices.json"))
    assert table.price_for(M855A1_APC) is None, "前提失效：APC+ 已有价，请更换无价弹样例"
    rankings, _thresholds, excluded = _run(gd, table)
    assert excluded == []
    base_rows = [r for r in rankings if r.entry_kind == "base"]
    assert len(base_rows) == 1
    assert base_rows[0].ammo_item_id == M855A1
    assert {r.ammo_item_id for r in rankings} == {M855A1}


def test_real_price_table_multi_priced_ammo_expands(gd):
    """真实价格表（无 monkeypatch）：4.6x30mm 4 级 FMJ SX / FMJ ST 均有价 → MP7 本体两行。"""
    table = load_ammo_prices(os.path.join(ROOT, "data", "reference", "ammo_prices.json"))
    rankings, _thresholds, excluded = _run(gd, table, key=MP7)
    assert excluded == []
    base_rows = [r for r in rankings if r.entry_kind == "base"]
    assert len(base_rows) == 2
    assert {r.ammo_item_id for r in base_rows} == {"37260400001", "37260400002"}
    assert all(r.ammo_price_daily is not None for r in rankings)


def test_all_unpriced_excludes_weapon(gd):
    """该等级全部弹缺价 → 该枪无行，进 excluded（与口径无弹同语义）。"""
    table = AmmoPriceTable(prices={"__unrelated__": 1})
    rankings, _thresholds, excluded = _run(gd, table)
    assert rankings == []
    assert len(excluded) == 1
    assert excluded[0]["profile_key"] == M4A1
    assert "缺价" in excluded[0]["reason"]


def test_no_price_table_falls_back_to_official_pool(gd):
    """价格维度未激活：回退官方池单弹（同等级 ammo_item_id 最小 = M855A1）。"""
    rankings, _thresholds, excluded = _run(gd, None)
    assert excluded == []
    base_rows = [r for r in rankings if r.entry_kind == "base"]
    assert len(base_rows) == 1
    assert base_rows[0].ammo_item_id == M855A1
    assert base_rows[0].ammo_price_daily is None
    assert all(r.bands[b].kill_cost is None for r in rankings for b in BAND_NAMES)


def test_single_priced_non_official_ammo_scores_beam_with_it(gd):
    """唯一有价弹 ≠ 官方池弹：束搜索打分以该弹为准（行弹与打分弹一致）。

    5.56 4 级官方池弹 = ammo_item_id 最小的 M855A1；只给 APC+ 配价时，
    枚举与全部行都必须围绕 APC+ 展开。
    """
    table = AmmoPriceTable(prices={M855A1_APC: 2000})
    rankings, _thresholds, excluded = _run(gd, table)
    assert excluded == []
    assert rankings, "APC+ 有价 → 应成行"
    assert {r.ammo_item_id for r in rankings} == {M855A1_APC}
    base_rows = [r for r in rankings if r.entry_kind == "base"]
    assert len(base_rows) == 1
    assert base_rows[0].ammo_name == "M855A1 APC+"


def test_real_price_table_excludes_bcp_sub_even_if_priced(gd):
    """S8 赛季限定弹 BCP-SUB（37280400002）即使在价格表中有价，也被赛季过滤排除。

    K437（.300BLK 4级）只能选用常驻弹 BCP-FMJ（37280400001）。
    """
    table = AmmoPriceTable(prices={"37280400001": 1897, "37280400002": 2500})
    rankings, _thresholds, excluded = _run(gd, table, key="18010000040:base", beam_width=8)
    assert excluded == []
    ammo_ids = {r.ammo_item_id for r in rankings}
    assert "37280400002" not in ammo_ids
    assert "37280400001" in ammo_ids
    assert all(r.ammo_name == "BCP-FMJ" for r in rankings)

