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

from src.engine import engagement as eg
from src.engine.loadout import LoadoutSolver

TIER_QUANTILES: tuple = (0.15, 0.40, 0.70)
TIER_NAMES: tuple = ("T0", "T1", "T2", "T3")
BAND_NAMES: tuple = ("贴脸", "近距", "中距", "远距")


@dataclass
class BandResult:
    """一个距离带内该枪的聚合结果。"""

    band: str
    mean_ms: float
    worst_ms: float
    best_ms: float
    rank: int = 0
    tier: str = ""


@dataclass
class GunRanking:
    """一把枪在一个情景下的完整成绩与配装。"""

    profile_key: str
    weapon_id: str
    display_name: str
    base_name: str
    category: str
    is_variant: bool
    variant_item_name: Optional[str]
    loadout: Dict[str, str]
    tuning: Dict[str, Dict[str, float]]
    equivalent_variants: List[str] = field(default_factory=list)
    bands: Dict[str, BandResult] = field(default_factory=dict)
    overall_mean_ms: float = 0.0
    expected_shots_0m: float = 0.0
    rpm: float = 0.0
    ads_ms_reference: float = 0.0
    muzzle_velocity_mps: float = 0.0
    effective_range_m: float = 0.0

    @property
    def has_variant(self) -> bool:
        return bool(self.is_variant)


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


def _same_performance(a: "GunRanking", b: "GunRanking") -> bool:
    if set(a.bands) != set(b.bands):
        return False
    for band, result in a.bands.items():
        if abs(result.mean_ms - b.bands[band].mean_ms) > 1e-6:
            return False
    return True


def _merge_equivalent_variants(rankings: List["GunRanking"]) -> List["GunRanking"]:
    """把「最优配装与 base 完全等价」的变体折叠到 base 行。

    变体是官方预装某配件的版本；若 base 的最优解恰好就是该配件，两者成绩完全一致，
    榜单上重复列出没有信息量，改用 ``equivalent_variants`` 标注。
    """
    grouped: Dict[str, List[GunRanking]] = {}
    for entry in rankings:
        grouped.setdefault(entry.weapon_id, []).append(entry)

    merged: List[GunRanking] = []
    for _weapon_id, group in grouped.items():
        base = next((e for e in group if not e.is_variant), group[0])
        for variant in group:
            if variant is base:
                continue
            if variant.loadout == base.loadout and _same_performance(variant, base):
                base.equivalent_variants.append(variant.display_name)
            else:
                merged.append(variant)
        merged.append(base)
    merged.sort(key=lambda e: e.display_name)
    return merged


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
) -> Dict[str, float]:
    """按指定距离带内的 TTK 分布切分层级，返回各层阈值（毫秒）。"""
    values = sorted(r.bands[band].mean_ms for r in rankings if band in r.bands)
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


def rank_weapons_for_scenario(
    game_data: Any,
    scenario_id: str,
    solver: Optional[LoadoutSolver] = None,
    beam_width: int = 8,
    top_k: int = 4,
    profile_keys: Optional[Sequence[str]] = None,
) -> tuple:
    """对武器池逐枪求解最优配装，聚合距离带并分层。

    **口径弹药不可用的武器会被排除**（与官方榜一致：某些口径没有该等级弹药，
    例如 9x19mm 无 5 级弹）。官方对应输出为 ``eligibleWeaponCount`` / ``excludedWeaponCount``。

    Returns:
        ``(rankings, tier_thresholds, excluded)``。
    """
    solver = solver or LoadoutSolver(game_data, scenario_id)
    keys = list(profile_keys) if profile_keys else [w["profile_key"] for w in game_data.weapons]

    rankings: List[GunRanking] = []
    excluded: List[Dict[str, str]] = []
    for profile_key in keys:
        weapon = game_data.get_weapon(profile_key)
        try:
            solution = solver.solve(profile_key, beam_width=beam_width, top_k=top_k)
        except eg.ScenarioError as exc:
            # 该口径没有本情景所需等级的弹药 → 排除（与官方 excluded 口径一致）
            excluded.append(
                {
                    "profile_key": profile_key,
                    "name": str(weapon.get("display_name") or weapon.get("name") or profile_key),
                    "reason": str(exc),
                }
            )
            continue
        summary = eg.band_summary(solution.curve)
        bands = {
            name: BandResult(
                band=name,
                mean_ms=stats["mean_ms"],
                worst_ms=stats["max_ms"],
                best_ms=stats["min_ms"],
            )
            for name, stats in summary.items()
        }
        curve0 = solution.curve[0]
        rankings.append(
            GunRanking(
                profile_key=profile_key,
                weapon_id=str(weapon["weapon_id"]),
                display_name=str(weapon.get("display_name") or weapon.get("name") or profile_key),
                base_name=str(weapon.get("name") or profile_key),
                category=str(weapon.get("category") or ""),
                is_variant=bool(weapon.get("is_variant")),
                variant_item_name=weapon.get("variant_item_name"),
                loadout=_effective_loadout(solution.loadout, weapon),
                tuning={k: dict(v) for k, v in solution.tuning.items()},
                bands=bands,
                overall_mean_ms=sum(b.mean_ms for b in bands.values()) / len(bands) if bands else 0.0,
                expected_shots_0m=curve0.expected_shots,
                rpm=curve0.rpm,
                ads_ms_reference=curve0.ads_seconds * 1000.0,
                muzzle_velocity_mps=curve0.muzzle_velocity_mps,
                effective_range_m=curve0.effective_range_m,
            )
        )

    # 折叠「最优解与 base 完全等价」的变体，避免榜单重复条目
    rankings = _merge_equivalent_variants(rankings)

    thresholds: Dict[str, Dict[str, float]] = {}
    for band in BAND_NAMES:
        present = [r for r in rankings if band in r.bands]
        present.sort(key=lambda r: r.bands[band].mean_ms)
        for index, entry in enumerate(present, start=1):
            entry.bands[band].rank = index
        thresholds[band] = assign_tiers(rankings, band)

    return rankings, thresholds, excluded


