"""S12 新弹口径与行情对齐回归（.300BLK TIV/TTV、CINDER 等）。

回归的三件事：

1. **口径回填**：上游对部分新弹不给 ``caliber``（``.300 BLK TIV``/``5.56×45 CINDER``
   等）。弹药类型内口径唯一，按类型回填；名字自带的重复口径前缀同时剥离，
   否则榜单会渲染成 ``.300BLK .300 BLK TIV``。
2. **行情匹配**：口径回填后名字键不得变成双口径（``.300blk.300blktiv``），
   否则行情页的 ``.300 BLK TIV`` 永远匹配不上。
3. **成行不依赖行情**：新弹当日无价时仍须上榜，价格字段为 None（渲染为 —）。
"""

import json
import os

import pytest

from src.collectors import orzice_price_sync as mod
from src.collectors.normalize import (
    backfill_ammo_calibers,
    strip_caliber_prefix,
)
from src.engine.ammo_pricing import AmmoPriceTable
from src.engine.game_data import load_game_data
from src.engine.ranking import rank_weapons_for_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIV = "37280400003"   # .300BLK 4 级（S12 叠层引爆）
TTV = "37280500003"   # .300BLK 5 级（S12 叠层引爆）
MCX_LT = "18010000044:base"


def _tables_ammo():
    path = os.path.join(ROOT, "data", "tables", "ammo.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["ammo"]


# --------------------------------------------------------------------------- #
# 名字去重
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "name, caliber, expected",
    [
        (".300 BLK TIV", ".300BLK", "TIV"),
        ("5.56×45 CINDER", "5.56x45mm", "CINDER"),
        ("9×19mm 7N30", "9x19mm", "7N30"),
        (".45 ACP CT", ".45ACP", "CT"),
        ("12 Gauge 龙息弹", "12Gauge", "龙息弹"),
        ("7.62x51mm\u00a0Ultra\u00a0Nosler", "7.62x51mm", "Ultra Nosler"),
        # 名字不以口径开头 → 原样保留
        ("M62", "7.62x51mm", "M62"),
        ("M855A1 APC+", "5.56x45mm", "M855A1 APC+"),
        # 无口径（type28 箭矢）→ 不动
        ("碳纤维穿甲箭矢", "", "碳纤维穿甲箭矢"),
    ],
)
def test_strip_caliber_prefix(name, caliber, expected):
    assert strip_caliber_prefix(name, caliber) == expected


# --------------------------------------------------------------------------- #
# 口径回填
# --------------------------------------------------------------------------- #

def test_backfill_caliber_from_ammo_type():
    records = [
        {"ammo_item_id": "a", "name": "V-Max", "caliber": ".300BLK", "ammo_type_id": "27", "penetration_level": 3},
        {"ammo_item_id": "b", "name": ".300 BLK TIV", "caliber": "", "ammo_type_id": "27", "penetration_level": 4},
    ]
    backfill_ammo_calibers(records)
    assert records[1]["caliber"] == ".300BLK"
    assert records[1]["name"] == "TIV"


def test_backfill_keeps_empty_caliber_when_type_has_none():
    """类型内全部无口径（type28 箭矢）→ 保持空串，不猜口径。"""
    records = [
        {"ammo_item_id": "a", "name": "玻纤柳叶箭矢", "caliber": "", "ammo_type_id": "28", "penetration_level": 3},
    ]
    backfill_ammo_calibers(records)
    assert records[0]["caliber"] == ""
    assert records[0]["name"] == "玻纤柳叶箭矢"


def test_tables_ammo_has_no_blank_caliber_except_arrows():
    """运行期真源：除 type28 箭矢外，任何弹都不允许空口径。"""
    for record in _tables_ammo():
        if record["caliber"]:
            continue
        assert record["ammo_type_id"] == "28", (
            f"{record['ammo_item_id']} {record['name']} 口径为空，但并非箭矢类型"
        )


def test_new_season_ammo_caliber_filled():
    by_id = {r["ammo_item_id"]: r for r in _tables_ammo()}
    assert by_id[TIV]["caliber"] == ".300BLK" and by_id[TIV]["name"] == "TIV"
    assert by_id[TTV]["caliber"] == ".300BLK" and by_id[TTV]["name"] == "TTV"


# --------------------------------------------------------------------------- #
# 行情匹配键
# --------------------------------------------------------------------------- #

def test_ammo_name_key_matches_prefixed_market_row():
    """口径回填后名字键不得双口径：行情行 ``.300 BLK TIV`` 仍须命中。"""
    catalog = {
        TIV: {"caliber": ".300BLK", "name": "TIV", "penetration_level": 4},
    }
    name_map = mod.build_ammo_name_map(catalog)
    row = {"name": ".300 BLK TIV", "price": 1234, "object_id": None}
    assert mod._resolve_ammo_row(row, catalog, name_map) == [TIV]


def test_blk_fmj_alias_maps_to_bcp_fmj():
    """行情页把 4 级写成 ``.300 BLK FMJ``，目录名为 ``BCP-FMJ``。"""
    catalog = {
        "37280400001": {"caliber": ".300BLK", "name": "BCP-FMJ", "penetration_level": 4},
    }
    name_map = mod.build_ammo_name_map(catalog)
    row = {"name": ".300 BLK FMJ", "price": 1687, "object_id": None}
    assert mod._resolve_ammo_row(row, catalog, name_map) == ["37280400001"]


# --------------------------------------------------------------------------- #
# 缺价照样成行
# --------------------------------------------------------------------------- #

def test_unpriced_new_ammo_still_ranked_with_blank_price():
    """MCX-LT 在 5-5 情景：TAC-TX 有价、TTV 无价，两弹都必须在榜。

    价格表由测试自建：行情每日变动，不能把「某款弹当日无价」写成测试前提
    （2026-11-06/07 的 CI 失败即由此引起）。
    """
    gd = load_game_data(os.path.join(ROOT, "data", "game"))
    table = AmmoPriceTable(prices={"37280500001": 5418})
    rankings, _thresholds, excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=4, profile_keys=[MCX_LT],
        price_table=table,
    )
    assert excluded == []
    base_rows = {r.ammo_item_id: r for r in rankings if r.entry_kind == "base"}
    assert {"37280500001", TTV} <= set(base_rows)
    assert base_rows["37280500001"].ammo_price_daily == 5418
    assert base_rows[TTV].ammo_price_daily is None
    assert base_rows[TTV].ammo_name == "TTV"
