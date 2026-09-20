"""采集层：从上游数据集同步并归一化官方游戏数据。

唯一入口 ``game_data_sync``，产出 ``data/game/*.json``。
"""

from src.collectors.game_data_sync import sync_all

__all__ = ["sync_all"]
