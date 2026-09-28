"""泛型价格表：加载自动维护的第三方行情当日价，并按主键查价。

本模块只做两件事——**加载**与**查价**，不含任何计算。

弹药表与枪械表共用本实现，仅 schema 标识、JSON 分段键与主键字段名不同；
两者的领域常量与类型名分别保留在 :mod:`src.engine.ammo_pricing` 与
:mod:`src.engine.weapon_pricing` 中。

价格由 ``src/collectors`` 下的同步器每日抓取第三方行情生成（非官方数据），
与 ``data/game/*``（官方同步数据）物理隔离：来源、更新频率、可信度三者都不同，
混在一起会污染 ``provenance`` 语义。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Type

logger = logging.getLogger(__name__)

#: 兜底币种（表缺失时渲染层仍需要一个单位名）
DEFAULT_CURRENCY = "哈夫币"


@dataclass(frozen=True)
class PriceTable:
    """第三方行情当日价表（单位见 ``currency``）。"""

    currency: str = DEFAULT_CURRENCY
    window: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    prices: Mapping[str, int] = field(default_factory=dict)

    def price_for(self, key: str) -> Optional[int]:
        """按主键查价；缺价或未知 id 返回 ``None``。"""
        return self.prices.get(str(key))

    @property
    def is_empty(self) -> bool:
        """是否没有任何可用价格（文件缺失 / 全未填时渲染层据此调整说明文案）。"""
        return not self.prices


def coerce_price(value: Any) -> Optional[int]:
    """只接受正整数；``bool``/``float``/字符串一律视为无效（缺价）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def load_price_table(
    path: str,
    *,
    schema: str,
    section: str,
    id_field: str,
    label: str,
    table_cls: Type[PriceTable] = PriceTable,
) -> PriceTable:
    """加载价格表。

    文件缺失、无法解析或 schema 不符时返回**空表**（不抛异常），
    使榜单在未配置价格时保持可用——对应列显示 ``—``，战斗数值完全不变。

    ``label`` 仅用于日志文案；``table_cls`` 决定返回的具体类型，
    使调用方保留各自的类型名。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        logger.info("未找到%s（%s），对应列将显示 —", label, path)
        return table_cls()
    except (OSError, ValueError) as exc:
        logger.warning("%s无法读取（%s）：%s", label, path, exc)
        return table_cls()

    if not isinstance(raw, dict) or raw.get("schema") != schema:
        logger.warning("%s schema 不符（期望 %s），整表忽略", label, schema)
        return table_cls()

    prices: Dict[str, int] = {}
    for entry in raw.get(section) or []:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get(id_field)
        price = coerce_price(entry.get("price_daily"))
        if not item_id or price is None:
            continue
        prices[str(item_id)] = price

    window = raw.get("window")
    return table_cls(
        currency=str(raw.get("currency") or DEFAULT_CURRENCY),
        window=dict(window) if isinstance(window, dict) else {},
        updated_at=str(raw.get("updated_at") or ""),
        prices=prices,
    )
