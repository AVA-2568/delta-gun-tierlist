"""弹药均价表：加载手工维护的 30 天成交均价，并按 ``ammo_item_id`` 查价。

本模块只做两件事——**加载**与**查价**，不含任何计算。

价格是手工维护的第三方市场均价（非官方数据），故与 ``data/game/*``（官方同步数据）
物理隔离：来源、更新频率、可信度三者都不同，混在一起会污染 ``provenance`` 语义。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

#: 兜底币种（表缺失时渲染层仍需要一个单位名）
DEFAULT_CURRENCY = "哈夫币"

#: 期望的表格式标识；不符则整表忽略，避免误读别种 JSON
EXPECTED_SCHEMA = "ammo-price-avg-30d"


@dataclass(frozen=True)
class AmmoPriceTable:
    """弹药单发均价表（30 天成交均价，单位见 ``currency``）。"""

    currency: str = DEFAULT_CURRENCY
    window: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    prices: Mapping[str, int] = field(default_factory=dict)

    def price_for(self, ammo_item_id: str) -> Optional[int]:
        """按弹药主键查单发均价；缺价或未知 id 返回 ``None``。"""
        return self.prices.get(str(ammo_item_id))

    @property
    def is_empty(self) -> bool:
        """是否没有任何可用价格（文件缺失 / 全未填时渲染层据此调整说明文案）。"""
        return not self.prices


def _empty() -> AmmoPriceTable:
    return AmmoPriceTable()


def _coerce_price(value: Any) -> Optional[int]:
    """只接受正整数；``bool``/``float``/字符串一律视为无效（缺价）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def load_ammo_prices(path: str) -> AmmoPriceTable:
    """加载均价表。

    文件缺失、无法解析或 schema 不符时返回**空表**（不抛异常），
    使榜单在未配置价格时保持可用——成本列显示 ``—``，战斗数值完全不变。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        logger.info("未找到弹药均价表（%s），成本列将显示 —", path)
        return _empty()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("弹药均价表无法读取（%s）：%s", path, exc)
        return _empty()

    if not isinstance(raw, dict) or raw.get("schema") != EXPECTED_SCHEMA:
        logger.warning("弹药均价表 schema 不符（期望 %s），整表忽略", EXPECTED_SCHEMA)
        return _empty()

    prices: Dict[str, int] = {}
    for entry in raw.get("ammo") or []:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("ammo_item_id")
        price = _coerce_price(entry.get("price_avg_30d"))
        if not item_id or price is None:
            continue
        prices[str(item_id)] = price

    window = raw.get("window")
    return AmmoPriceTable(
        currency=str(raw.get("currency") or DEFAULT_CURRENCY),
        window=dict(window) if isinstance(window, dict) else {},
        updated_at=str(raw.get("updated_at") or ""),
        prices=prices,
    )
