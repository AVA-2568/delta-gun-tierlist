"""弹药对齐管线回归（离线，黄金集 fixtures/orzice/ammo_rows_golden.json）。

只锁**行名与对齐结论**，不锁具体价格数值（盘中漂移；note 内引用的行情价
随黄金集冻结，故可精确断言）：

- L1 权威键 ammo_item_id：合并条目 37250400005（DART）从价格表骨架消失，不留重定向；
- L2 名称对齐：mm/引号/空白归一化、行名字级别名（箭形→箭型、鼠弹→鼠蛋、DART→箭型弹）；
- L3 ``<口径>_N`` 合并行：组内候选弹药对齐该口径同等级行情价；
- 同 id 多行取**全行最小价** + note 记全源价（弃行序依赖的取首行）；
- normalize 层合并护栏：MERGED_AMMO_IDS 应用前运行时重验弹道字段全等。

黄金集 provenance 详见 fixtures/orzice/ammo_rows_golden.json（30 行晨间实抓解析
+ 5 行定稿方案行情考古点名行）。
"""

import json
from pathlib import Path

from src.collectors import orzice_price_sync as mod
from src.collectors.normalize import (
    MERGED_AMMO_IDS,
    ammo_type_to_caliber_map,
    normalize_ammo,
)

ROOT = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "orzice" / "ammo_rows_golden.json"


def _load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _match():
    payload = _load_fixture()
    catalog = mod.load_ammo_catalog(str(ROOT / "data" / "game" / "ammo.json"))
    prices, notes = mod.match_ammo_prices(
        payload["rows"], catalog, mod.build_ammo_name_map(catalog)
    )
    return payload, catalog, prices, notes


# ---- 归一化与别名（单元） ----

def test_norm_name_strips_straight_and_curly_quotes():
    """站方直引号 ↔ 官方弯引号统一剥除（鼠蛋系行名的引号风格差异）。"""
    assert mod.norm_name('9号霰射"鼠蛋"') == mod.norm_name("9号霰射“鼠蛋”")
    assert mod.norm_name("9号霰射‘鼠蛋’") == mod.norm_name("9号霰射“鼠蛋”")
    assert mod.norm_name('9号霰射"鼠弹"') != mod.norm_name("9号霰射“鼠蛋”")  # 别名归别名层管


def test_fold_name_aliases_row_side_only():
    assert mod.fold_name_aliases("12 Gauge箭形弹") == "12 Gauge箭型弹"
    assert mod.fold_name_aliases("12 Gauge DART") == "12 Gauge 箭型弹"
    assert mod.fold_name_aliases('9号霰射"鼠弹"') == '9号霰射"鼠蛋"'
    assert mod.fold_name_aliases("V-Max") == "V-Max"  # 未知名原样
    # 别名只折叠行名侧：官方目录名不折叠（防止目录侧制造撞名键）
    assert "DART" not in mod.NAME_ALIASES.values()


def test_parse_rows_decodes_html_entities_then_alias_row_matches():
    """站方行名引号以 HTML 实体下发（2026-09-30 晚实证 &#34;鼠弹&#34;=318 漏配落 null）。

    parse_rows 先 HTML unescape，再经引号剥除+别名折叠命中 9号霰射“鼠蛋”。
    """
    page = (
        "<table><tr><td><div class=\"ui-item\"><div class=\"ui-tname\">"
        ".357 Magnum 9号霰射&#34;鼠弹&#34;</div></div></td>"
        "<td><div class=\"ui-cell-gold\"><span class=\"icon-gold ui-num\">318</span></div></td></tr></table>"
    )
    rows = mod.parse_rows(page)
    assert rows[0]["name"] == '.357 Magnum 9号霰射"鼠弹"'
    catalog = mod.load_ammo_catalog(str(ROOT / "data" / "game" / "ammo.json"))
    prices, _notes = mod.match_ammo_prices(rows, catalog, mod.build_ammo_name_map(catalog))
    assert prices["37220000001"] == 318  # 不再落 null（缺价不猜测≠漏配缺陷）


