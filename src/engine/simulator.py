"""Discrete bullet-by-bullet combat simulation and practical TTK engine."""

import math
from typing import Dict, List, Tuple

from src.models import AmmoPrice, DamageDropoff, GunMeta, SimulationResult

# Standard armor baseline durability lookup table
ARMOR_MAX_DURABILITY: Dict[int, float] = {
    1: 35.0,
    2: 50.0,
    3: 60.0,
    4: 75.0,
    5: 95.0,
    6: 115.0,
}


def get_damage_at_distance(
    dropoffs: List[DamageDropoff], distance_m: float
) -> Tuple[float, float]:
    """Retrieve chest flesh damage and armor durability damage for a given distance."""
    sorted_dropoffs = sorted(dropoffs, key=lambda d: d.max_distance)
    for dropoff in sorted_dropoffs:
        if distance_m <= dropoff.max_distance:
            return dropoff.chest_damage, dropoff.armor_damage
    return sorted_dropoffs[-1].chest_damage, sorted_dropoffs[-1].armor_damage


def calc_effective_hit_rate(
    recoil_control: float, stability: float, velocity: float, distance_m: float
) -> float:
    """Calculate Effective Hit Rate (EHR) considering recoil, stability, velocity, and distance.

    Formula:
        EHR(d) = min(1.0, alpha(d) * [0.4 + 0.35 * (recoil/100) + 0.25 * (stability/100)] * sqrt(velocity/600))
    """
    control_factor = 0.4 + 0.35 * (recoil_control / 100.0) + 0.25 * (stability / 100.0)
    velocity_factor = math.sqrt(max(1.0, velocity) / 600.0)

    # Distance attenuation coefficient alpha(d)
    if distance_m <= 15.0:
        alpha = 1.10
    elif distance_m <= 35.0:
        # Linear interpolation between 15m (1.10) and 35m (0.85)
        alpha = 1.10 - (distance_m - 15.0) * (1.10 - 0.85) / (35.0 - 15.0)
    elif distance_m <= 50.0:
        # Linear interpolation between 35m (0.85) and 50m (0.65)
        alpha = 0.85 - (distance_m - 35.0) * (0.85 - 0.65) / (50.0 - 35.0)
    else:
        alpha = max(0.20, 0.65 - (distance_m - 50.0) * 0.01)

    raw_ehr = alpha * control_factor * velocity_factor
    return max(0.05, min(1.0, raw_ehr))


def simulate_duel(
    gun: GunMeta, ammo: AmmoPrice, armor_level: int, distance_m: int
) -> SimulationResult:
    """Simulate discrete bullet-by-bullet combat duel against an armored target.

    Chest HP: 100.0
    Armor durability: Looked up from ARMOR_MAX_DURABILITY based on armor_level.
    Simulation logic:
        - Target penetration baseline = armor_level * 10
        - Delta penetration = ammo.penetration - target_pen
        - Penetration probability follows a logistic transition that jumps as armor durability drops below 35%
        - Unpenetrated: deals blunt flesh damage (~15% base damage) and heavy durability damage
        - Penetrated: deals full flesh damage and medium durability damage
        - Shots continue until HP <= 0 (STK)
        - Theoretical TTK = (STK - 1) * (60.0 / gun.rpm) * 1000 ms
        - Practical TTK = ads_time_ms * k_ads + theoretical_ttk_ms / EHR
    """
    chest_damage, armor_damage = get_damage_at_distance(gun.dropoffs, float(distance_m))
    max_durability = ARMOR_MAX_DURABILITY.get(
        armor_level, max(20.0, armor_level * 18.0 + 5.0)
    )
    current_durability = max_durability

    target_penetration = armor_level * 10
    delta_pen = ammo.penetration - target_penetration

    # Material resistance factor against lower-tier bullets
    tier_diff = max(0, armor_level - ammo.level)
    armor_eff = max(0.20, 1.0 - 0.55 * tier_diff)

    hp = 100.0
    shots = 0

    while hp > 0.0 and shots < 100:
        shots += 1
        durability_ratio = current_durability / max_durability if max_durability > 0 else 0.0

        # Degradation score rises sharply once durability drops below 35%
        if durability_ratio < 0.35:
            degradation = (0.35 - durability_ratio) / 0.35
        else:
            degradation = 0.0

        z = delta_pen + 30.0 * degradation - 5.0
        if current_durability <= 0.0:
            penetration_prob = 1.0
        else:
            penetration_prob = 1.0 / (1.0 + math.exp(-z / 3.0))

        penetrated = penetration_prob >= 0.5

        if penetrated:
            flesh_damage = chest_damage
            durability_loss = armor_damage * 0.60 * armor_eff
        else:
            flesh_damage = chest_damage * 0.15
            durability_loss = armor_damage * 1.00 * armor_eff

        hp -= flesh_damage
        current_durability = max(0.0, current_durability - durability_loss)

    stk = shots
    theoretical_ttk_ms = (stk - 1) * (60.0 / gun.rpm) * 1000.0
    ehr = calc_effective_hit_rate(
        gun.recoil_control, gun.stability, gun.bullet_velocity, float(distance_m)
    )

    k_ads = 0.5 if distance_m <= 15 else 0.8
    practical_ttk_ms = gun.ads_time_ms * k_ads + (theoretical_ttk_ms / ehr)

    return SimulationResult(
        stk=stk,
        theoretical_ttk_ms=round(theoretical_ttk_ms, 2),
        practical_ttk_ms=round(practical_ttk_ms, 2),
        ehr=round(ehr, 4),
    )
