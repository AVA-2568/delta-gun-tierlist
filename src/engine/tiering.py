"""纯 TTK 分层与距离带聚合（Task #6）。

主排序键：**距离带内加权实战 TTK**（带内逐米 TTK 的算术平均，毫秒，升序）。
稳健性列：**带内最差 TTK**（带内最大毫秒值）。

分层规则：以该情景该距离带内所有枪的 TTK 分布**分位数**切分 T0–T3，
阈值随情景公布（写入输出 JSON），保证「层级是相对强度」且可复算。

    排序升序后，前 15% → T0，15%–40% → T1，40%–70% → T2，其余 → T3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from src.engine import engagement as eg
from src.engine.ammo_pricing import DEFAULT_CURRENCY
from src.engine.loadout import LoadoutSolver, part_affects_ttk

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from src.engine.ammo_pricing import AmmoPriceTable

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
    mean_expected_shots: float = 0.0
    kill_cost: Optional[int] = None


@dataclass
class GunRanking:
    """一个配置状态在一个情景下的完整成绩。

    ``entry_kind`` 区分三种单状态行：

    - ``"base"``：本体裸枪（官方默认配装）；
    - ``"variant"``：官方变体枪出厂预装态（预装件生效、无其他改装）；
    - ``"single_part"``：本体裸枪 + 单件装配（仅该件替换默认件，不做组合）。

    每行只代表一个配置状态，全部参与排名与分层。
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
    ammo_price_avg_30d: Optional[int] = None
    #: 相对本体裸枪的关键 TTK 属性变化（伤害档案替换、射速、优势射程等）
    loadout_effects: List[Dict[str, Any]] = field(default_factory=list)
    #: 本体裸枪（无改装）在各距离带的 TTK 聚合，作为本行收益的参照
    stock_bands: Dict[str, Dict[str, float]] = field(default_factory=dict)
    #: 本状态在整数采样距离（每 10 m）下的 TTK（毫秒）
    ttk_by_distance_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def has_variant(self) -> bool:
        return bool(self.is_variant)


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
    beam_width: int = 48,
    profile_keys: Optional[Sequence[str]] = None,
    price_table: Optional["AmmoPriceTable"] = None,
) -> tuple:
    """起枪状态口径榜单：每行 = 一个起枪配置状态的 TTK，聚合距离带并分层。

    条目构成（同一把枪会产生多个状态行）：

    - **base 本体**：官方默认配装（裸枪）；
    - **改装状态**：束搜索枚举的合法配装（仅影响 TTK 的插槽参与），每个
      TTK 互异状态一行——四带平均 TTK 相同的状态视为同一情况，不重复列；
    - **官方变体枪（仅预装件影响 TTK 的）**：出厂预装态。

    全部状态行一起参与排名与 T0–T3 分层。各行的「预装收益」以同枪本体
    裸枪为参照。

    **口径弹药不可用的武器会被排除**（与官方榜一致：某些口径没有该等级弹药，
    例如 9x19mm 无 5 级弹）。官方对应输出为 ``eligibleWeaponCount`` / ``excludedWeaponCount``。

    Returns:
        ``(rankings, tier_thresholds, excluded)``。
    """
    solver = solver or LoadoutSolver(game_data, scenario_id)
    keys = list(profile_keys) if profile_keys else [w["profile_key"] for w in game_data.weapons]
    keys_set = set(keys)
    distances = tuple(float(d) for d in range(0, int(eg.DISTANCE_MAX) + 1))

    # 按 weapon_id 分组：base 与其变体
    groups: Dict[str, Dict[str, Any]] = {}
    for weapon in game_data.weapons:
        group = groups.setdefault(str(weapon["weapon_id"]), {"base": None, "variants": []})
        if weapon.get("is_variant"):
            group["variants"].append(weapon)
        else:
            group["base"] = weapon

    def _band_results(
        summary: Mapping[str, Mapping[str, float]], ammo_price: Optional[int]
    ) -> Dict[str, BandResult]:
        return {
            name: BandResult(
                band=name,
                mean_ms=stats["mean_ms"],
                worst_ms=stats["max_ms"],
                best_ms=stats["min_ms"],
                mean_expected_shots=stats["mean_expected_shots"],
                kill_cost=compute_kill_cost(stats["mean_expected_shots"], ammo_price),
            )
            for name, stats in summary.items()
        }

    def _ammo_price(ammo: Mapping[str, Any]) -> Optional[int]:
        ammo_item_id = str(ammo.get("ammo_item_id") or "")
        return price_table.price_for(ammo_item_id) if price_table is not None else None

    def _exclude(profile_key: str, weapon: Mapping[str, Any], exc: Exception) -> Dict[str, str]:
        return {
            "profile_key": profile_key,
            "name": str(weapon.get("display_name") or weapon.get("name") or profile_key),
            "reason": str(exc),
        }

    def _signature(summary: Mapping[str, Mapping[str, float]]) -> tuple:
        """四带平均 TTK 签名：相同签名 = 同一 TTK 状态（不重复列）。"""
        return tuple(round(summary[b]["mean_ms"], 6) for b in BAND_NAMES if b in summary)

    def _factory_ranking(
        weapon: Mapping[str, Any],
        *,
        entry_kind: str,
        curve: Sequence[eg.TtkResult],
        ammo: Mapping[str, Any],
        stock_bands: Mapping[str, Mapping[str, float]],
        loadout_effects: List[Dict[str, Any]],
        loadout: Optional[Mapping[str, Any]] = None,
    ) -> GunRanking:
        ammo_price = _ammo_price(ammo)
        curve0 = curve[0]
        by_distance: Dict[str, float] = {}
        for point in curve:
            d = point.distance_m
            if abs(d - round(d)) < 1e-9 and round(d) % 10 == 0:
                by_distance[str(int(d))] = round(point.ttk_milliseconds, 2)
        return GunRanking(
            profile_key=str(weapon["profile_key"]),
            weapon_id=str(weapon["weapon_id"]),
            display_name=str(weapon.get("display_name") or weapon.get("name") or weapon["profile_key"]),
            base_name=str(weapon.get("name") or weapon["profile_key"]),
            category=str(weapon.get("category") or ""),
            is_variant=entry_kind == "variant",
            variant_item_name=weapon.get("variant_item_name") if entry_kind == "variant" else None,
            loadout=_effective_loadout(loadout or {}, weapon),
            tuning={},
            entry_kind=entry_kind,
            bands=_band_results(eg.band_summary(curve), ammo_price),
            overall_mean_ms=0.0,
            expected_shots_0m=curve0.expected_shots,
            rpm=curve0.rpm,
            ads_ms_reference=curve0.ads_seconds * 1000.0,
            muzzle_velocity_mps=curve0.muzzle_velocity_mps,
            effective_range_m=curve0.effective_range_m,
            ammo_item_id=str(ammo.get("ammo_item_id") or ""),
            ammo_name=str(ammo.get("name") or ""),
            ammo_caliber=str(ammo.get("caliber") or ""),
            ammo_price_avg_30d=ammo_price,
            loadout_effects=loadout_effects,
            stock_bands=dict(stock_bands),
            ttk_by_distance_ms=by_distance,
        )

    rankings: List[GunRanking] = []
    excluded: List[Dict[str, str]] = []

    for _weapon_id, group in groups.items():
        base_weapon = group["base"]
        if base_weapon is None:
            continue
        base_key = str(base_weapon["profile_key"])
        if base_key not in keys_set:
            continue

        # ---- base 本体：官方默认（裸枪）----
        try:
            ammo = solver.ammo_for(base_key)
            base_state = solver.resolver.resolve(base_key, loadout={}, tuning=None)
        except eg.ScenarioError as exc:
            excluded.append(_exclude(base_key, base_weapon, exc))
            continue
        base_curve = eg.ttk_curve(base_state, ammo, solver.armor, solver.probabilities, distances)
        base_stock_bands = eg.band_summary(base_curve)
        rankings.append(
            _factory_ranking(
                base_weapon,
                entry_kind="base",
                curve=base_curve,
                ammo=ammo,
                stock_bands=base_stock_bands,
                loadout_effects=[],
            )
        )

        # ---- 变体枪先入榜：出厂预装态（保留官方身份命名），仅预装件影响 TTK 的才列 ----
        variant_item_ids = {
            str(v.get("variant_item_id") or "") for v in group["variants"]
        }
        variant_signatures: set = set()
        for variant_weapon in group["variants"]:
            variant_key = str(variant_weapon["profile_key"])
            if variant_key not in keys_set:
                continue
            variant_item_id = str(variant_weapon.get("variant_item_id") or "")
            if not part_affects_ttk(game_data.get_part(variant_item_id)):
                continue
            try:
                # 与 base 共用弹药池：口径无该等级弹药时同样排除
                variant_ammo = solver.ammo_for(variant_key)
                variant_state = solver.resolver.resolve(variant_key, loadout={}, tuning=None)
            except eg.ScenarioError as exc:
                excluded.append(_exclude(variant_key, variant_weapon, exc))
                continue
            variant_curve = eg.ttk_curve(
                variant_state, variant_ammo, solver.armor, solver.probabilities, distances
            )
            variant_summary = eg.band_summary(variant_curve)
            variant_signatures.add(_signature(variant_summary))
            rankings.append(
                _factory_ranking(
                    variant_weapon,
                    entry_kind="variant",
                    curve=variant_curve,
                    ammo=variant_ammo,
                    stock_bands=base_stock_bands,
                    loadout_effects=summarize_loadout_effects(base_state, variant_state),
                )
            )

        # ---- 起枪状态池：束搜索合法配装（仅影响 TTK 的插槽参与）----
        # 与变体出厂态同 TTK 签名的状态（即"本体装上该预装件"）已由变体行覆盖，跳过。
        try:
            beam = solver.enumerate_loadouts(base_key, beam_width=beam_width)
        except eg.ScenarioError as exc:
            excluded.append(_exclude(base_key, base_weapon, exc))
            continue

        seen_signatures = {_signature(base_stock_bands)} | variant_signatures

        # 束搜索状态：按四带均值升序排列（与排名方向一致）
        scored: List[tuple] = []
        for loadout in beam:
            try:
                state_mounted = solver.resolver.resolve(base_key, loadout=loadout, tuning=None)
            except eg.ScenarioError:
                continue
            state_curve = eg.ttk_curve(
                state_mounted, ammo, solver.armor, solver.probabilities, distances
            )
            scored.append((loadout, state_mounted, state_curve, eg.band_summary(state_curve)))
        scored.sort(key=lambda item: tuple(item[3][b]["mean_ms"] for b in BAND_NAMES if b in item[3]))

        for loadout_choice, _mounted, state_curve, state_summary in scored:
            signature = _signature(state_summary)
            if signature in seen_signatures:
                continue  # TTK 与已列状态相同 → 不属于"会影响 TTK 的情况"
            seen_signatures.add(signature)
            rankings.append(
                _factory_ranking(
                    base_weapon,
                    entry_kind="state",
                    curve=state_curve,
                    ammo=ammo,
                    stock_bands=base_stock_bands,
                    loadout_effects=summarize_loadout_effects(
                        base_state, solver.resolver.resolve(base_key, loadout=loadout_choice, tuning=None)
                    ),
                    loadout=loadout_choice,
                )
            )

    for entry in rankings:
        if entry.bands:
            entry.overall_mean_ms = sum(b.mean_ms for b in entry.bands.values()) / len(entry.bands)

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
    price_table: Optional["AmmoPriceTable"] = None,
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
                "loadout": entry.loadout,
                "tuning": entry.tuning,
                "entry_kind": entry.entry_kind,
                "loadout_effects": [dict(e) for e in entry.loadout_effects],
                "ttk_by_distance_ms": dict(entry.ttk_by_distance_ms),
                "stock_bands": {
                    name: {k: round(v, 2) for k, v in stats.items()}
                    for name, stats in entry.stock_bands.items()
                },
                "overall_mean_ms": round(entry.overall_mean_ms, 2),
                "expected_shots_0m": round(entry.expected_shots_0m, 4),
                "rpm": round(entry.rpm, 1),
                "ads_ms_reference": round(entry.ads_ms_reference, 2),
                "muzzle_velocity_mps": round(entry.muzzle_velocity_mps, 2),
                "effective_range_m": round(entry.effective_range_m, 2),
                "ammo": {
                    "ammo_item_id": entry.ammo_item_id,
                    "name": entry.ammo_name,
                    "caliber": entry.ammo_caliber,
                    "price_avg_30d": entry.ammo_price_avg_30d,
                },
                "bands": {
                    name: {
                        "rank": b.rank,
                        "tier": b.tier,
                        "mean_ms": round(b.mean_ms, 2),
                        "worst_ms": round(b.worst_ms, 2),
                        "best_ms": round(b.best_ms, 2),
                        "mean_expected_shots": round(b.mean_expected_shots, 6),
                        "kill_cost": b.kill_cost,
                    }
                    for name, b in entry.bands.items()
                },
            }
        )
    # 变体出厂态行与本体的最优配装行同属「可参赛武器」，直接计入 eligible
    eligible = len(rankings)
    excluded_count = len(excluded or [])

    return {
        "scenario_id": scenario_id,
        "ammo_price_meta": {
            "currency": price_table.currency if price_table is not None else DEFAULT_CURRENCY,
            "window": dict(price_table.window) if price_table is not None else {},
            "updated_at": price_table.updated_at if price_table is not None else "",
            "available": bool(price_table is not None and not price_table.is_empty),
        },
        "ranking_key": "band_mean_ttk_ms",
        "robustness_key": "band_worst_ttk_ms",
        "tier_quantiles": list(TIER_QUANTILES),
        "weapon_pool_count": eligible + excluded_count,
        "eligible_weapon_count": eligible,
        "excluded_weapon_count": excluded_count,
        "ranked_entry_count": len(rankings),
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
