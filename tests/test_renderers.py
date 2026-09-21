"""渲染层测试：只格式化、不出数值。"""

import pytest

from src.renderers.ttk_report import (
    loadout_text,
    render_band_table,
    render_gunsmith_guide,
    render_readme,
    render_scenario_markdown,
)

PART_NAMES = {"13020000173": "AR特勤一体消音组合", "13020000349": "AR加百列长枪管组合"}

PAYLOAD = {
    "scenario_id": "armor-5-ammo-5-default",
    "ranking_key": "band_mean_ttk_ms",
    "tier_thresholds_ms": {
        "贴脸": {"T0": 320.0, "T1": 360.0, "T2": 420.0},
        "远距": {"T0": 400.0, "T1": 460.0, "T2": 520.0},
    },
    "band_definitions": {
        "贴脸": {"from_m": 0.0, "to_m": 15.0},
        "近距": {"from_m": 15.0, "to_m": 30.0},
        "中距": {"from_m": 30.0, "to_m": 50.0},
        "远距": {"from_m": 50.0, "to_m": 80.0},
    },
    "weapons": [
        {
            "profile_key": "18010000001:base",
            "name": "M4A1",
            "loadout": {"2": "13020000173"},
            "expected_shots_0m": 5.8348,
            "rpm": 800.0,
            "effective_range_m": 47.2,
            "bands": {
                "贴脸": {"rank": 1, "tier": "T0", "mean_ms": 362.61, "worst_ms": 362.61, "best_ms": 362.61},
                "远距": {"rank": 2, "tier": "T1", "mean_ms": 431.32, "worst_ms": 431.32, "best_ms": 431.32},
            },
        },
        {
            "profile_key": "18010000006:base",
            "name": "AKM",
            "loadout": {},
            "expected_shots_0m": 4.67,
            "rpm": 600.0,
            "effective_range_m": 40.0,
            "bands": {
                "贴脸": {"rank": 2, "tier": "T1", "mean_ms": 366.69, "worst_ms": 366.69, "best_ms": 366.69},
            },
        },
    ],
}

SCENARIO_META = {
    "scenario_id": "armor-5-ammo-5-default",
    "label": "5套 · 5弹 · 实战概率",
    "armor_level": "5",
    "ammo_level": 5,
    "probability_preset": "default",
    "helmet_durability": 50,
    "armor_durability": 125,
}


def test_loadout_text_uses_part_names():
    assert loadout_text({"2": "13020000173"}, PART_NAMES) == "AR特勤一体消音组合"
    assert loadout_text({}, PART_NAMES) == "官方默认"
    assert loadout_text({"9": "unknown_id"}, PART_NAMES) == "unknown_id"


def test_band_table_sorted_by_rank_and_complete():
    table = render_band_table(PAYLOAD, "贴脸", PART_NAMES)
    lines = table.splitlines()
    assert lines[0].startswith("| # | 层级 | 武器 |")
    # 表头 + 分隔 + 2 行数据
    assert len(lines) == 4
    assert lines[2].startswith("| 1 | **T0** | M4A1 |")
    assert lines[3].startswith("| 2 | T1 | AKM |")
    assert lines[3].endswith("官方默认 |")


def test_band_table_limit():
    table = render_band_table(PAYLOAD, "贴脸", PART_NAMES, limit=1)
    assert len(table.splitlines()) == 3


def test_scenario_markdown_contains_definition_and_thresholds():
    md = render_scenario_markdown(PAYLOAD, SCENARIO_META, PART_NAMES)
    assert "# 纯 TTK 榜单" in md
    assert "`armor-5-ammo-5-default`" in md
    assert "5 套 · 5 弹" in md
    assert "(期望击杀发数 − 1) × 射击间隔" in md
    assert "T0 ≤ 320.0 ms" in md
    assert "## 贴脸（0–15 m）" in md
    # 没有数据的带不渲染
    assert "## 中距" not in md


def test_readme_lists_main_bands_and_scenario_index():
    md = render_readme(
        PAYLOAD,
        SCENARIO_META,
        {"source": {"name": "dfttk-v3", "dataset_version": "20260911-044903.3"}},
        PART_NAMES,
        scenario_index=[SCENARIO_META],
    )
    assert "# 三角洲行动 · 纯 TTK 枪械强度榜" in md
    assert "### 贴脸（0–15 m）" in md
    assert "docs/tierlist/armor-5-ammo-5-default.md" in md
    assert "20260911-044903.3" in md


def test_gunsmith_guide_generates_workbench_table():
    from src.engine.game_data import load_game_data
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gd = load_game_data(os.path.join(root, "data", "game"))
    md = render_gunsmith_guide(gd, {"source": {"name": "dfttk-v3", "dataset_version": "x"}})
    assert "# 改枪指南" in md
    # 官方操控曲线：操控 50 → 350ms
    assert "| 50 | 350 ms |" in md
    # 精校目标总览必须说明其不影响 TTK
    assert "没有任何一个改变期望击杀发数或射击间隔" in md
    assert "GAiming_ADSTime" in md


