"""Engine package containing combat simulator, cost models, and tier ranking modules."""

from src.engine.simulator import (
    simulate_duel,
    calc_effective_hit_rate,
    get_damage_at_distance,
)

__all__ = [
    "simulate_duel",
    "calc_effective_hit_rate",
    "get_damage_at_distance",
]
