"""纯 TTK 榜单与改枪指南的 Markdown 渲染层（Task #7）。

渲染层**只做格式化**：所有数值直接取自引擎输出（``tiering.to_export`` 的 payload），
禁止二次计算，保证文档与 JSON 数值一致。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

BAND_ORDER = ("贴脸", "近距", "中距", "远距")
TIER_ORDER = ("T0", "T1", "T2", "T3")


def _fmt(value: Any, digits: int = 1, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_money(value: Any, currency: str = "哈夫币") -> str:
    """整数金额千分位格式化；``None`` 渲染为 ``—``（缺价不猜测）。"""
    if value is None:
        return "—"
    try:
        return f"{int(value):,} {currency}"
    except (TypeError, ValueError):
        return "—"


def _ammo_label(ammo: Mapping[str, Any]) -> str:
    """弹药展示名：``口径 + 型号``；口径为空时只输出型号。"""
    caliber = str(ammo.get("caliber") or "").strip()
    name = str(ammo.get("name") or "").strip()
    return f"{caliber} {name}".strip() or "—"


def _price_note(payload: Mapping[str, Any]) -> Optional[str]:
    """价格数据说明行；未配置价格表时返回提示缺失的文案。"""
    meta = payload.get("ammo_price_meta")
    if not meta:
        return None
    if not meta.get("available"):
        return "- 价格数据：未配置（data/reference/ammo_prices.json 缺失或为空），成本列显示 —"
    window = meta.get("window") or {}
    span = f"（{window.get('from')} ~ {window.get('to')}）" if window.get("from") else ""
    return f"- 价格数据：手工维护 30 天均价{span}，截至 {meta.get('updated_at') or '未知'}"


def loadout_text(loadout: Mapping[str, str], part_names: Mapping[str, str]) -> str:
    """把 ``{socket: item_id}`` 渲染成可读配件清单。"""
    if not loadout:
        return "官方默认"
    labels = []
    for socket_id, item_id in sorted(loadout.items(), key=lambda kv: str(kv[0])):
        name = part_names.get(str(item_id), str(item_id))
        labels.append(f"{name}")
    return " + ".join(labels)


def _tier_badge(tier: str) -> str:
    return {"T0": "**T0**", "T1": "T1", "T2": "T2", "T3": "T3"}.get(tier, tier or "—")


def _thresholds_text(thresholds: Mapping[str, float]) -> str:
    """层级阈值说明：T0–T2 为分位切点，T3 为其余。"""
    parts = [f"{tier} ≤ {_fmt(thresholds.get(tier), 1, ' ms')}" for tier in TIER_ORDER if tier in thresholds]
    parts.append("T3：其余")
    return " / ".join(parts)


def render_band_table(
    payload: Mapping[str, Any],
    band: str,
    part_names: Mapping[str, str],
    limit: Optional[int] = None,
) -> str:
    """渲染单个距离带的榜单表。"""
    rows = [
        w for w in payload["weapons"]
        if band in (w.get("bands") or {})
    ]
    rows.sort(key=lambda w: w["bands"][band]["rank"])
    if limit:
        rows = rows[:limit]

    lines = [
        "| # | 层级 | 武器 | 平均 TTK | 最差 TTK | 期望击杀发数@0m | 弹药 | 单发价 | 击杀成本 | 射速 | 优势射程 | 最优配装 |",
        "| :-- | :-- | :-- | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |",
    ]
    for w in rows:
        band_data = w["bands"][band]
        name = w["name"]
        equivalents = w.get("equivalent_variants") or []
        if equivalents:
            name = f"{name}<br><sub>变体同配置：{'、'.join(equivalents)}</sub>"
        ammo = w.get("ammo") or {}
        currency = ((payload.get("ammo_price_meta") or {}).get("currency")) or "哈夫币"
        lines.append(
            "| {rank} | {tier} | {name} | {mean} | {worst} | {shots} | {ammo} | {price} | {cost} | {rpm} | {rng} | {loadout} |".format(
                rank=band_data["rank"],
                tier=_tier_badge(band_data.get("tier", "")),
                name=name,
                mean=_fmt(band_data["mean_ms"], 1, " ms"),
                worst=_fmt(band_data["worst_ms"], 1, " ms"),
                shots=_fmt(w.get("expected_shots_0m"), 2, " 发"),
                ammo=_ammo_label(ammo),
                price=_fmt_money(ammo.get("price_avg_30d"), currency),
                cost=_fmt_money(band_data.get("kill_cost"), currency),
                rpm=_fmt(w.get("rpm"), 0),
                rng=_fmt(w.get("effective_range_m"), 1, " m"),
                loadout=loadout_text(w.get("loadout") or {}, part_names),
            )
        )
    return "\n".join(lines)


def render_scenario_markdown(
    payload: Mapping[str, Any],
    scenario_meta: Mapping[str, Any],
    part_names: Mapping[str, str],
    limit_per_band: Optional[int] = 40,
) -> str:
    """渲染单个情景的完整榜单文档。"""
    scenario_id = payload["scenario_id"]
    thresholds = payload.get("tier_thresholds_ms") or {}
    bands = payload.get("band_definitions") or {}

    lines: List[str] = []
    lines.append(f"# 纯 TTK 榜单 · {scenario_meta.get('label', scenario_id)}")
    lines.append("")
    lines.append(f"- **情景 ID**：`{scenario_id}`")
    if scenario_meta:
        lines.append(
            f"- **护甲/弹药**：{scenario_meta.get('armor_level')} 套 · {scenario_meta.get('ammo_level')} 弹"
            f"（头盔耐久 {scenario_meta.get('helmet_durability')} / 背心耐久 {scenario_meta.get('armor_durability')}）"
        )
        preset = scenario_meta.get("probability_preset")
        if preset:
            lines.append(f"- **命中分布预设**：`{preset}`")
    lines.append("- **排序键**：距离带内平均实战 TTK（升序，越小越强）")
    lines.append("- **稳健性列**：距离带内最差 TTK")
    lines.append("- **TTK 定义**：`(期望击杀发数 − 1) × 射击间隔`，不含开镜时间与弹丸飞行时间")
    lines.append("")
    lines.append("> 层级由该情景该距离带内全部武器的 TTK 分布分位数切分"
                 "（前 15% → T0，15–40% → T1，40–70% → T2，其余 → T3），阈值见下方表格。")
    lines.append("")

    for band in BAND_ORDER:
        if band not in bands:
            continue
        # 该带没有任何武器成绩时不渲染（避免空表）
        if not any(band in (w.get("bands") or {}) for w in payload["weapons"]):
            continue
        lo = bands[band]["from_m"]
        hi = bands[band]["to_m"]
        lines.append(f"## {band}（{lo:g}–{hi:g} m）")
        lines.append("")
        band_thresholds = thresholds.get(band) or {}
        if band_thresholds:
            lines.append("层级阈值：" + _thresholds_text(band_thresholds))
            lines.append("")
        lines.append(render_band_table(payload, band, part_names, limit=limit_per_band))
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 数据说明")
    lines.append("")
    lines.append("- 期望击杀发数与射击间隔均已逐位复现官方数据集（3774 / 291 个官方样本，零偏差）")
    lines.append("- 距离场锁定 0–80m（官方排行 `distanceRange`），不做外推")
    lines.append("- 开镜时间、初速、后坐/散布等维度不计入 TTK，详见 `docs/gunsmith-guide.md`")
    note = _price_note(payload)
    if note:
        lines.append(note)
    return "\n".join(lines)


def render_readme(
    main_payload: Mapping[str, Any],
    scenario_meta: Mapping[str, Any],
    provenance: Mapping[str, Any],
    part_names: Mapping[str, str],
    scenario_index: Optional[Sequence[Mapping[str, Any]]] = None,
    limit_per_band: Optional[int] = 20,
    repo_slug: Optional[str] = None,
) -> str:
    """渲染仓库首页 README（主榜 = 官方默认情景 × 4 距离带）。

    ``scenario_index`` 必须只传**实际生成了榜单文件**的情景，否则会产出死链。
    """
    source = provenance.get("source") or {}
    lines: List[str] = []
    lines.append("# 三角洲行动 · 纯 TTK 枪械强度榜")
    if repo_slug:
        lines.insert(
            1,
            f"[![CI](https://github.com/{repo_slug}/actions/workflows/update.yml/badge.svg)]"
            f"(https://github.com/{repo_slug}/actions/workflows/update.yml)",
        )
        lines.insert(2, "")
    lines.append("")
    lines.append("只回答一个问题：**在给定护甲、弹药与距离下，这把枪击杀对手需要多久（毫秒）**。")
    lines.append("")
    lines.append("| 项 | 说明 |")
    lines.append("| :-- | :-- |")
    lines.append("| 排序键 | 距离带内平均实战 TTK（`(期望击杀发数 − 1) × 射击间隔`） |")
    lines.append("| 不参与 | 开镜时间、弹丸飞行时间（初速）、换弹、命中率修正 |")
    lines.append("| 配装 | 官方插槽规则下的**最优合法配装**，非人工预设 |")
    lines.append("| 距离场 | 0–80 m（官方排行口径），分 4 个距离带 |")
    lines.append("| 分层 | 带内 TTK 分位数切分 T0–T3，阈值公开 |")
    lines.append(f"| 数据版本 | `{source.get('dataset_version', '未知')}`（{source.get('name', 'dfttk-v3')}） |")
    lines.append("")
    lines.append(f"## 主榜 · {scenario_meta.get('label', main_payload['scenario_id'])}")
    lines.append("")
    lines.append(
        f"> 护甲 {scenario_meta.get('armor_level')} 套 / 弹药 {scenario_meta.get('ammo_level')} 级，"
        f"命中分布 `{scenario_meta.get('probability_preset')}`"
    )
    lines.append("")
    for band in BAND_ORDER:
        if band not in (main_payload.get("band_definitions") or {}):
            continue
        band_def = main_payload["band_definitions"][band]
        thresholds = (main_payload.get("tier_thresholds_ms") or {}).get(band) or {}
        lines.append(f"### {band}（{band_def['from_m']:g}–{band_def['to_m']:g} m）")
        lines.append("")
        if thresholds:
            lines.append("层级阈值：" + _thresholds_text(thresholds))
            lines.append("")
        lines.append(render_band_table(main_payload, band, part_names, limit=limit_per_band))
        lines.append("")

    if scenario_index:
        lines.append("## 情景索引")
        lines.append("")
        lines.append("默认收录以下实战情景（口径：不含 3 级弹组合，命中分布只用实战 `default`）；")
        lines.append("全部 21 个官方情景（含 `center` / `chest-only` 理论聚焦预设）可用 `python -m src.pipeline --all` 生成。")
        lines.append("")
        lines.append("| 情景 | 护甲 | 弹药 | 命中分布 | 文件 |")
        lines.append("| :-- | --: | --: | :-- | :-- |")
        for item in scenario_index:
            sid = item.get("scenario_id")
            label = f"[{item.get('label', sid)}](docs/tierlist/{sid}.md)"
            if sid == main_payload["scenario_id"]:
                label += "（主榜）"
            lines.append(
                f"| {label} | {item.get('armor_level')} "
                f"| {item.get('ammo_level')} | `{item.get('probability_preset')}` "
                f"| `docs/tierlist/{sid}.md` |"
            )
        lines.append("")

    lines.append("## 方法学与可信度")
    lines.append("")
    lines.append("- **期望击杀发数**：按官方伤害规则（血量 100、单弹匣不换弹、碎甲按剩余耐久比例、"
                 "距离衰减同时作用于肉伤与护甲）逐位复现官方 `candidateMetrics`，**3774 个样本零偏差**")
    lines.append("- **射击间隔**：由官方 `sdkTiming` 与射速模式决定，**291 个官方候选零偏差**")
    lines.append("- **配装搜索**：官方插槽规则 + 强制联动，精校交由玩家自行调校（不影响 TTK）")
    lines.append("- **改枪指南**：开镜时间/初速/后坐等不进 TTK 的维度见 [docs/gunsmith-guide.md](docs/gunsmith-guide.md)")
    note = _price_note(main_payload)
    if note:
        lines.append(note)
        lines.append("")
    lines.append("详细设计见 [`docs/superpowers/specs/2026-09-20-pure-ttk-redesign-design.md`]"
                 "(docs/superpowers/specs/2026-09-20-pure-ttk-redesign-design.md)。")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 改枪指南
# --------------------------------------------------------------------------- #
HANDLING_CURVE_ID = "authoring:mechanism:handlingDefault:0:sol"

# 精校作用目标 → 该维度对玩家的实际含义（用于指南说明，不含 TTK）
TUNE_TARGET_MEANING = {
    "GAiming_ADSTime": ("开镜时间", "举枪速度，影响交战时先手的快慢"),
    "GGunkickRandom": ("枪口随机抖动", "连发时枪口的随机跳动，影响弹着散布"),
    "GGunkickSpring": ("枪口回弹", "后坐后的复位速度，影响控枪节奏"),
    "GRecoil_V": ("垂直后坐", "枪口上抬幅度"),
    "GRecoil_H": ("水平后坐", "枪口左右漂移幅度"),
    "GBreathScale": ("呼吸晃动", "据枪时准星的呼吸漂移"),
    "AimMoveGunSway": ("移动据枪晃动", "移动中开镜的准星稳定性"),
    "GBullet_Velocity": ("枪口初速", "弹丸飞行速度，影响提前量与远距命中"),
    "GMovement_ADSSpeed": ("开镜移速", "开镜状态下的移动速度"),
    "ScopeCameraTuneDistance": ("镜距", "瞄准镜的出瞳距离"),
    "ScopeZoomTuneRate": ("缩放倍率", "瞄准镜倍率微调"),
    "ParallelBulletAimOffsetCm": ("并行弹道偏移", "多管/并行枪管的弹着偏移"),
}


def render_gunsmith_guide(
    game_data: Any,
    provenance: Mapping[str, Any],
    panel_values: Sequence[int] = (35, 40, 45, 50, 55, 58, 60, 65, 70, 75, 80, 90, 100),
) -> str:
    """从官方机制曲线与配件精校定义生成改枪指南。"""
    source = provenance.get("source") or {}
    lines: List[str] = []
    lines.append("# 改枪指南（不进 TTK 的维度）")
    lines.append("")
    lines.append("榜单只回答「击杀需要多久」。本指南说明**不影响 TTK、但影响手感与命中**的维度，")
    lines.append("供玩家按自己的作战习惯权衡。")
    lines.append("")
    lines.append("## 1. 开镜时间 ↔ 操控速度")
    lines.append("")
    lines.append("面板「操控速度」经官方机制曲线直接映射为开镜时间；配件再以乘性效果叠加。")
    lines.append("")
    lines.append("| 操控速度 | 开镜时间 |")
    lines.append("| --: | --: |")
    curve = game_data.curves.get(HANDLING_CURVE_ID)
    if curve is not None:
        for panel in panel_values:
            try:
                ms = curve.evaluate(float(panel)) * 1000.0
            except Exception:
                continue
            lines.append(f"| {panel} | {ms:.0f} ms |")
    lines.append("")
    lines.append("> 实测极端改装可将开镜时间压到约 125 ms（多层乘性效果叠加），"
                 "代价是据枪稳定性大幅下降。由于开镜不计入 TTK，本榜不为该取向背书。")
    lines.append("")

    lines.append("## 2. 精校维度总览")
    lines.append("")
    lines.append("官方精校共 12 个作用目标。**没有任何一个改变期望击杀发数或射击间隔**，")
    lines.append("因此精校不影响 TTK 排名——这是把它交给玩家自行调校的原因。")
    lines.append("")
    lines.append("| 精校作用目标 | 含义 | 影响 |")
    lines.append("| :-- | :-- | :-- |")
    tally = _tune_target_tally(game_data)
    for target, count in tally:
        name, meaning = TUNE_TARGET_MEANING.get(target, (target, "—"))
        lines.append(f"| `{target}` | {name}：{meaning} | {count} 处 |")
    lines.append("")
    lines.append("## 3. 配件层面确实影响 TTK 的维度")
    lines.append("")
    lines.append("配件（而非精校）可通过以下规则目标改变 TTK：")
    lines.append("")
    lines.append("| 目标 | 含义 | 对 TTK 的作用 |")
    lines.append("| :-- | :-- | :-- |")
    lines.append("| `WeaponMainAttribute.MainAttrValues.2` | 优势射程 | 缩放伤害衰减分段 → 改变期望击杀发数 |")
    lines.append("| `GRateOfFire` / `FireRateMode` | 射速 | 改变射击间隔 |")
    lines.append("| `BulletFlyingId` | 弹道档案 | 改变初速与有效射程基准 |")
    lines.append("| `AttackerValueId.DefaultDamageId` | 伤害档案 | 整体替换基础伤害/甲伤/部位倍率 |")
    lines.append("| `ProjectileNumPerShot` | 弹丸数 | 改变单发伤害 |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"数据版本：`{source.get('dataset_version', '未知')}`"
                 f"（{source.get('name', 'dfttk-v3')}，非官方 API，详见 `data/game/provenance.json`）")
    return "\n".join(lines)


def _tune_target_tally(game_data: Any) -> List[tuple]:
    """聚合全部配件精校函数的作用目标频次。"""
    from collections import Counter

    counter: Counter = Counter()
    for part in (game_data.parts or {}).values():
        for tune in part.get("tunes") or []:
            for func in tune.get("functions") or []:
                target = func.get("target")
                if target:
                    counter[target] += 1
    return counter.most_common()
