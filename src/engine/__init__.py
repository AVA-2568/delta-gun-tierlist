"""引擎层：官方物理量解析链 + 弹道/STK + 配装求解 + 分层。

模块分工（关注点分离）：

- ``game_data``       只读数据视图
- ``curves``          官方机制曲线求值
- ``weapon_state``    面板 → 规则量 → :class:`WeaponState`
- ``ballistics``      伤害/碎甲/STK（官方伤害模型）
- ``engagement``      实战 TTK 组装
- ``loadout``         配装枚举与最优求解
- ``tiering``         距离带聚合与 T0–T3 分层
"""

from src.engine.ballistics import DamageContext, expected_kill_shots
from src.engine.engagement import TtkResult, ttk_at, ttk_curve
from src.engine.game_data import GameData, load_game_data
from src.engine.loadout import LoadoutSolution, LoadoutSolver
from src.engine.tiering import GunRanking, rank_weapons_for_scenario
from src.engine.weapon_state import WeaponState, WeaponStateResolver

__all__ = [
    "GameData",
    "load_game_data",
    "WeaponState",
    "WeaponStateResolver",
    "DamageContext",
    "expected_kill_shots",
    "TtkResult",
    "ttk_at",
    "ttk_curve",
    "LoadoutSolver",
    "LoadoutSolution",
    "GunRanking",
    "rank_weapons_for_scenario",
]
