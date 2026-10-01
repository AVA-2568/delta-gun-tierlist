"""弹药价格表：加载自动维护的当日价，并按 ``ammo_item_id`` 查价。

实现见 :mod:`src.engine.price_table`；本模块只绑定弹药表的 schema 与主键。

价格由 :mod:`src.collectors.orzice_price_sync` 每日自动抓取第三方行情生成
（非官方数据），与 ``data/game/*``（官方同步数据）物理隔离。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.price_table import (
    DEFAULT_CURRENCY,
    PriceTable,
    load_price_table,
)

__all__ = ["DEFAULT_CURRENCY", "AmmoPriceTable", "load_ammo_prices"]

#: 期望的表格式标识；不符则整表忽略，避免误读别种 JSON
EXPECTED_SCHEMA = "ammo-price-daily"


@dataclass(frozen=True)
class AmmoPriceTable(PriceTable):
    """弹药单发当日价表（第三方交易行行情，单位见 ``currency``）。"""


def load_ammo_prices(path: str) -> AmmoPriceTable:
    """加载弹药均价表；文件缺失 / 解析失败 / schema 不符 → 空表（不抛异常）。"""
    return load_price_table(
        path,
        schema=EXPECTED_SCHEMA,
        section="ammo",
        id_field="ammo_item_id",
        label="弹药均价表",
        table_cls=AmmoPriceTable,
    )
