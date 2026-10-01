"""采集层：官方游戏数据同步与第三方行情价格同步。

- ``game_data_sync``：同步并归一化官方游戏数据，产出 ``data/game/*.json``；
- ``orzice_price_sync``：抓取 orzice 小涛查实时行情，产出
  ``data/reference/weapon_prices.json`` 与 ``data/reference/ammo_prices.json``。
"""

from src.collectors.game_data_sync import sync_all

__all__ = ["sync_all"]
