"""枪械价格表：加载自动维护的本体裸枪当日价，并按 ``weapon_id`` 查价。

实现见 :mod:`src.engine.price_table`；本模块只绑定枪械表的 schema 与主键。

口径（2026-09-22 与需求方确认）：

- **本体裸枪价**：交易行该枪本体的当日价。变体/改装状态**共用本体价**——
  官方变体只是本体预装了官方改件，不存在独立的"变体枪"商品；配件价格不在维护范围。
- 预装件/改装件会影响伤害、射速等战斗属性，但这些差异体现在榜单各行的
  TTK / 击杀成本列；**裸枪价格与起枪配置无关**，同枪所有状态行同价。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.price_table import (
    DEFAULT_CURRENCY,
    PriceTable,
    load_price_table,
)

__all__ = ["DEFAULT_CURRENCY", "WeaponPriceTable", "load_weapon_prices"]

#: 期望的表格式标识；不符则整表忽略，避免误读别种 JSON
EXPECTED_SCHEMA = "weapon-price-daily"


@dataclass(frozen=True)
class WeaponPriceTable(PriceTable):
    """武器本体裸枪当日价表（第三方交易行行情，单位见 ``currency``）。"""


def load_weapon_prices(path: str) -> WeaponPriceTable:
    """加载枪价表；文件缺失 / 解析失败 / schema 不符 → 空表（不抛异常）。"""
    return load_price_table(
        path,
        schema=EXPECTED_SCHEMA,
        section="weapons",
        id_field="weapon_id",
        label="枪械价格表",
        table_cls=WeaponPriceTable,
    )
