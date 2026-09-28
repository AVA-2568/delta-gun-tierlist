"""纯 TTK 分层与距离带聚合（Task #6）。

主排序键：**距离带内加权实战 TTK**（带内逐米 TTK 的算术平均，毫秒，升序）。
稳健性列：**带内最差 TTK**（带内最大毫秒值）。

分层规则：以该情景该距离带内所有枪的 TTK 分布**分位数**切分 T0–T3，
阈值随情景公布（写入输出 JSON），保证「层级是相对强度」且可复算。

    排序升序后，前 15% → T0，15%–40% → T1，40%–70% → T2，其余 → T3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

TIER_QUANTILES: tuple = (0.15, 0.40, 0.70)
TIER_NAMES: tuple = ("T0", "T1", "T2", "T3")
BAND_NAMES: tuple = ("贴脸", "近距", "中距", "远距")

#: 起枪备弹数：裸枪 + N 发所配弹药的预估口径（2026-09-22 与需求方确认）
SPARE_AMMO_ROUNDS = 180


@dataclass
class BandResult:
    """一个距离带内该枪的聚合结果。"""

    band: str
    mean_ms: float
    worst_ms: float
    best_ms: float
    rank: int = 0
    tier: str = ""
    mean_expected_shots: float = 0.0
    kill_cost: Optional[int] = None


@dataclass
class GunRanking:
    """一个配置状态在一个情景下的完整成绩。

    ``entry_kind`` 区分三种单状态行：

    - ``"base"``：本体裸枪（官方默认配装）；
    - ``"variant"``：本体+官方预装件（官方变体出厂态，预装件生效、无其他改装）；
    - ``"single_part"``：本体裸枪 + 单件装配（仅该件替换默认件，不做组合）。

    每行只代表一个配置状态，全部参与排名与分层。变体不是独立的枪——
    只是本体预装了官方改件，故 ``gun_price_daily`` 与本体一致。
    """

    profile_key: str
    weapon_id: str
    display_name: str
    base_name: str
    category: str
    is_variant: bool
    variant_item_name: Optional[str]
    loadout: Dict[str, str]
    tuning: Dict[str, Dict[str, float]]
    entry_kind: str = "base"
    single_part_item_id: Optional[str] = None
    bands: Dict[str, BandResult] = field(default_factory=dict)
    overall_mean_ms: float = 0.0
    expected_shots_0m: float = 0.0
    rpm: float = 0.0
    ads_ms_reference: float = 0.0
    muzzle_velocity_mps: float = 0.0
    effective_range_m: float = 0.0
    ammo_item_id: str = ""
    ammo_name: str = ""
    ammo_caliber: str = ""
    ammo_price_daily: Optional[int] = None
    #: 本体裸枪交易行当日价（变体/改装状态与本体同价，配件价不计入）
    gun_price_daily: Optional[int] = None
    #: 起枪预估价：裸枪价 + N 发所配弹药（缺任一价则为 None）
    full_price_180rd: Optional[int] = None
    #: 相对本体裸枪的关键 TTK 属性变化（伤害档案替换、射速、优势射程等）
    loadout_effects: List[Dict[str, Any]] = field(default_factory=list)
    #: 本体裸枪（无改装）在各距离带的 TTK 聚合，作为本行收益的参照
    stock_bands: Dict[str, Dict[str, float]] = field(default_factory=dict)
    #: 本状态在整数采样距离（每 10 m）下的 TTK（毫秒）
    ttk_by_distance_ms: Dict[str, float] = field(default_factory=dict)


#: 参与「配装效果摘要」的状态属性：key → (展示名, 小数位, 单位)
EFFECT_SPECS: tuple = (
    ("base_damage", "肉伤", 0, ""),
    ("base_armor_damage", "甲伤", 0, ""),
    ("rpm", "射速", 0, ""),
    ("effective_range_m", "优势射程", 1, " m"),
    ("projectile_count", "每发弹丸", 0, ""),
)


def summarize_loadout_effects(base_state: Any, final_state: Any) -> List[Dict[str, Any]]:
    """对比白板状态与配装后状态，列出有变化的关键 TTK 属性。

    只输出真实发生变化的维度（如 K437 长矛手长枪管替换伤害档案、
    M249 链锯套件改射速），渲染层直接格式化，禁止二次计算。
    """
    effects: List[Dict[str, Any]] = []
    for key, label, digits, unit in EFFECT_SPECS:
        base = float(getattr(base_state, key, 0.0) or 0.0)
        final = float(getattr(final_state, key, 0.0) or 0.0)
        if abs(final - base) > 1e-9:
            effects.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "base": round(base, digits),
                    "final": round(final, digits),
                }
            )
    return effects


def _effective_loadout(loadout: Mapping[str, str], weapon: Mapping[str, Any]) -> Dict[str, str]:
    """只保留**玩家需要改装**的件（与官方默认件相同的选择不列出）。

    归一化后的配件表会保留原厂内部件（``selectable=false``，如原厂枪管/弹匣内衬），
    求解器可能选中它们——它们不是玩家要装的配件，列出来只会干扰阅读。
    """
    defaults = {str(k): str(v) for k, v in (weapon.get("default_items") or {}).items()}
    return {
        str(socket_id): str(item_id)
        for socket_id, item_id in loadout.items()
        if defaults.get(str(socket_id)) != str(item_id)
    }


def compute_kill_cost(
    mean_expected_shots: Optional[float],
    price_per_round: Optional[int],
) -> Optional[int]:
    """单次击杀的弹药成本（哈夫币）：带内平均期望发数 × 单发均价。

    **禁用内建 ``round()``**：Python 采用银行家舍入（``round(2.5) == 2``），
    会让成本列出现反直觉数值，故统一用 ``int(x + 0.5)``。

    任一输入为 ``None``（缺价）时返回 ``None``——不猜测、不兜底。
    """
    if mean_expected_shots is None or price_per_round is None:
        return None
    return int(mean_expected_shots * price_per_round + 0.5)


def compute_full_price(
    gun_price: Optional[int],
    ammo_price_per_round: Optional[int],
    rounds: int = SPARE_AMMO_ROUNDS,
) -> Optional[int]:
    """起枪预估价（哈夫币）：本体裸枪价 + N 发所配弹药。

    口径（2026-09-22 与需求方确认）：

    - **裸枪价按本体计**——变体/改装只是本体多装了配件（配件会改伤害/射速，
      但那些差异体现在各行的 TTK 与击杀成本里），配件价不计入起枪价；
    - 弹药单价用**该行实际所配弹药**的单发价，而非全枪统一价；
    - 整数运算无舍入歧义，任一输入为 ``None``（缺价）时返回 ``None``——不猜测、不兜底。
    """
    if gun_price is None or ammo_price_per_round is None:
        return None
    return gun_price + rounds * ammo_price_per_round


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """线性插值分位数（与 numpy.percentile 默认口径一致）。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def assign_tiers(
    rankings: List[GunRanking],
    band: str,
    quantiles: tuple = TIER_QUANTILES,
    sorted_values: Optional[Sequence[float]] = None,
) -> Dict[str, float]:
    """按指定距离带内的 TTK 分布切分层级，返回各层阈值（毫秒）。

    ``sorted_values`` 为该带内 ``mean_ms`` 的**升序**序列；调用方若已排好可直接传入，
    省去重复排序。缺省时本函数自行排序。
    """
    if sorted_values is None:
        sorted_values = sorted(r.bands[band].mean_ms for r in rankings if band in r.bands)
    values = sorted_values
    if not values:
        return {}
    thresholds = {TIER_NAMES[i]: _quantile(values, q) for i, q in enumerate(quantiles)}
    for entry in rankings:
        band_result = entry.bands.get(band)
        if band_result is None:
            continue
        value = band_result.mean_ms
        for i, name in enumerate(TIER_NAMES):
            key = TIER_NAMES[i]
            upper = thresholds.get(key)
            if upper is None or value <= upper + 1e-9:
                band_result.tier = name
                break
        else:
            band_result.tier = TIER_NAMES[-1]
    return thresholds
