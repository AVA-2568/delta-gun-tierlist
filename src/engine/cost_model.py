"""Economic cost evaluation model for loadout pricing and ammo consumption."""

from typing import Optional, Tuple
from src.models import AmmoPrice, GunMeta, WeaponBuild


def calc_loadout_cost(
    gun: GunMeta,
    build: Optional[WeaponBuild],
    ammo: AmmoPrice,
    stk: int = 1,
    reserve_rounds: int = 60,
) -> Tuple[int, int, int]:
    """Calculate total tactical loadout cost, reserve ammo cost, and single kill ammo cost.

    Formula:
        ammo_reserve_cost = reserve_rounds * ammo.price_per_round
        total_loadout_cost = gun.base_price + build.mod_cost + ammo_reserve_cost
        single_kill_cost = stk * ammo.price_per_round

    Args:
        gun: Base weapon metadata with base price.
        build: Weapon modification plan with attachment costs (or None for stock).
        ammo: Ammo market price object.
        stk: Shots to kill from combat simulation (defaults to 1).
        reserve_rounds: Number of reserve rounds (standard baseline is 60).

    Returns:
        Tuple[int, int, int]:
            - total_loadout_cost: Combined weapon, modification, and reserve ammo cost.
            - ammo_reserve_cost: Cost of reserve ammunition.
            - single_kill_cost: Cost of ammunition consumed per single kill.
    """
    ammo_reserve_cost = reserve_rounds * ammo.price_per_round
    mod_cost = build.mod_cost if build is not None else 0
    total_loadout_cost = gun.base_price + mod_cost + ammo_reserve_cost
    single_kill_cost = stk * ammo.price_per_round

    return total_loadout_cost, ammo_reserve_cost, single_kill_cost
