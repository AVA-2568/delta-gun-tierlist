"""Engine package containing combat simulator, cost models, and tier ranking modules."""

from src.engine.cost_model import calc_loadout_cost
from src.engine.ranker import calc_handling_score, rank_weapons
from src.engine.simulator import (
    calc_effective_hit_rate,
    get_damage_at_distance,
    simulate_duel,
)

__all__ = [
    "simulate_duel",
    "calc_effective_hit_rate",
    "get_damage_at_distance",
    "calc_loadout_cost",
    "calc_handling_score",
    "rank_weapons",
]

