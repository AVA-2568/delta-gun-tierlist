"""Multi-dimensional weapon ranking and tier determination engine."""

from typing import Any, Dict, List, Optional, Union
from src.engine.cost_model import calc_loadout_cost
from src.engine.simulator import simulate_duel
from src.models import AmmoPrice, GunMeta, SimulationResult, TierEntry, WeaponBuild

DEFAULT_COMBAT_BASELINE: float = 35.0
DEFAULT_COST_BASELINE: float = 0.0


def calc_handling_score(recoil: float, stability: float, rpm: int) -> float:
    """Calculate handling and error-tolerance score (0~100).

    Formula:
        handling_score = 0.4 * recoil + 0.3 * stability + 0.3 * min(100, rpm / 10)
    """
    raw_score = 0.4 * recoil + 0.3 * stability + 0.3 * min(100.0, rpm / 10.0)
    return round(max(0.0, min(100.0, raw_score)), 2)


def resolve_ammo(
    ammo_prices: Union[Dict[Any, AmmoPrice], List[AmmoPrice]],
    caliber: str,
    target_level: int,
) -> Optional[AmmoPrice]:
    """Resolve ammo price record strictly matching caliber and target level.

    Returns None if no ammo of the specified level exists for the caliber.
    """
    if isinstance(ammo_prices, dict):
        key = f"{caliber}_{target_level}"
        if key in ammo_prices:
            return ammo_prices[key]

        if (caliber, target_level) in ammo_prices:
            return ammo_prices[(caliber, target_level)]

        norm_cal = caliber.replace(" ", "").lower().rstrip("mm")
        for v in ammo_prices.values():
            if isinstance(v, AmmoPrice) and v.level == target_level:
                if (
                    v.caliber == caliber
                    or v.caliber.replace(" ", "").lower().rstrip("mm") == norm_cal
                ):
                    return v
        return None

    elif isinstance(ammo_prices, list):
        norm_cal = caliber.replace(" ", "").lower().rstrip("mm")
        for item in ammo_prices:
            if item.level == target_level:
                if (
                    item.caliber == caliber
                    or item.caliber.replace(" ", "").lower().rstrip("mm") == norm_cal
                ):
                    return item
        return None

    return None


def generate_tags(
    gun: GunMeta,
    build: Optional[WeaponBuild],
    ammo: AmmoPrice,
    sim: SimulationResult,
    total_cost: int,
    single_kill_cost: int,
    combat_score: float,
    handling_score: float,
    cost_score: float,
    composite_score: float,
    tier: str,
    distance_m: int,
) -> List[str]:
    """Generate meaningful domain-specific tactical tags for the weapon."""
    tags: List[str] = []

    # Tier excellence
    if tier == "T0":
        tags.append("版本答案")

    # Economic characteristics
    if cost_score >= 80.0 or total_cost <= 115000:
        tags.append("平民首选")

    # Range & combat mechanics
    if distance_m <= 15 and (gun.category == "冲锋枪" or gun.rpm >= 850 or combat_score >= 80.0):
        tags.append("近战撕裂")

    if distance_m >= 35 and (
        gun.category in ["精确射手步枪", "战斗步枪"]
        or gun.bullet_velocity >= 800.0
        or combat_score >= 75.0
    ):
        tags.append("远距控场")

    # Handling stability
    if handling_score >= 75.0:
        tags.append("高容错")

    # Lethality & ammo efficiency
    if sim.stk <= 3:
        tags.append("破甲利刃")
    elif single_kill_cost <= 5000:
        tags.append("低耗击杀")

    # High capacity
    if gun.default_mag_size >= 40:
        tags.append("持久压制")

    # Fallback to category baseline if few tags assigned
    if len(tags) < 2:
        category_defaults = {
            "突击步枪": "均衡突击",
            "冲锋枪": "极限机动",
            "精确射手步枪": "高精点射",
            "战斗步枪": "重火压制",
        }
        fallback_tag = category_defaults.get(gun.category, "标准战备")
        if fallback_tag not in tags:
            tags.append(fallback_tag)

    return tags


