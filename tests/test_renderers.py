"""渲染层测试：只格式化、不出数值。"""

import pytest

from src.renderers.ttk_report import (
    band_doc_name,
    band_doc_ref,
    loadout_text,
    main_band_doc_prefix,
    render_band_doc,
    render_band_table,
    render_band_top_preview,
    render_gunsmith_guide,
    render_readme,
    scenario_doc_stem,
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


def test_readme_is_slim_overview_with_band_nav():
    md = render_readme(
        PAYLOAD,
        SCENARIO_META,
        {"source": {"name": "dfttk-v3", "dataset_version": "20260911-044903.3"}},
        PART_NAMES,
        scenario_index=[SCENARIO_META],
    )
    assert "# 三角洲行动 · 纯 TTK 枪械强度榜" in md
    assert "20260911-044903.3" in md
    # 主榜速览：每带 Top 5 精简表 + 完整榜跳转（README 在仓库根，链接须带 docs/榜单/ 前缀）
    assert "### 贴脸（0–15 m）· [完整榜 →](docs/榜单/主榜-贴脸.md)" in md
    assert "| # | 层级 | 武器 | 平均 TTK | 击杀成本 | 裸枪价格 | 裸枪+180发备弹 | 起枪配置 |" in md
    # 完整榜的宽表列不得回流 README
    assert "| 最差 TTK |" not in md
    # 情景索引：主榜行指向 4 份距离榜，不再有旧英文路径
    assert "[贴脸](docs/榜单/主榜-贴脸.md) · [近距](docs/榜单/主榜-近距.md) · [中距](docs/榜单/主榜-中距.md) · [远距](docs/榜单/主榜-远距.md)" in md
    assert "docs/tierlist/" not in md


def test_readme_scenario_index_all_bands_for_every_scenario():
    """情景索引：所有情景（含非主榜）都列出 4 份距离榜链接。"""
    other = {
        "scenario_id": "armor-4-ammo-4-default",
        "label": "4套 · 4弹 · 实战概率",
        "armor_level": 4,
        "ammo_level": 4,
        "probability_preset": "default",
    }
    md = render_readme(
        PAYLOAD,
        SCENARIO_META,
        {"source": {"name": "dfttk-v3", "dataset_version": "x"}},
        PART_NAMES,
        scenario_index=[SCENARIO_META, other],
    )
    assert "[贴脸](docs/榜单/护甲4弹药4-实战-贴脸.md) · [近距](docs/榜单/护甲4弹药4-实战-近距.md) · [中距](docs/榜单/护甲4弹药4-实战-中距.md) · [远距](docs/榜单/护甲4弹药4-实战-远距.md)" in md
    assert "护甲4弹药4-实战（主榜）" not in md  # 主榜标记只给主榜情景
    assert "`docs/榜单/护甲4弹药4-实战.json`" not in md  # 索引里只链文档，不链 JSON


def test_band_doc_name_and_ref():
    prefix = main_band_doc_prefix()
    assert prefix == "主榜"
    assert band_doc_name(prefix, "贴脸") == "主榜-贴脸.md"
    assert band_doc_ref(prefix, "贴脸") == "docs/榜单/主榜-贴脸.md"
    assert band_doc_name("护甲4弹药4-实战", "远距") == "护甲4弹药4-实战-远距.md"
    assert band_doc_ref("护甲4弹药4-实战", "远距") == "docs/榜单/护甲4弹药4-实战-远距.md"


def test_scenario_doc_stem_naming():
    assert scenario_doc_stem(
        {"armor_level": 5, "ammo_level": 5, "probability_preset": "default"}
    ) == "护甲5弹药5-实战"
    assert scenario_doc_stem(
        {"armor_level": "5", "ammo_level": "5", "probability_preset": "center"}
    ) == "护甲5弹药5-聚焦中心"
    assert scenario_doc_stem(
        {"armor_level": 6, "ammo_level": 5, "probability_preset": "chest-only"}
    ) == "护甲6弹药5-仅胸口"
    # 未知预设回退原值，不猜测
    assert scenario_doc_stem({"armor_level": 4, "ammo_level": 3}) == "护甲4弹药3-default"


def test_band_top_preview_limits_rows():
    table = render_band_top_preview(PAYLOAD, "贴脸", PART_NAMES, limit=1)
    lines = table.splitlines()
    assert lines[0] == "| # | 层级 | 武器 | 平均 TTK | 击杀成本 | 裸枪价格 | 裸枪+180发备弹 | 起枪配置 |"
    assert len(lines) == 3
    assert lines[2].startswith("| 1 | **T0** | M4A1 |")


def test_band_doc_renders_full_list_and_nav():
    md = render_band_doc(PAYLOAD, "贴脸", SCENARIO_META, PART_NAMES)
    assert "# 主榜 · 贴脸（0–15 m）" in md
    assert "armor-5-ammo-5-default" not in md  # 面向读者的文档不暴露内部情景 ID
    assert "T0 ≤ 320.0 ms" in md
    # 完整榜（非速览）表格
    assert "| 最差 TTK |" in md
    assert "| 2 | T1 | AKM |" in md
    # 导航：其余三带可点，当前带加粗不可自链
    assert "**贴脸**" in md
    assert "[贴脸](主榜-贴脸.md)" not in md
    assert "[近距](主榜-近距.md)" in md and "[远距](主榜-远距.md)" in md
    assert "[← 返回 README 主榜速览](../../README.md)" in md
    assert "[改枪指南](../改枪指南.md)" in md


def test_band_doc_rejects_unknown_band():
    import pytest

    with pytest.raises(KeyError):
        render_band_doc(PAYLOAD, "不存在", SCENARIO_META, PART_NAMES)


def test_band_doc_supports_scenario_prefix():
    """非主榜情景的距离榜：标题/导航用情景中文名前缀。"""
    other = {"scenario_id": "armor-4-ammo-4-default", "armor_level": 4,
             "ammo_level": 4, "probability_preset": "default"}
    md = render_band_doc(PAYLOAD, "贴脸", other, PART_NAMES, prefix="护甲4弹药4-实战")
    assert "# 护甲4弹药4-实战 · 贴脸（0–15 m）" in md
    assert "[近距](护甲4弹药4-实战-近距.md)" in md
    assert "[贴脸](护甲4弹药4-实战-贴脸.md)" not in md
    assert "**贴脸**" in md
    assert "armor-4-ammo-4-default" not in md  # 不暴露内部情景 ID


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
        "window": {"from": "2026-09-22", "to": "2026-09-22", "days": 1},
        "updated_at": "2026-09-22",
        "available": True,
    },
    "weapons": [
        {
            **PAYLOAD["weapons"][0],
            "ammo": {"ammo_item_id": "37260500001", "name": "AP SX",
                     "caliber": "4.6x30mm", "price_daily": 4579},
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


def test_band_table_has_gun_price_columns():
    """裸枪价格 / 裸枪+180发备弹 两列紧跟「击杀成本」之后。"""
    table = render_band_table(PAYLOAD_WITH_COST, "贴脸", PART_NAMES)
    header = table.splitlines()[0]
    assert "裸枪价格" in header
    assert "裸枪+180发备弹" in header
    assert header.index("击杀成本") < header.index("裸枪价格") < header.index("裸枪+180发备弹") < header.index("射速")


def test_band_table_renders_gun_prices():
    payload = {
        **PAYLOAD_WITH_COST,
        "weapon_price_meta": {
            "currency": "哈夫币",
            "window": {"from": "2026-09-22", "to": "2026-09-22", "days": 1},
            "updated_at": "2026-09-22",
            "available": True,
            "spare_ammo_rounds": 180,
        },
        "weapons": [
            {**PAYLOAD_WITH_COST["weapons"][0],
             "gun_price_daily": 87591,
             "full_price_180rd": 87591 + 180 * 4579},
        ],
    }
    table = render_band_table(payload, "贴脸", PART_NAMES)
    assert "87,591 哈夫币" in table
    assert f"{87591 + 180 * 4579:,} 哈夫币" in table
    # README 速览同列
    preview = render_band_top_preview(payload, "贴脸", PART_NAMES)
    assert "87,591 哈夫币" in preview
    assert f"{87591 + 180 * 4579:,} 哈夫币" in preview


def test_variant_row_shows_base_name_not_variant_identity():
    """官方预装态行：武器列显示本体名（变体 = 本体 + 预装件，不是独立的枪）。"""
    payload = {
        **PAYLOAD_WITH_COST,
        "weapon_price_meta": {"available": True, "spare_ammo_rounds": 180,
                              "currency": "哈夫币", "window": {}, "updated_at": "2026-09-22"},
        "weapons": [
            {**PAYLOAD_WITH_COST["weapons"][0],
             "name": "M4A1-AR特勤一体消音组合",   # 变体 display_name（payload 保留官方身份）
             "base_name": "M4A1",
             "is_variant": True,
             "variant_item_name": "AR特勤一体消音组合",
             "gun_price_daily": 87591,
             "full_price_180rd": 87591 + 180 * 4579},
        ],
    }
    table = render_band_table(payload, "贴脸", PART_NAMES)
    assert "| 1 | **T0** | M4A1 |" in table          # 武器列 = 本体名
    assert "M4A1-AR特勤一体消音组合" not in table   # 变体枪名不得作为武器身份出现
    assert "变体 · 出厂预装态" not in table          # 旧「变体枪」副标签移除
    assert "出厂预装：AR特勤一体消音组合" in table   # 预装来源在配置列标注
    preview = render_band_top_preview(payload, "贴脸", PART_NAMES)
    assert "| 1 | **T0** | M4A1 |" in preview
    assert "出厂预装：AR特勤一体消音组合" in preview


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
                      "price_daily": None},
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
                      "price_daily": 1000},
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
    assert "2026-09-22" in md
    assert "第三方交易行当日价" in md
    assert "每日自动抓取维护" in md


def test_readme_notes_weapon_price_source_and_cost_rule():
    """README 必须说明枪价口径：本体裸枪当日价、配件价不计入、起枪成本公式。"""
    payload = {
        **PAYLOAD_WITH_COST,
        "weapon_price_meta": {
            "currency": "哈夫币",
            "window": {"from": "2026-09-22", "to": "2026-09-22", "days": 1},
            "updated_at": "2026-09-22",
            "available": True,
            "spare_ammo_rounds": 180,
        },
    }
    md = render_readme(
        payload,
        SCENARIO_META,
        {"source": {"name": "dfttk-v3", "dataset_version": "x"}},
        PART_NAMES,
    )
    assert "枪械价格" in md
    assert "本体裸枪当日价" in md
    assert "配件价不计入" in md
    assert "| 起枪成本 |" in md
    assert "回答三个问题" in md
