"""纯 TTK 榜单与改枪指南的 Markdown 渲染层（Task #7）。

渲染层**只做格式化**：所有数值直接取自引擎输出（``tiering.to_export`` 的 payload），
禁止二次计算，保证文档与 JSON 数值一致。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

BAND_ORDER = ("贴脸", "近距", "中距", "远距")
TIER_ORDER = ("T0", "T1", "T2", "T3")

# --------------------------------------------------------------------------- #
# 产物文件命名（展示层职责：管线层从这里取名落盘，README/文档从这里取名造链接）
# --------------------------------------------------------------------------- #

#: 主榜（官方默认情景）距离榜文档的情景前缀：``主榜-贴脸.md`` …
MAIN_BAND_DOC_PREFIX = "主榜"

#: 距离榜文档所在目录（相对仓库根）
DOCS_BAND_DIR = "docs/榜单"

#: 命中分布预设 → 中文名（未知预设回退原值，不猜测）
PRESET_ZH = {"default": "实战", "center": "聚焦中心", "chest-only": "仅胸口"}


def main_band_doc_prefix() -> str:
    """主榜距离榜文档的情景前缀。"""
    return MAIN_BAND_DOC_PREFIX


def band_doc_name(prefix: str, band: str) -> str:
    """某情景某距离带的独立榜单文档文件名（同目录互链用裸名）。"""
    return f"{prefix}-{band}.md"


def band_doc_ref(prefix: str, band: str) -> str:
    """从仓库根（README）引用距离榜文档的相对路径。"""
    return f"{DOCS_BAND_DIR}/{band_doc_name(prefix, band)}"


def scenario_doc_stem(scenario_meta: Mapping[str, Any]) -> str:
    """情景产物文件名主干（不含扩展名）：``护甲5弹药5-实战``。

    内部 ``scenario_id`` 保持英文稳定不变，仅**落盘文件名**中文化。
    预设缺失或未收录时回退英文原值——文件名不猜测预设身份。
    """
    preset = scenario_meta.get("probability_preset")
    if preset is None:
        return (
            f"护甲{scenario_meta.get('armor_level')}弹药{scenario_meta.get('ammo_level')}"
            "-default"
        )
    preset = str(preset)
    return (
        f"护甲{scenario_meta.get('armor_level')}弹药{scenario_meta.get('ammo_level')}"
        f"-{PRESET_ZH.get(preset, preset)}"
    )


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
    span = f"（{window.get('from')}）" if window.get("from") else ""
    return f"- 价格数据：第三方交易行 30 日价格{span}，抓取于 {meta.get('updated_at') or '未知'}"


def loadout_text(loadout: Mapping[str, str], part_names: Mapping[str, str]) -> str:
    """把 ``{socket: item_id}`` 渲染成可读配件清单。"""
    if not loadout:
        return "官方默认"
    labels = []
    for socket_id, item_id in sorted(loadout.items(), key=lambda kv: str(kv[0])):
        name = part_names.get(str(item_id), str(item_id))
        labels.append(f"{name}")
    return " + ".join(labels)


def loadout_effect_text(effects: Sequence[Mapping[str, Any]]) -> str:
    """渲染「配装效果」摘要：最优配装相对白板的关键 TTK 属性变化。

    例：``（甲伤 32→35 · 优势射程 35→52.5 m）``；无变化时返回空串。
    TTK 差异由独立的「配装收益」列呈现，不在此重复。
    """
    if not effects:
        return ""
    chunks = [
        f"{e['label']} {e['base']:g}→{e['final']:g}{e.get('unit', '')}"
        for e in effects
        if e.get("base") is not None and e.get("final") is not None
    ]
    if not chunks:
        return ""
    return "<br><sub>配装效果：" + " · ".join(chunks) + "</sub>"


def loadout_gain_text(stock_mean_ms: Optional[float], final_mean_ms: Optional[float]) -> str:
    """渲染「配装收益」列：最优配装相对官方白板的**带内平均 TTK 缩短量**。

    正值 = 配装赚到的毫秒，括号内为相对白板的缩短百分比；白板与配装无差异
    （如官方默认即最优）时显示 ``—``，数据缺失时同样不猜测。
    """
    if stock_mean_ms is None or final_mean_ms is None:
        return "—"
    gain = stock_mean_ms - final_mean_ms
    if abs(gain) <= 1e-9:
        return "—"
    pct = gain / stock_mean_ms * 100.0
    return f"{_fmt(gain, 1, ' ms')}（{_fmt(pct, 1, '%')}）"


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
        "| # | 层级 | 武器 | 平均 TTK | 最差 TTK | 预装收益 | 期望击杀发数@0m | 弹药 | 单发价 | 击杀成本 | 射速 | 优势射程 | 起枪配置 |",
        "| :-- | :-- | :-- | --: | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |",
    ]
    for w in rows:
        band_data = w["bands"][band]
        if w.get("is_variant"):
            # 变体枪：出厂预装态成绩，配装列显示预装件
            name = f"{w['name']}<br><sub>变体 · 出厂预装态</sub>"
            loadout = f"出厂预装：{w.get('variant_item_name') or '—'}" + loadout_effect_text(
                w.get("loadout_effects") or []
            )
        else:
            name = w["name"]
            loadout = loadout_text(w.get("loadout") or {}, part_names) + loadout_effect_text(
                w.get("loadout_effects") or []
            )
        ammo = w.get("ammo") or {}
        currency = ((payload.get("ammo_price_meta") or {}).get("currency")) or "哈夫币"
        stock_mean = ((w.get("stock_bands") or {}).get(band) or {}).get("mean_ms")
        lines.append(
            "| {rank} | {tier} | {name} | {mean} | {worst} | {gain} | {shots} | {ammo} | {price} | {cost} | {rpm} | {rng} | {loadout} |".format(
                rank=band_data["rank"],
                tier=_tier_badge(band_data.get("tier", "")),
                name=name,
                mean=_fmt(band_data["mean_ms"], 1, " ms"),
                worst=_fmt(band_data["worst_ms"], 1, " ms"),
                gain=loadout_gain_text(stock_mean, band_data["mean_ms"]),
                shots=_fmt(w.get("expected_shots_0m"), 2, " 发"),
                ammo=_ammo_label(ammo),
                price=_fmt_money(ammo.get("price_avg_30d"), currency),
                cost=_fmt_money(band_data.get("kill_cost"), currency),
                rpm=_fmt(w.get("rpm"), 0),
                rng=_fmt(w.get("effective_range_m"), 1, " m"),
                loadout=loadout,
            )
        )
    return "\n".join(lines)


def render_band_top_preview(
    payload: Mapping[str, Any],
    band: str,
    part_names: Mapping[str, str],
    limit: int = 5,
) -> str:
    """README 主榜速览：单距离带前 N 名的精简表（完整列留给距离榜文档）。"""
    rows = [w for w in payload["weapons"] if band in (w.get("bands") or {})]
    rows.sort(key=lambda w: w["bands"][band]["rank"])
    rows = rows[:limit]

    currency = ((payload.get("ammo_price_meta") or {}).get("currency")) or "哈夫币"
    lines = [
        "| # | 层级 | 武器 | 平均 TTK | 击杀成本 | 起枪配置 |",
        "| :-- | :-- | :-- | --: | --: | :-- |",
    ]
    for w in rows:
        band_data = w["bands"][band]
        if w.get("is_variant"):
            name = f"{w['name']}<br><sub>变体 · 出厂预装态</sub>"
            loadout = f"出厂预装：{w.get('variant_item_name') or '—'}"
        else:
            name = w["name"]
            loadout = loadout_text(w.get("loadout") or {}, part_names)
        lines.append(
            "| {rank} | {tier} | {name} | {mean} | {cost} | {loadout} |".format(
                rank=band_data["rank"],
                tier=_tier_badge(band_data.get("tier", "")),
                name=name,
                mean=_fmt(band_data["mean_ms"], 1, " ms"),
                cost=_fmt_money(band_data.get("kill_cost"), currency),
                loadout=loadout,
            )
        )
    return "\n".join(lines)


def _band_nav_line(prefix: str, current: Optional[str] = None) -> str:
    """距离榜横向导航（同情景内互链）：其余三带链接 + 当前带加粗（不可自链）。"""
    parts = []
    for band in BAND_ORDER:
        if band == current:
            parts.append(f"**{band}**")
        else:
            parts.append(f"[{band}]({band_doc_name(prefix, band)})")
    return " · ".join(parts)


def render_band_doc(
    payload: Mapping[str, Any],
    band: str,
    scenario_meta: Mapping[str, Any],
    part_names: Mapping[str, str],
    limit: Optional[int] = 120,
    prefix: Optional[str] = None,
) -> str:
    """单个情景单个距离带的独立榜单文档（完整排名，一份距离一个文件）。

    ``prefix`` 为文档标题与互链所用的情景名（主榜用 ``主榜``，其余情景用
    ``scenario_doc_stem`` 的中文名）；缺省回落到主榜前缀。
    """
    prefix = prefix or MAIN_BAND_DOC_PREFIX
    band_def = (payload.get("band_definitions") or {}).get(band)
    if band_def is None:
        raise KeyError(f"payload 未定义距离带：{band}")
    thresholds = (payload.get("tier_thresholds_ms") or {}).get(band) or {}

    lines: List[str] = []
    lines.append(f"# {prefix} · {band}（{band_def['from_m']:g}–{band_def['to_m']:g} m）")
    lines.append("")
    lines.append(
        f"> {scenario_doc_stem(scenario_meta)}"
        f"（护甲 {scenario_meta.get('armor_level')} 套 / 弹药 {scenario_meta.get('ammo_level')} 级，"
        f"命中分布 `{scenario_meta.get('probability_preset')}`）"
    )
    lines.append(">")
    lines.append("> - **排序键**：带内平均实战 TTK（`(期望击杀发数 − 1) × 射击间隔`），"
                 "不含开镜时间与弹丸飞行时间")
    lines.append("> - **层级**：带内 TTK 分位数切分（前 15% → T0，15–40% → T1，40–70% → T2，其余 → T3）")
    if thresholds:
        lines.append(f"> - **层级阈值**：{_thresholds_text(thresholds)}")
    lines.append("")
    lines.append(render_band_table(payload, band, part_names, limit=limit))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("其他距离榜：" + _band_nav_line(prefix, current=band))
    lines.append("")
    lines.append("[← 返回 README 主榜速览](../../README.md)")
    lines.append("")
    lines.append("- 距离明细：本情景每状态的 0–80 m 每 10 m 采样 TTK 见 `data/榜单/<情景>.json` 的 "
                 "`ttk_by_distance_ms`")
    lines.append("- 开镜时间、初速、后坐/散布等维度不计入 TTK，详见 [改枪指南](../改枪指南.md)")
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
    repo_slug: Optional[str] = None,
) -> str:
    """渲染仓库首页 README：口径 → 主榜速览（每带 Top 5）→ 距离榜/情景导航 → 方法学。

    主榜完整排名按距离带拆分为 4 份独立文档（``docs/榜单/主榜-<带>.md``），
    README 只保留速览与导航，不再内嵌完整大表。``scenario_index`` 必须只传
    **实际生成了榜单文件**的情景，否则会产出死链。
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
    lines.append("回答两个问题：**在给定护甲、弹药与距离下，这把枪击杀对手需要多久（毫秒）**，"
                 "以及**这次击杀要花多少哈夫币**。")
    lines.append("")
    lines.append("| 项 | 说明 |")
    lines.append("| :-- | :-- |")
    lines.append("| 排序键 | 距离带内平均实战 TTK（`(期望击杀发数 − 1) × 射击间隔`） |")
    lines.append("| 不参与 | 开镜时间、弹丸飞行时间（初速）、换弹、命中率修正 |")
    lines.append("| 起枪状态 | 每行 = 一个起枪配置状态：本体裸枪、官方变体出厂预装态、束搜索枚举的改装状态（官方插槽规则 + 强制联动）；"
                 "仅 TTK 有差异的状态列出，全部一起排名分层 |")
    lines.append("| 预装收益 | 该距离带内**本体裸枪 → 本状态**的平均 TTK 缩短量与百分比（`—` 表示本体裸枪行） |")
    lines.append("| 距离场 | 0–80 m（官方排行口径），分 4 个距离带，每带独立成榜 |")
    lines.append("| 分层 | 带内 TTK 分位数切分 T0–T3，阈值公开 |")
    lines.append(f"| 数据版本 | `{source.get('dataset_version', '未知')}`（{source.get('name', 'dfttk-v3')}） |")
    lines.append("")

    lines.append(f"## 主榜速览 · {scenario_doc_stem(scenario_meta)}")
    lines.append("")
    lines.append(
        f"> 护甲 {scenario_meta.get('armor_level')} 套 / 弹药 {scenario_meta.get('ammo_level')} 级，"
        f"命中分布 `{scenario_meta.get('probability_preset')}`；每带只列前 5 名，"
        f"完整排名（全部起枪状态 × 预装收益 × 最差 TTK）见各距离榜。"
    )
    lines.append("")
    for band in BAND_ORDER:
        if band not in (main_payload.get("band_definitions") or {}):
            continue
        if not any(band in (w.get("bands") or {}) for w in main_payload["weapons"]):
            continue
        band_def = main_payload["band_definitions"][band]
        thresholds = (main_payload.get("tier_thresholds_ms") or {}).get(band) or {}
        lines.append(f"### {band}（{band_def['from_m']:g}–{band_def['to_m']:g} m）· [完整榜 →]({band_doc_ref(MAIN_BAND_DOC_PREFIX, band)})")
        lines.append("")
        if thresholds:
            lines.append("层级阈值：" + _thresholds_text(thresholds))
            lines.append("")
        lines.append(render_band_top_preview(main_payload, band, part_names, limit=5))
        lines.append("")

    if scenario_index:
        lines.append("## 情景索引")
        lines.append("")
        lines.append("默认收录以下实战情景（口径：不含 3 级弹组合，命中分布只用实战 `default`）；")
        lines.append("全部 21 个官方情景（含 `center` / `chest-only` 理论聚焦预设）可用 `python -m src.pipeline --all` 生成。")
        lines.append("")
        lines.append("| 情景 | 护甲 | 弹药 | 命中分布 | 榜单 |")
        lines.append("| :-- | --: | --: | :-- | :-- |")
        for item in scenario_index:
            sid = item.get("scenario_id")
            is_main = sid == main_payload["scenario_id"]
            prefix = MAIN_BAND_DOC_PREFIX if is_main else scenario_doc_stem(item)
            label = f"{scenario_doc_stem(item)}（主榜）" if is_main else scenario_doc_stem(item)
            file_cell = " · ".join(
                f"[{band}]({band_doc_ref(prefix, band)})" for band in BAND_ORDER
            )
            lines.append(
                f"| {label} | {item.get('armor_level')} "
                f"| {item.get('ammo_level')} | `{item.get('probability_preset')}` "
                f"| {file_cell} |"
            )
        lines.append("")

    lines.append("## 方法学与可信度")
    lines.append("")
    lines.append("- **期望击杀发数**：按官方伤害规则（血量 100、单弹匣不换弹、碎甲按剩余耐久比例、"
                 "距离衰减同时作用于肉伤与护甲）逐位复现官方 `candidateMetrics`，**3774 个样本零偏差**")
    lines.append("- **射击间隔**：由官方 `sdkTiming` 与射速模式决定，**291 个官方候选零偏差**")
    lines.append("- **状态枚举**：官方插槽规则 + 强制联动，束搜索枚举合法起枪状态，"
                 "仅保留 TTK 有差异的状态；已绝版的赛季限时件（哈夫克军工改件，如 S9 链锯/格斗套件）"
                 "不参与枚举，榜单为**当前赛季可达成**的配置")
    lines.append("- **距离明细**：每状态的 0–80 m 每 10 m 采样 TTK 见 `data/榜单/<情景>.json` 的 "
                 "`ttk_by_distance_ms`")
    lines.append("- **改枪指南**：开镜时间/初速/后坐等不进 TTK 的维度见 [docs/改枪指南.md](docs/改枪指南.md)")
    lines.append("- **榜单刷新**：仓库页 **Actions → CI → Run workflow** 手动触发，"
                 "在 GitHub 上同步官方数据、重算全部榜单并自动提交；本地无需跑任何重计算")
    note = _price_note(main_payload)
    if note:
        lines.append(note)
        lines.append("")
    lines.append("详细设计见 [`docs/superpowers/specs/2026-09-20-pure-ttk-redesign-design.md`]"
                 "(docs/superpowers/specs/2026-09-20-pure-ttk-redesign-design.md)，"
                 "弹药击杀成本相关规范见 [`docs/superpowers/specs/2026-09-21-ammo-kill-cost-design.md`]"
                 "(docs/superpowers/specs/2026-09-21-ammo-kill-cost-design.md)。")
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
    lines.append("榜单回答「击杀需要多久」与「这次击杀要花多少钱」。本指南说明**不影响 TTK、但影响手感与命中**的维度，")
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