# ---- 黄金集对齐结论 ----

def test_golden_fixture_all_priced_rows_resolved():
    """35 有价行全部对齐，覆盖 34 个有效 ammo_item_id（过往赛季限定弹如 S8 V-SUB/BCP-SUB 排除），零静默未匹配。"""
    payload, catalog, prices, notes = _match()
    priced_rows = [r for r in payload["rows"] if r["price"]]
    assert len(priced_rows) == 35
    assert len(prices) == 34
    # 唯一 note 为双源取 min 的箭型弹
    assert len(notes) == 1 and "37250300001" in notes


def test_golden_fixture_merged_id_absent_from_skeleton():
    """合并条目 37250400005 不进价格表骨架（L1 权威键合并即消失，不留重定向）。"""
    _payload, catalog, prices, _notes = _match()
    assert MERGED_AMMO_IDS == {"37250400005": "37250300001"}
    assert "37250400005" not in catalog
    table = mod.build_ammo_table(catalog, prices, "2026-09-30", notes=_notes)
    table_ids = [row["ammo_item_id"] for row in table["ammo"]]
    assert len(table_ids) == len(catalog) == 113
    assert "37250400005" not in table_ids


def test_golden_fixture_alias_rows_aligned():
    payload, _catalog, prices, _notes = _match()
    by_name = {r["name"]: r for r in payload["rows"]}
    # 箭形弹行 + DART 行 → 同 id 37250300001（箭型弹），双源取 min
    assert by_name["12 Gauge箭形弹"]["price"] < by_name["12 Gauge DART"]["price"]
    assert prices["37250300001"] == by_name["12 Gauge箭形弹"]["price"]
    # 鼠弹行（引号风格 + 别名）→ 9号霰射“鼠蛋”
    assert prices["37220000001"] == by_name['.357 Magnum 9号霰射"鼠弹"']["price"]
    # \xa0 行名 → 7.62x51mm Ultra Nosler（空口径条目按名可命中）
    assert prices["37170200001"] == by_name["7.62x51mm\xa0Ultra\xa0Nosler"]["price"]


def test_golden_fixture_same_id_multi_row_takes_min_with_note():
    """同 id 双行（页序非确定性）→ 全行最小价 + note 记全源价，弃「取首行」。"""
    _payload, _catalog, prices, notes = _match()
    assert prices["37250300001"] == 400  # min(箭形弹 400, DART 523)
    note = notes["37250300001"]
    assert note == "orzice 12 Gauge箭形弹=400; 12 Gauge DART=523"


def test_golden_fixture_level_rows_aligned():
    """``<口径>_N`` 通道：合并行情行对齐组内同口径同等级候选弹药（过往赛季限定弹安全排除）。"""
    _payload, _catalog, prices, _notes = _match()
    # .300BLK_5 → TAC-TX 唯一 5 级弹 → aligned
    assert prices["37280500001"] == 4968
    # .300BLK_3 → 仅对齐常驻 3 级弹 V-Max；V-SUB（S8赛季限定）安全排除
    assert prices["37280300001"] == 497
    assert "37280300002" not in prices
    # .300BLK_4 → 仅对齐常驻 4 级弹 BCP-FMJ；BCP-SUB（S8赛季限定）安全排除
    assert prices["37280400001"] == 1757
    assert "37280400002" not in prices


def test_golden_fixture_objectid_rows_exact_match():
    """带官方 objectID 的行（45-70 系/箭矢）精确匹配，不经名称层。"""
    _payload, _catalog, prices, _notes = _match()
    for item_id in ("37290300001", "37290400001", "37290500001", "37270300001"):
        assert item_id in prices and prices[item_id] > 0