def rank_weapons(
    guns: List[GunMeta],
    builds: Dict[str, WeaponBuild],
    ammo_prices: Union[Dict[Any, AmmoPrice], List[AmmoPrice]],
    armor_level: int,
    ammo_level: int,
    distance_m: int,
    combat_baseline: float = DEFAULT_COMBAT_BASELINE,
    cost_baseline: float = DEFAULT_COST_BASELINE,
) -> List[TierEntry]:
    """Simulate combat, evaluate economics, compute composite scores, and rank weapons.

    Args:
        guns: List of weapon metadata models.
        builds: Dictionary mapping gun_id to WeaponBuild.
        ammo_prices: Mapping or list containing AmmoPrice instances.
        armor_level: Target armor level (e.g. 4 or 5).
        ammo_level: Ammunition level (e.g. 4 or 5).
        distance_m: Engagement combat distance in meters (e.g. 15, 35, 50).
        combat_baseline: Baseline score for the slowest weapon practical TTK (default 35.0).
        cost_baseline: Baseline score for the highest loadout cost weapon (default 0.0).

    Returns:
        List[TierEntry]: Ranked list of tier list entries sorted descending by composite_score.
    """
    if not guns:
        return []

    simulated_items = []

    for gun in guns:
        ammo = resolve_ammo(ammo_prices, gun.caliber, ammo_level)
        if ammo is None:
            # Caliber gating: skip weapon if no suitable ammo for this scenario
            continue

        build = builds.get(gun.id)

        effective_velocity = (
            gun.bullet_velocity * (1.0 + build.velocity_bonus_pct)
            if build
            else gun.bullet_velocity
        )
        effective_ads = (
            max(50, gun.ads_time_ms + build.ads_modifier_ms)
            if build
            else gun.ads_time_ms
        )
        effective_recoil = (
            min(100.0, max(0.0, gun.recoil_control + build.recoil_bonus))
            if build
            else gun.recoil_control
        )
        effective_stability = (
            min(100.0, max(0.0, gun.stability + build.stability_bonus))
            if build
            else gun.stability
        )
        attachments = build.attachments if build else []
        tuning_instructions = getattr(build, "tuning_instructions", []) if build else []

        sim_gun = gun.model_copy(
            update={
                "ads_time_ms": effective_ads,
                "recoil_control": effective_recoil,
                "stability": effective_stability,
            }
        )
        sim = simulate_duel(
            sim_gun,
            ammo,
            armor_level,
            distance_m,
            effective_velocity=effective_velocity,
        )
        handling_score = calc_handling_score(
            recoil=effective_recoil,
            stability=effective_stability,
            rpm=gun.rpm,
        )
        total_cost, ammo_60_cost, single_kill_cost = calc_loadout_cost(
            gun=gun,
            build=build,
            ammo=ammo,
            stk=sim.stk,
            reserve_rounds=60,
        )

        simulated_items.append(
            {
                "gun": gun,
                "build": build,
                "ammo": ammo,
                "sim": sim,
                "attachments": attachments,
                "tuning_instructions": tuning_instructions,
                "handling_score": handling_score,
                "total_cost": total_cost,
                "ammo_60_cost": ammo_60_cost,
                "single_kill_cost": single_kill_cost,
            }
        )

    if not simulated_items:
        return []

    # Min-Max normalization
    min_ttk = min(item["sim"].practical_ttk_ms for item in simulated_items)
    max_ttk = max(item["sim"].practical_ttk_ms for item in simulated_items)
    min_cost = min(item["total_cost"] for item in simulated_items)
    max_cost = max(item["total_cost"] for item in simulated_items)

    entries: List[TierEntry] = []

    for item in simulated_items:
        gun = item["gun"]
        sim = item["sim"]
        total_cost = item["total_cost"]
        handling_score = item["handling_score"]

        # Combat score: faster TTK is better
        if max_ttk > min_ttk:
            c_score = 100.0 - (
                (sim.practical_ttk_ms - min_ttk) / (max_ttk - min_ttk)
            ) * (100.0 - combat_baseline)
        else:
            c_score = 100.0
        combat_score = round(max(0.0, min(100.0, c_score)), 2)

        # Cost score: cheaper loadout cost is better
        if max_cost > min_cost:
            cost_norm = 100.0 - (
                (total_cost - min_cost) / (max_cost - min_cost)
            ) * (100.0 - cost_baseline)
        else:
            cost_norm = 100.0
        cost_score = round(max(0.0, min(100.0, cost_norm)), 2)

        # Composite score: 50% combat + 20% handling + 30% cost
        raw_composite = 0.50 * combat_score + 0.20 * handling_score + 0.30 * cost_score
        composite_score = round(max(0.0, min(100.0, raw_composite)), 2)

        # Tier determination
        if composite_score >= 88.0:
            tier = "T0"
        elif composite_score >= 78.0:
            tier = "T1"
        elif composite_score >= 65.0:
            tier = "T2"
        else:
            tier = "T3"

        tags = generate_tags(
            gun=gun,
            build=item["build"],
            ammo=item["ammo"],
            sim=sim,
            total_cost=total_cost,
            single_kill_cost=item["single_kill_cost"],
            combat_score=combat_score,
            handling_score=handling_score,
            cost_score=cost_score,
            composite_score=composite_score,
            tier=tier,
            distance_m=distance_m,
        )

        entry = TierEntry(
            gun_id=gun.id,
            gun_name=gun.name,
            category=gun.category,
            caliber=gun.caliber,
            distance_m=distance_m,
            armor_level=armor_level,
            ammo_level=ammo_level,
            stk=sim.stk,
            practical_ttk_ms=sim.practical_ttk_ms,
            ammo_60_cost=item["ammo_60_cost"],
            total_loadout_cost=total_cost,
            single_kill_cost=item["single_kill_cost"],
            combat_score=combat_score,
            handling_score=handling_score,
            cost_score=cost_score,
            composite_score=composite_score,
            tier=tier,
            attachments=item["attachments"],
            tuning_instructions=item["tuning_instructions"],
            tags=tags,
        )
        entries.append(entry)

    # Sort descending by composite_score (tie-breakers: practical TTK, total cost)
    entries.sort(key=lambda e: (-e.composite_score, e.practical_ttk_ms, e.total_loadout_cost))

    return entries


generate_scenario_rankings = rank_weapons

