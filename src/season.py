"""当前赛季的单一来源。

赛季限定弹的「是否绝版」判定（榜单候选、价格同步护栏）必须用同一个常量，
否则榜单与价格表会对同一款弹给出互相矛盾的结论。赛季更迭时只改这里。
"""

from __future__ import annotations

CURRENT_SEASON = "S11"

__all__ = ["CURRENT_SEASON"]
