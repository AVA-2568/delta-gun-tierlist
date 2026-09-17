"""Markdown report renderer for main project README and scenario sub-documents."""

import json
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Set
from src.models import DataSourceStatus, TierEntry


def _load_caliber_map() -> Dict[str, str]:
    """Load gun caliber mappings from base_guns.json or default definitions."""
    mapping = {
        "m4a1": "5.56x45mm",
        "k416": "5.56x45mm",
        "car15": "5.56x45mm",
        "vector": "9x19mm",
        "smg45": ".45 ACP",
        "mp5": "9x19mm",
        "svd": "7.62x54mmR",
        "m14": "7.62x51mm",
        "asval": "9x39mm",
        "m7": "6.8x51mm",
        "pkp": "7.62x54mmR",
    }
    base_guns_path = "data/base_guns.json"
    if os.path.exists(base_guns_path):
        try:
            with open(base_guns_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                if isinstance(item, dict) and "id" in item and "caliber" in item:
                    mapping[item["id"]] = item["caliber"]
        except Exception:
            pass
    return mapping


_CALIBER_MAP = _load_caliber_map()


def _get_gun_caliber(entry: TierEntry) -> str:
    """Retrieve caliber for a tier entry."""
    if hasattr(entry, "caliber") and getattr(entry, "caliber"):
        return str(getattr(entry, "caliber"))
    return _CALIBER_MAP.get(entry.gun_id, entry.category)


def _get_entries_for_scenario(
    all_rankings: Dict[Any, List[TierEntry]],
    armor: int,
    ammo: int,
    distance: int,
) -> List[TierEntry]:
    """Retrieve entries for a specific armor-ammo-distance combination with key fallback."""
    candidate_keys = [
        f"{armor}-{ammo}-{distance}m",
        f"{armor}_{ammo}_{distance}m",
        f"{armor}-{ammo}-{distance}",
        f"{armor}_{ammo}_{distance}",
        (armor, ammo, distance),
        f"{armor}armor_{ammo}ammo_{distance}m",
    ]
    for k in candidate_keys:
        if k in all_rankings:
            return all_rankings[k]

    # Search through all ranking groups
    for entries in all_rankings.values():
        if entries and len(entries) > 0:
            first = entries[0]
            if (
                getattr(first, "armor_level", None) == armor
                and getattr(first, "ammo_level", None) == ammo
                and getattr(first, "distance_m", None) == distance
            ):
                return entries

    return []


def _format_tier(tier: str) -> str:
    """Highlight T0 tiers in bold."""
    if tier == "T0":
        return "**T0**"
    return tier


def _render_tier_cell(tier: str) -> str:
    """Format single tier cell in table."""
    return _format_tier(tier)


def render_main_readme(
    all_rankings: Dict[str, List[TierEntry]],
    status: DataSourceStatus,
    output_path: str = "README.md",
) -> str:
    """Render and write the main project README.md document.

    Args:
        all_rankings: Complete 9-dimension ranking dataset.
        status: DataSourceStatus indicating live/fallback health.
        output_path: Target filesystem path for README.md.

    Returns:
        str: Generated Markdown string.
    """
    # Ensure directory exists
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    # Collect tracked weapons
    unique_guns: Set[str] = set()
    gun_meta_map: Dict[str, Dict[str, Any]] = {}
    for entries in all_rankings.values():
        for e in entries:
            unique_guns.add(e.gun_id)
            if e.gun_id not in gun_meta_map:
                gun_meta_map[e.gun_id] = {
                    "name": e.gun_name,
                    "category": e.category,
                    "build_code": e.build_code,
                    "costs": {},
                }
            # Record total loadout costs by ammo level
            gun_meta_map[e.gun_id]["costs"][e.ammo_level] = e.total_loadout_cost

    total_guns_count = len(unique_guns)

    # Status Badges
    if status.fallback_tier == 0 or status.source == "zxfps_live":
        status_badge = "![数据源状态](https://img.shields.io/badge/数据源-Live%20在线实时-brightgreen?style=flat-square)"
    elif status.fallback_tier == 1 or status.source == "snapshot":
        status_badge = "![数据源状态](https://img.shields.io/badge/数据源-Snapshot%20历史快照-orange?style=flat-square)"
    else:
        status_badge = "![数据源状态](https://img.shields.io/badge/数据源-Baseline%20固化基准-red?style=flat-square)"

    encoded_time = urllib.parse.quote(status.updated_at)
    time_badge = f"![更新时间](https://img.shields.io/badge/更新时间-{encoded_time}-blue?style=flat-square)"
    guns_badge = f"![收录枪械](https://img.shields.io/badge/收录枪械-{total_guns_count}把-success?style=flat-square)"
    game_badge = "![游戏](https://img.shields.io/badge/三角洲行动-Delta%20Force-blueviolet?style=flat-square)"
    build_badge = "![CI/CD](https://img.shields.io/badge/CI%2FCD-自动化更新-informational?style=flat-square)"

    warning_banner = ""
    if status.is_fallback or status.message:
        warning_banner = f"\n> ⚠️ **数据源提示**：{status.message}（当前降级层级：Tier {status.fallback_tier} / 标识：`{status.source}`）\n"

    # Build T0 Quick Lookup Cards
    scenarios_cards_config = [
        {
            "title": "4套4弹（常规对决）",
            "subtitle": "经济局与常规对抗 | 4级防具对战4级弹药 | 平民最强收益方案",
            "armor": 4,
            "ammo": 4,
            "doc_link": "docs/tierlist/4armor_4ammo.md",
        },
        {
            "title": "4套5弹（穿甲压制）",
            "subtitle": "越级压制交锋 | 4级防具对战5级高穿弹 | 瞬间融甲统治力",
            "armor": 4,
            "ammo": 5,
            "doc_link": "docs/tierlist/4armor_5ammo.md",
        },
        {
            "title": "5套5弹（顶级交锋）",
            "subtitle": "高烈度顶级对抗 | 5级重甲对战5级高穿弹 | 高穿高射速决胜",
            "armor": 5,
            "ammo": 5,
            "doc_link": "docs/tierlist/5armor_5ammo.md",
        },
    ]

    t0_cards_sections: List[str] = []
    for sc in scenarios_cards_config:
        entries_15m = _get_entries_for_scenario(all_rankings, sc["armor"], sc["ammo"], 15)
        entries_35m = _get_entries_for_scenario(all_rankings, sc["armor"], sc["ammo"], 35)
        entries_50m = _get_entries_for_scenario(all_rankings, sc["armor"], sc["ammo"], 50)

        # Collect T0 guns across distances, or top guns if no T0
        t0_candidates: Dict[str, Dict[str, Any]] = {}
        all_candidates: Dict[str, Dict[str, Any]] = {}

        for dist, d_entries in [(15, entries_15m), (35, entries_35m), (50, entries_50m)]:
            for e in d_entries:
                gid = e.gun_id
                if gid not in all_candidates:
                    all_candidates[gid] = {
                        "entry": e,
                        "t0_dists": [],
                        "max_score": e.composite_score,
                        "distances_info": [],
                    }
                all_candidates[gid]["distances_info"].append(
                    f"{dist}m(实战TTK {e.practical_ttk_ms:.1f}ms / {e.tier})"
                )
                if e.composite_score > all_candidates[gid]["max_score"]:
                    all_candidates[gid]["max_score"] = e.composite_score
                    all_candidates[gid]["entry"] = e
                if e.tier == "T0":
                    all_candidates[gid]["t0_dists"].append(f"{dist}m")
                    t0_candidates[gid] = all_candidates[gid]

        # Determine featured weapons: T0 if available, else top 2 overall
        if t0_candidates:
            featured = sorted(
                t0_candidates.values(),
                key=lambda x: x["entry"].composite_score,
                reverse=True,
            )
        else:
            featured = sorted(
                all_candidates.values(),
                key=lambda x: x["entry"].composite_score,
                reverse=True,
            )[:2]

        card_lines: List[str] = [
            f"### 🏆 {sc['title']}",
            f"> {sc['subtitle']}",
            "",
        ]

        for item in featured:
            feat_entry = item["entry"]
            caliber = _get_gun_caliber(feat_entry)
            tag_badges = " ".join([f"`{t}`" for t in feat_entry.tags])
            dist_desc = ", ".join(item["t0_dists"]) if item["t0_dists"] else "全距离综合"

            card_lines.extend([
                f"- **{feat_entry.gun_name}** (`{caliber}` | 梯队评级: {_format_tier(feat_entry.tier)} | 优势距离: {dist_desc})",
                f"  - **起枪总成本 (裸枪+改装+60发备弹)**: **{feat_entry.total_loadout_cost:,} 哈夫币**",
                f"  - **60发备弹成本**: **{feat_entry.ammo_60_cost:,} 哈夫币** (单杀弹药消耗: {feat_entry.single_kill_cost:,} 币)",
                f"  - **综合评分**: **{feat_entry.composite_score:.2f}** | 击杀需发数 STK: **{feat_entry.stk}发**",
                f"  - **推荐实用改枪码** (游戏内导入一键复制):",
                f"    ```{feat_entry.build_code}```",
                f"  - **战术特性标签**: {tag_badges}",
                "",
            ])

        card_lines.append(f"🔗 **[查看 {sc['title']} 完整详细数据分册 →]({sc['doc_link']})**\n")
        t0_cards_sections.append("\n".join(card_lines))

    t0_cards_block = "\n".join(t0_cards_sections)

    # Build 9-Dimension Overview Matrix Table
    matrix_header = [
        "| 枪械名称 | 类别 | 4套4弹 (15m/35m/50m) | 4套5弹 (15m/35m/50m) | 5套5弹 (15m/35m/50m) | 起枪总成本 (4级/5级弹) | 实用改枪码 (点击复制) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    # Pre-fetch scenario maps
    sc_map = {}
    for armor, ammo in [(4, 4), (4, 5), (5, 5)]:
        for dist in [15, 35, 50]:
            entries = _get_entries_for_scenario(all_rankings, armor, ammo, dist)
            for e in entries:
                sc_map[(e.gun_id, armor, ammo, dist)] = e

    # Sort guns by highest composite score in 4-4-15m or alphabetical
    sorted_gun_ids = sorted(
        list(unique_guns),
        key=lambda gid: (
            -(sc_map[(gid, 4, 4, 15)].composite_score if (gid, 4, 4, 15) in sc_map else 0.0),
            gun_meta_map.get(gid, {}).get("name", gid),
        ),
    )

    matrix_rows = []
    for gid in sorted_gun_ids:
        meta = gun_meta_map.get(gid, {"name": gid, "category": "突击步枪", "build_code": "STOCK", "costs": {}})
        g_name = meta["name"]
        category = meta["category"]
        build_code = meta["build_code"]

        def get_triplet(armor: int, ammo: int) -> str:
            t15 = sc_map.get((gid, armor, ammo, 15))
            t35 = sc_map.get((gid, armor, ammo, 35))
            t50 = sc_map.get((gid, armor, ammo, 50))
            s15 = _render_tier_cell(t15.tier) if t15 else "-"
            s35 = _render_tier_cell(t35.tier) if t35 else "-"
            s50 = _render_tier_cell(t50.tier) if t50 else "-"
            return f"{s15} / {s35} / {s50}"

        c_4_4 = get_triplet(4, 4)
        c_4_5 = get_triplet(4, 5)
        c_5_5 = get_triplet(5, 5)

        cost_lv4 = meta["costs"].get(4)
        cost_lv5 = meta["costs"].get(5)
        if cost_lv4 is not None and cost_lv5 is not None:
            cost_str = f"{cost_lv4:,} / {cost_lv5:,} 币"
        elif cost_lv4 is not None:
            cost_str = f"{cost_lv4:,} 币"
        elif cost_lv5 is not None:
            cost_str = f"{cost_lv5:,} 币"
        else:
            cost_str = "-"

        code_str = f"`{build_code}`"
        matrix_rows.append(
            f"| **{g_name}** | {category} | {c_4_4} | {c_4_5} | {c_5_5} | {cost_str} | {code_str} |"
        )

    matrix_table = "\n".join(matrix_header + matrix_rows)

    readme_content = f"""# 🎯 三角洲行动枪械梯度排行榜与 60 发备弹性价比矩阵
> **Delta Force Weapon Tier List & 60-Round Tactical Economics Engine**

{status_badge} {time_badge} {guns_badge} {game_badge} {build_badge}
{warning_banner}

欢迎查阅《三角洲行动》枪械全自动综合战备排行榜。本排行榜摒弃主观口嗨与单一数值计算，基于**逐发弹药击打状态机（护甲耐久递减 + EHR 距离有效命中率修正）**与**真实起枪战备成本模型（裸枪 + 实用合理改装 + 60发备弹储备）**，全自动定时仿真计算输出。

---

## ⚡ 三大核心实战场景 T0 速查卡片

{t0_cards_block}

---

## 📊 全场景 9 维推荐天梯矩阵 (Overview Matrix)

> 注：表格中梯次格式为 `15m近距 / 35m中距 / 50m远距`。加粗 **T0** 代表该距离下的版本统治级武器。

{matrix_table}

---

## 📚 详细分册天梯索引

| 对决场景 | 目标防具 | 使用弹药 | 核心侧重点 | 完整分册文档链接 |
| :--- | :---: | :---: | :--- | :--- |
| **常规对决** | 4 级甲 | 4 级弹 | 平民搜刮与常规交火，高泛用与经济性平衡 | 👉 [4armor_4ammo.md](docs/tierlist/4armor_4ammo.md) |
| **穿甲压制** | 4 级甲 | 5 级弹 | 进阶越级压制，5级弹高穿透瞬秒4级甲 | 👉 [4armor_5ammo.md](docs/tierlist/4armor_5ammo.md) |
| **顶级交锋** | 5 级甲 | 5 级弹 | 顶级防具对碰，长TTK与破甲耐久衰减博弈 | 👉 [5armor_5ammo.md](docs/tierlist/5armor_5ammo.md) |
| **JSON 数据** | 全场景 | 4/5 级 | 机器可读规范化全量排行榜数据集 | 👉 [latest_rankings.json](data/latest_rankings.json) |

---

## 📐 算法评估模型与基准说明

### 1. 60发备弹基准起枪成本模型 (Loadout Economics)
在真实的撤离射击游戏中，起枪成本绝非仅包含裸枪交易行买入价：
$$\\text{{起枪总成本}} = \\text{{裸枪市场指导价}} + \\text{{实用改装配件造价}} + \\text{{60发备弹成本}}$$
- **60发备弹基准**：进入行动的标准起装配给（1个主弹匣30发 + 1个备用弹匣30发），避免低射速高单价弹药或高射速泼水枪的成本失真。
- **单杀弹药消耗**：$\\text{{单杀成本}} = \\text{{实战击杀发数 (STK)}} \\times \\text{{弹药单价}}$。

### 2. 逐发离散战斗仿真与实战 TTK (Practical TTK)
- **非线性穿透与耐久削减**：拒绝硬编码「总血量/单发基础伤害」除法。仿真器以单发子弹为步长推进，根据实时护甲耐久度、防具等级、弹药穿深判定首发击穿概率，动态计算减伤比率与甲耐久削减。
- **距离有效命中率修正 (EHR, Effective Hit Rate)**：
  $$\\text{{实战 TTK (ms)}} = \\frac{{\\text{{理论 TTK (ms)}}}}{{\\text{{EHR}}}}$$
  结合初速、散布与后坐稳定性随距离递减的客观物理规律，真实反映交火中的空枪惩罚。

### 3. 三维加权综合评分体系 (Composite Score)
综合评分由战力、操控、经济三轴融合而成，取值范围为 $0 \\sim 100$：
$$\\text{{综合评分}} = 50\\% \\times \\text{{战力效能分}} + 20\\% \\times \\text{{操控容错分}} + 30\\% \\times \\text{{经济性价比分}}$$
- **战力效能分 (50%)**：以实战 TTK 进行 Min-Max 逆向归一化（TTK 越短得分越高，基准保底 35 分）。
- **操控容错分 (20%)**：$0.4 \\times \\text{{后坐控制}} + 0.3 \\times \\text{{射击稳定性}} + 0.3 \\times \\min(100, \\frac{{\\text{{RPM}}}}{{10}})$。
- **经济性价比分 (30%)**：以起枪总成本进行 Min-Max 逆向归一化（战备总价越低性价比越高）。

### 4. 梯队划级标准 (Tier Definition)
- **T0 (≥ 88.0 分)**：**版本答案**。战力与性价比兼备，综合胜率统治级。
- **T1 (78.0 ~ 87.9 分)**：**强势主力**。各项指标均衡优秀，高容错主流选择。
- **T2 (65.0 ~ 77.9 分)**：**可用战备**。特定距离或受限经济条件下的平稳备选。
- **T3 (< 65.0 分)**：**不推荐**。当前环境收益率低或战术耗费与杀伤严重倒挂。
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(readme_content)

    return readme_content


def render_scenario_docs(
    all_rankings: Dict[str, List[TierEntry]],
    status: DataSourceStatus,
    docs_dir: str = "docs/tierlist",
) -> List[str]:
    """Generate the 3 dedicated scenario Markdown tier list documents.

    Files:
        - docs/tierlist/4armor_4ammo.md
        - docs/tierlist/4armor_5ammo.md
        - docs/tierlist/5armor_5ammo.md

    Args:
        all_rankings: Complete 9-dimension ranking dataset.
        status: DataSourceStatus object.
        docs_dir: Destination directory path.

    Returns:
        List[str]: Filepaths of the generated Markdown documents.
    """
    os.makedirs(docs_dir, exist_ok=True)

    scenario_configs = [
        {
            "filename": "4armor_4ammo.md",
            "armor": 4,
            "ammo": 4,
            "title": "4套4弹（常规对决）全距离枪械天梯排行榜",
            "description": "双方均配装 4 级护甲与 4 级弹药的常规平民作战环境。重点评估常规交火效率与起枪经济性。",
        },
        {
            "filename": "4armor_5ammo.md",
            "armor": 4,
            "ammo": 5,
            "title": "4套5弹（穿甲压制）全距离枪械天梯排行榜",
            "description": "自身使用 5 级高穿深弹药打击敌方 4 级防具的越级压制环境。重点评估首发破甲秒杀效率与昂贵弹药成本的平衡。",
        },
        {
            "filename": "5armor_5ammo.md",
            "armor": 5,
            "ammo": 5,
            "title": "5套5弹（顶级交锋）全距离枪械天梯排行榜",
            "description": "高级护甲对决高穿弹药的顶级对局环境。重点评估高破甲系数、耐久削减速率与高射速倾泻的极致战力。",
        },
    ]

    created_filepaths: List[str] = []

    for sc in scenario_configs:
        out_file = os.path.join(docs_dir, sc["filename"])
        armor = sc["armor"]
        ammo = sc["ammo"]

        lines = [
            f"# {sc['title']}",
            f"> {sc['description']}",
            "",
            f"- **数据源状态**: `{status.source}` (降级梯次: Tier {status.fallback_tier})",
            f"- **数据更新时间**: `{status.updated_at}`",
            "- **返回主导航**: [🏠 返回主排行榜与总览矩阵](../../README.md)",
            "",
            "---",
            "",
        ]

        # 3 Distances: 15m, 35m, 50m
        distance_sections = [
            (15, "近距离交火 (15m)", "近身贴脸遭遇战（15米以内），射速、腰射/开镜速度与近距爆发决定胜负。"),
            (35, "中距离交火 (35m)", "常规街区与走廊对决（35米区间），重点考核初速、首段衰减与连发后坐可控性。"),
            (50, "远距离交火 (50m)", "长距离点射与架枪压制（50米区间），散布惩罚激增，考量稳定度与远距离肉伤保留。"),
        ]

        for dist, dist_title, dist_desc in distance_sections:
            entries = _get_entries_for_scenario(all_rankings, armor, ammo, dist)
            lines.extend([
                f"## {dist_title}",
                f"> {dist_desc}",
                "",
                "| 排名 | 梯队 | 枪械 | 口径 | STK | 实战TTK | 60发备弹成本 | 起枪总成本 | 单杀弹药成本 | 综合评分 | 推荐改枪码 | 战术标签 |",
                "| :---: | :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :--- |",
            ])

            if not entries:
                lines.append("| - | - | 暂无数据 | - | - | - | - | - | - | - | - | - |")
            else:
                for idx, entry in enumerate(entries, start=1):
                    rank = idx
                    tier_str = _format_tier(entry.tier)
                    gun_name = f"**{entry.gun_name}**"
                    caliber = _get_gun_caliber(entry)
                    stk_str = f"{entry.stk}发"
                    ttk_str = f"{entry.practical_ttk_ms:.1f}ms"
                    ammo60_str = f"{entry.ammo_60_cost:,}"
                    total_str = f"{entry.total_loadout_cost:,}"
                    single_str = f"{entry.single_kill_cost:,}"
                    score_str = f"{entry.composite_score:.2f}"
                    code_str = f"`{entry.build_code}`"
                    tags_str = " ".join([f"`{t}`" for t in entry.tags])

                    row = f"| {rank} | {tier_str} | {gun_name} | {caliber} | {stk_str} | {ttk_str} | {ammo60_str} | {total_str} | {single_str} | {score_str} | {code_str} | {tags_str} |"
                    lines.append(row)

            lines.extend(["", "---", ""])

        doc_content = "\n".join(lines)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(doc_content)

        created_filepaths.append(out_file)

    return created_filepaths
