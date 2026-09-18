"""Discrete bullet-by-bullet combat simulation and practical TTK engine."""

import math
import random
from typing import Dict, List, Optional, Tuple

from src.models import AmmoPrice, DamageDropoff, GunMeta, SimulationResult

# Official Delta Force defense preset values from dfttk.com v3:
# 3套: 头盔耐久 40 / 护甲耐久 85
# 4套: 头盔耐久 48 / 护甲耐久 110
# 5套: 头盔耐久 50 / 护甲耐久 125
# 6套: 头盔耐久 50 / 护甲耐久 150
ARMOR_MAX_DURABILITY: Dict[int, float] = {
    1: 45.0,
    2: 65.0,
    3: 85.0,
    4: 110.0,
    5: 125.0,
    6: 150.0,
}

HELMET_MAX_DURABILITY: Dict[int, float] = {
    1: 25.0,
    2: 30.0,
    3: 40.0,
    4: 48.0,
    5: 50.0,
    6: 50.0,
}

# Real combat hit location probability distribution:
# 头部 17.24% / 胸部 30.46% / 腹部 18.97% / 上臂 8.33% / 其余四肢 25.00%
HIT_PARTS: List[str] = ["head", "chest", "abdomen", "upper_arm", "limbs"]
HIT_WEIGHTS: List[float] = [0.1724, 0.3046, 0.1897, 0.0833, 0.2500]

HITBOX_MULTIPLIERS: Dict[str, float] = {
    "head": 1.90,
    "chest": 1.00,
    "abdomen": 0.90,
    "upper_arm": 0.40,
    "limbs": 0.40,
}


def get_pen_rate(ammo_level: int, armor_level: int) -> float:
    """Official deterministic penetration coefficient.

    - ammo_level < armor_level: 0.0 (no blunt damage before break)
    - ammo_level == armor_level: 0.50
    - ammo_level == armor_level + 1: 0.75
    - ammo_level >= armor_level + 2: 1.00
    """
    if ammo_level < armor_level:
        return 0.0
    elif ammo_level == armor_level:
        return 0.50
    elif ammo_level == armor_level + 1:
        return 0.75
    else:
        return 1.00


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
    gun: GunMeta,
    ammo: AmmoPrice,
    armor_level: int,
    distance_m: int,
    effective_velocity: Optional[float] = None,
    sim_iterations: int = 500,
    seed: int = 42,
) -> SimulationResult:
    """Simulate real combat duel against an armored target using official deterministic pen and hitboxes."""
    velocity = effective_velocity if effective_velocity is not None else gun.bullet_velocity
    chest_damage, armor_damage = get_damage_at_distance(gun.dropoffs, float(distance_m))

    # Ammo flesh damage rate adjustment (e.g. .45 ACP Super has 0.85 rate)
    flesh_rate = 0.85 if ".45" in ammo.caliber and ammo.level == 5 else 1.00
    chest_damage *= flesh_rate

    # Ammo armor damage rate
    ammo_armor_rate = 1.10 if ammo.level >= 5 else 1.00
    actual_armor_dmg = armor_damage * ammo_armor_rate

    max_body_dur = ARMOR_MAX_DURABILITY.get(armor_level, float(armor_level * 25.0))
    max_head_dur = HELMET_MAX_DURABILITY.get(armor_level, float(armor_level * 10.0))
    pen_rate = get_pen_rate(ammo.level, armor_level)

    rng = random.Random(seed)
    stk_samples: List[int] = []

    for _ in range(sim_iterations):
        hp = 100.0
        cur_body_dur = max_body_dur
        cur_head_dur = max_head_dur
        shots = 0

        while hp > 0.0 and shots < 50:
            shots += 1
            part = rng.choices(HIT_PARTS, weights=HIT_WEIGHTS)[0]
            mult = HITBOX_MULTIPLIERS[part]

            if part in ["upper_arm", "limbs"]:
                hp -= chest_damage * mult
            elif part in ["chest", "abdomen"]:
                if cur_body_dur <= 0.0:
                    hp -= chest_damage * mult
                elif actual_armor_dmg >= cur_body_dur:
                    dur_fraction = cur_body_dur / actual_armor_dmg
                    cur_body_dur = 0.0
                    hp -= chest_damage * mult * ((1.0 - dur_fraction) + dur_fraction * pen_rate)
                else:
                    cur_body_dur -= actual_armor_dmg
                    hp -= chest_damage * mult * pen_rate
            elif part == "head":
                if cur_head_dur <= 0.0:
                    hp -= chest_damage * mult
                elif actual_armor_dmg >= cur_head_dur:
                    dur_fraction = cur_head_dur / actual_armor_dmg
                    cur_head_dur = 0.0
                    hp -= chest_damage * mult * ((1.0 - dur_fraction) + dur_fraction * pen_rate)
                else:
                    cur_head_dur -= actual_armor_dmg
                    hp -= chest_damage * mult * pen_rate

        stk_samples.append(shots)

    avg_stk = sum(stk_samples) / len(stk_samples)
    stk = max(1, int(round(avg_stk)))

    theoretical_ttk_ms = max(0.0, (avg_stk - 1) * (60.0 / gun.rpm) * 1000.0)
    ehr = calc_effective_hit_rate(gun.recoil_control, gun.stability, velocity, float(distance_m))

    expected_shots = avg_stk / ehr
    k_ads = 0.5 if distance_m <= 15 else 0.8
    practical_ttk_ms = gun.ads_time_ms * k_ads + max(0.0, (expected_shots - 1) * (60.0 / gun.rpm) * 1000.0)

    return SimulationResult(
        stk=stk,
        theoretical_ttk_ms=round(theoretical_ttk_ms, 2),
        practical_ttk_ms=round(practical_ttk_ms, 2),
        ehr=round(ehr, 4),
    )


