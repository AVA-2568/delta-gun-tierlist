"""配件价格表：加载自动维护的配件交易行当日价，并按 ``part_id`` 查价。

实现见 :mod:`src.engine.price_table`；本模块只绑定配件表的 schema 与主键。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.price_table import (
    DEFAULT_CURRENCY,
    PriceTable,
    load_price_table,
)

__all__ = ["DEFAULT_CURRENCY", "PartPriceTable", "load_part_prices"]

#: 期望的表格式标识；不符则整表忽略，避免误读别种 JSON
EXPECTED_SCHEMA = "part-price-daily"


@dataclass(frozen=True)
class PartPriceTable(PriceTable):
    """配件当日价表（第三方交易行行情，单位见 ``currency``）。"""


def load_part_prices(path: str) -> PartPriceTable:
    """加载配件价格表；文件缺失 / 解析失败 / schema 不符 → 空表（不抛异常）。"""
    return load_price_table(
        path,
        schema=EXPECTED_SCHEMA,
        section="parts",
        id_field="part_id",
        label="配件价格表",
        table_cls=PartPriceTable,
    )