def test_golden_fixture_generic_name_rows_aligned():
    """泛口径图行按归一化「口径+名称」全等匹配（mm/空白桥接）。"""
    _payload, _catalog, prices, _notes = _match()
    assert prices["37160400001"] == 1942  # 12.7x55mm PS12（口径 12.7x55）
    assert prices["37100300001"] == 451  # 5.56x45mm M855
    assert all(p > 0 for p in prices.values())


def test_golden_fixture_table_notes_are_additive_schema():
    """note 为可选增列：无 note 行字段集不变（向后兼容，消费方只读 price_daily）。"""
    _payload, catalog, prices, notes = _match()
    table = mod.build_ammo_table(catalog, prices, "2026-09-30", notes=notes)
    by_id = {row["ammo_item_id"]: row for row in table["ammo"]}
    assert set(by_id["37100100001"]) == {
        "ammo_item_id", "caliber", "name", "penetration_level", "price_daily",
    }
    assert set(by_id["37250300001"]) == {
        "ammo_item_id", "caliber", "name", "penetration_level", "price_daily", "note",
    }


# ---- normalize 层：合并护栏 + caliber 回填映射（单元） ----

def _ammo_catalog_pair(flesh_b: float):
    """构造 37250300001/37250400005 双条目原始目录（弹道字段除 flesh 外全等）。"""
    def _entry(ammo_id, name, flesh, rarity="蓝", legacy=None):
        return {
            "name": name, "caliber": "12Gauge", "ammoTypeId": "25",
            "penetrationLevel": 3, "fleshDamageMultiplier": flesh,
            "armorDamageMultiplier": 1.0, "rarity": rarity,
            "sourceLegacyAmmoId": legacy,
        }

    return {"ammo": {
        "37250300001": _entry("37250300001", "箭型弹", 0.85, legacy="505"),
        "37250400005": _entry("37250400005", "DART", flesh_b, rarity="紫"),
    }}


_EMPTY_OVERRIDES = {"weapons": {}, "ammo": {}, "armor": {}}


def test_normalize_ammo_merges_ballistic_equal_pair():
    merges = []
    records = normalize_ammo(
        _ammo_catalog_pair(flesh_b=0.85), {"profiles": {}}, _EMPTY_OVERRIDES, [],
        merges=merges,
    )
    ids = [r["ammo_item_id"] for r in records]
    assert ids == ["37250300001"]  # 被并条目消失，不留重定向
    assert merges == [{
        "removed": "37250400005 DART",
        "into": "37250300001 箭型弹",
        "evidence": "弹道字段全等（运行时逐字段重验，非身份键零差异）",
    }]


def test_normalize_ammo_merge_guard_skips_when_ballistics_diverge():
    """上游改数值（弹道不再全等）→ 告警并跳过合并，防误并。"""
    merges = []
    records = normalize_ammo(
        _ammo_catalog_pair(flesh_b=4.8), {"profiles": {}}, _EMPTY_OVERRIDES, [],
        merges=merges,
    )
    ids = sorted(r["ammo_item_id"] for r in records)
    assert ids == ["37250300001", "37250400005"]  # 两目都保留
    assert merges == []


def test_ammo_type_to_caliber_map_first_non_empty():
    """口径回填：类型内按 (pen, id) 序取首个非空 caliber；全空类型不入映射。"""
    records = [
        {"ammo_type_id": "17", "penetration_level": 2, "ammo_item_id": "37170200001", "caliber": ""},
        {"ammo_type_id": "17", "penetration_level": 3, "ammo_item_id": "37170300001", "caliber": "7.62x51mm"},
        {"ammo_type_id": "17", "penetration_level": 4, "ammo_item_id": "37170400001", "caliber": "7.62x51mm"},
        {"ammo_type_id": "28", "penetration_level": 3, "ammo_item_id": "37270300001", "caliber": ""},
    ]
    mapping = ammo_type_to_caliber_map(records)
    assert mapping == {"17": "7.62x51mm"}