PAYLOAD_WITH_COST = {
    **PAYLOAD,
    "ammo_price_meta": {
        "currency": "哈夫币",
        "window": {"from": "2026-08-23", "to": "2026-09-21", "days": 30},
        "updated_at": "2026-09-21",
        "available": True,
    },
    "weapons": [
        {
            **PAYLOAD["weapons"][0],
            "ammo": {"ammo_item_id": "37260500001", "name": "AP SX",
                     "caliber": "4.6x30mm", "price_avg_30d": 4579},
            "bands": {
                "贴脸": {"rank": 1, "tier": "T0", "mean_ms": 286.92, "worst_ms": 286.92,
                         "best_ms": 286.92, "mean_expected_shots": 5.543, "kill_cost": 25381},
            },
        }
    ],
}


def test_band_table_has_three_new_columns():
    table = render_band_table(PAYLOAD_WITH_COST, "贴脸", PART_NAMES)
    header = table.splitlines()[0]
    assert "弹药" in header
    assert "单发价" in header
    assert "击杀成本" in header
    # 位置：紧跟在「期望击杀发数@0m」之后
    assert header.index("期望击杀发数@0m") < header.index("弹药") < header.index("单发价") < header.index("击杀成本")


def test_band_table_renders_ammo_and_money():
    table = render_band_table(PAYLOAD_WITH_COST, "贴脸", PART_NAMES)
    assert "4.6x30mm AP SX" in table
    assert "4,579 哈夫币" in table
    assert "25,381 哈夫币" in table


def test_missing_price_renders_dash():
    payload = {
        **PAYLOAD_WITH_COST,
        "ammo_price_meta": {**PAYLOAD_WITH_COST["ammo_price_meta"], "available": False},
        "weapons": [
            {**PAYLOAD_WITH_COST["weapons"][0],
             "ammo": {"ammo_item_id": "x", "name": "AP SX", "caliber": "4.6x30mm",
                      "price_avg_30d": None},
             "bands": {"贴脸": {"rank": 1, "tier": "T0", "mean_ms": 286.92, "worst_ms": 286.92,
                                "best_ms": 286.92, "mean_expected_shots": 5.543,
                                "kill_cost": None}}}
        ],
    }
    table = render_band_table(payload, "贴脸", PART_NAMES)
    assert "AP SX" in table
    assert "哈夫币" not in table  # 缺价时不得出现金额
    assert "—" in table


def test_empty_caliber_renders_name_only():
    payload = {
        **PAYLOAD_WITH_COST,
        "weapons": [
            {**PAYLOAD_WITH_COST["weapons"][0],
             "ammo": {"ammo_item_id": "y", "name": "碳纤维穿甲箭矢", "caliber": "",
                      "price_avg_30d": 1000},
             "bands": {"贴脸": {"rank": 1, "tier": "T0", "mean_ms": 286.92, "worst_ms": 286.92,
                                "best_ms": 286.92, "mean_expected_shots": 5.0, "kill_cost": 5000}}}
        ],
    }
    table = render_band_table(payload, "贴脸", PART_NAMES)
    assert "碳纤维穿甲箭矢" in table
    assert "哈夫币" in table  # 有价时金额正常出现


def test_ammo_label_skips_empty_caliber():
    """直接单测格式化函数：空口径只输出型号，无前导/尾随空格。

    不在表格层断言前导空格——表格单元格会被 strip，那类缺陷在那里测不出来（会变成恒真断言）。
    """
    from src.renderers.ttk_report import _ammo_label

    assert _ammo_label({"caliber": "4.6x30mm", "name": "AP SX"}) == "4.6x30mm AP SX"
    assert _ammo_label({"caliber": "", "name": "碳纤维穿甲箭矢"}) == "碳纤维穿甲箭矢"
    assert _ammo_label({"caliber": None, "name": "碳纤维穿甲箭矢"}) == "碳纤维穿甲箭矢"
    assert _ammo_label({}) == "—"


def test_legacy_payload_without_new_keys_does_not_raise():
    """旧 payload（无 ammo / kill_cost / meta）必须仍能渲染。"""
    table = render_band_table(PAYLOAD, "贴脸", PART_NAMES)   # 原 PAYLOAD 未含新键
    assert "| 1 |" in table
    assert "—" in table


def test_fmt_money_groups_thousands():
    from src.renderers.ttk_report import _fmt_money

    assert _fmt_money(4579) == "4,579 哈夫币"
    assert _fmt_money(25381) == "25,381 哈夫币"
    assert _fmt_money(999) == "999 哈夫币"
    assert _fmt_money(None) == "—"


def test_readme_notes_price_source():
    md = render_readme(
        PAYLOAD_WITH_COST,
        SCENARIO_META,
        {"source": {"name": "dfttk-v3", "dataset_version": "x"}},
        PART_NAMES,
    )
    assert "2026-08-23" in md and "2026-09-21" in md
    assert "手工维护" in md