def to_export(
    rankings: List[GunRanking],
    thresholds: Mapping[str, Mapping[str, float]],
    scenario_id: str,
    excluded: Optional[Sequence[Mapping[str, str]]] = None,
) -> Dict[str, Any]:
    """序列化为可写入 JSON 的结构（渲染层直接消费，禁止二次计算）。"""
    payload_rankings: List[Dict[str, Any]] = []
    for entry in rankings:
        payload_rankings.append(
            {
                "profile_key": entry.profile_key,
                "weapon_id": entry.weapon_id,
                "name": entry.display_name,
                "base_name": entry.base_name,
                "category": entry.category,
                "is_variant": entry.is_variant,
                "variant_item_name": entry.variant_item_name,
                "equivalent_variants": list(entry.equivalent_variants),
                "loadout": entry.loadout,
                "tuning": entry.tuning,
                "overall_mean_ms": round(entry.overall_mean_ms, 2),
                "expected_shots_0m": round(entry.expected_shots_0m, 4),
                "rpm": round(entry.rpm, 1),
                "ads_ms_reference": round(entry.ads_ms_reference, 2),
                "muzzle_velocity_mps": round(entry.muzzle_velocity_mps, 2),
                "effective_range_m": round(entry.effective_range_m, 2),
                "bands": {
                    name: {
                        "rank": b.rank,
                        "tier": b.tier,
                        "mean_ms": round(b.mean_ms, 2),
                        "worst_ms": round(b.worst_ms, 2),
                        "best_ms": round(b.best_ms, 2),
                    }
                    for name, b in entry.bands.items()
                },
            }
        )
    # 折叠的等价变体仍属于「可参赛武器」，统计口径必须补回，
    # 否则 ``weapon_pool_count`` 会小于官方武器池。
    folded = sum(len(entry.equivalent_variants) for entry in rankings)
    eligible = len(rankings) + folded
    excluded_count = len(excluded or [])

    return {
        "scenario_id": scenario_id,
        "ranking_key": "band_mean_ttk_ms",
        "robustness_key": "band_worst_ttk_ms",
        "tier_quantiles": list(TIER_QUANTILES),
        "weapon_pool_count": eligible + excluded_count,
        "eligible_weapon_count": eligible,
        "excluded_weapon_count": excluded_count,
        "ranked_entry_count": len(rankings),
        "folded_variant_count": folded,
        "excluded_weapons": [dict(item) for item in (excluded or [])],
        "tier_thresholds_ms": {
            band: {tier: round(value, 2) for tier, value in per.items()}
            for band, per in thresholds.items()
        },
        "band_definitions": {
            name: {"from_m": eg.DISTANCE_BANDS[name][0], "to_m": eg.DISTANCE_BANDS[name][1]}
            for name in BAND_NAMES
        },
        "weapons": payload_rankings,
    }
