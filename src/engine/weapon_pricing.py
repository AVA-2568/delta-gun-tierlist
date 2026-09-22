"""枪械价格表：加载自动维护的本体裸枪当日价，并按 ``weapon_id`` 查价。

本模块只做两件事——**加载**与**查价**，不含任何计算。

价格由 :mod:`src.collectors.weapon_price_sync` 每日自动抓取第三方行情生成
（非官方数据），与 ``data/game/*``（官方同步数据）物理隔离。

口径（2026-09-22 与需求方确认）：

- **本体裸枪价**：交易行该枪本体的当日价。变体/改装状态**共用本体价**——
  官方变体只是本体预装了官方改件（改件在交易行按配件分类出售），
  不存在独立的"变体枪"商品；配件价格不在维护范围。
- 预装件/改装件会影响伤害、射速等战斗属性，但这些差异体现在榜单各行的
  TTK / 击杀成本列；**裸枪价格与起枪配置无关**，同枪所有状态行同价。
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
EXPECTED_SCHEMA = "weapon-price-daily"


@dataclass(frozen=True)
class WeaponPriceTable:
    """武器本体裸枪当日价表（第三方交易行行情，单位见 ``currency``）。"""

    currency: str = DEFAULT_CURRENCY
    window: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    prices: Mapping[str, int] = field(default_factory=dict)

    def price_for(self, weapon_id: str) -> Optional[int]:
        """按武器主键查本体裸枪当日价；缺价或未知 id 返回 ``None``。"""
        return self.prices.get(str(weapon_id))

    @property
    def is_empty(self) -> bool:
        """是否没有任何可用价格（文件缺失 / 全未填时渲染层据此调整说明文案）。"""
        return not self.prices


def _empty() -> WeaponPriceTable:
    return WeaponPriceTable()


def _coerce_price(value: Any) -> Optional[int]:
    """只接受正整数；``bool``/``float``/字符串一律视为无效（缺价）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def load_weapon_prices(path: str) -> WeaponPriceTable:
    """加载枪价表。

    文件缺失、无法解析或 schema 不符时返回**空表**（不抛异常），
    使榜单在未配置价格时保持可用——裸枪价格列显示 ``—``，战斗数值完全不变。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        logger.info("未找到枪械价格表（%s），裸枪价格列将显示 —", path)
        return _empty()
    except (OSError, ValueError) as exc:
        logger.warning("枪械价格表无法读取（%s）：%s", path, exc)
        return _empty()

    if not isinstance(raw, dict) or raw.get("schema") != EXPECTED_SCHEMA:
        logger.warning("枪械价格表 schema 不符（期望 %s），整表忽略", EXPECTED_SCHEMA)
        return _empty()

    prices: Dict[str, int] = {}
    for entry in raw.get("weapons") or []:
        if not isinstance(entry, dict):
            continue
        weapon_id = entry.get("weapon_id")
        price = _coerce_price(entry.get("price_daily"))
        if not weapon_id or price is None:
            continue
        prices[str(weapon_id)] = price

    window = raw.get("window")
    return WeaponPriceTable(
        currency=str(raw.get("currency") or DEFAULT_CURRENCY),
        window=dict(window) if isinstance(window, dict) else {},
        updated_at=str(raw.get("updated_at") or ""),
        prices=prices,
    )
