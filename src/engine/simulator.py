"""Discrete bullet-by-bullet combat simulation and practical TTK engine."""

import math
import random
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

# Standard helmet baseline durability lookup table
HELMET_MAX_DURABILITY: Dict[int, float] = {
    1: 25.0,
    2: 30.0,
    3: 35.0,
    4: 45.0,
    5: 55.0,
    6: 70.0,
}

# Real combat hit location probability distribution from dfttk.com:
# 头部 17.24% / 胸部 30.46% / 腹部 18.97% / 上臂 12.00% / 其余四肢 21.33%
HIT_PARTS: List[str] = ["head", "chest", "stomach", "arms", "legs"]
HIT_WEIGHTS: List[float] = [0.1724, 0.3046, 0.1897, 0.1200, 0.2133]


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
    sim_iterations: int = 500,
    seed: int = 42,
) -> SimulationResult:
    """Simulate real combat duel against an armored target using dfttk hit location distribution.

    Hit location probabilities:
        - 头部 (17.24%): 受到头盔保护，穿透后 2.5x 爆头暴击肉伤，未穿透造成钝伤与头盔耐久损耗
        - 胸部 (30.46%): 受到胸部护甲保护，穿透全额肉伤 (1.0x)，未穿透造成钝伤 (0.15x) 与甲耐久损耗
        - 腹部 (18.97%): 受到防具保护，肉伤 1.0x
        - 上臂 (12.00%): 无护甲保护 (0 Armor)，全额直伤 0.8x 绕过护甲扣减 HP
        - 腿部 (21.33%): 无护甲保护 (0 Armor)，全额直伤 0.7x 绕过护甲扣减 HP

    Simulation runs Monte Carlo iterations with deterministic seed to calculate expected STK and TTK.
    """
    chest_damage, armor_damage = get_damage_at_distance(gun.dropoffs, float(distance_m))

    max_body_dur = ARMOR_MAX_DURABILITY.get(
        armor_level, max(20.0, armor_level * 18.0 + 5.0)
    )
    max_head_dur = HELMET_MAX_DURABILITY.get(
        armor_level, max(15.0, armor_level * 10.0 + 5.0)
    )

    target_pen = armor_level * 10
    delta_pen = ammo.penetration - target_pen

    # Material resistance factor against lower-tier bullets
    tier_diff = max(0, armor_level - ammo.level)
    armor_eff = max(0.20, 1.0 - 0.55 * tier_diff)

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

            if part == "arms":
                hp -= chest_damage * 0.80
            elif part == "legs":
                hp -= chest_damage * 0.70
            elif part in ["chest", "stomach"]:
                dur_ratio = cur_body_dur / max_body_dur if max_body_dur > 0 else 0.0
                deg = (0.35 - dur_ratio) / 0.35 if dur_ratio < 0.35 else 0.0
                z = delta_pen + 30.0 * deg - 5.0

                prob = 1.0 if cur_body_dur <= 0.0 else 1.0 / (1.0 + math.exp(-z / 3.0))
                if rng.random() < prob:
                    hp -= chest_damage * 1.0
                    cur_body_dur = max(0.0, cur_body_dur - armor_damage * 0.60 * armor_eff)
                else:
                    hp -= chest_damage * 0.15
                    cur_body_dur = max(0.0, cur_body_dur - armor_damage * 1.00 * armor_eff)
            elif part == "head":
                dur_ratio = cur_head_dur / max_head_dur if max_head_dur > 0 else 0.0
                deg = (0.35 - dur_ratio) / 0.35 if dur_ratio < 0.35 else 0.0
                z = delta_pen + 30.0 * deg - 5.0

                prob = 1.0 if cur_head_dur <= 0.0 else 1.0 / (1.0 + math.exp(-z / 3.0))
                if rng.random() < prob:
                    hp -= chest_damage * 2.50
                    cur_head_dur = max(0.0, cur_head_dur - armor_damage * 0.60 * armor_eff)
                else:
                    hp -= chest_damage * 2.50 * 0.15
                    cur_head_dur = max(0.0, cur_head_dur - armor_damage * 1.00 * armor_eff)

        stk_samples.append(shots)

    avg_stk = sum(stk_samples) / len(stk_samples)
    stk = max(1, int(round(avg_stk)))

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

