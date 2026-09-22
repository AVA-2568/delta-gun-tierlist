"""弹药当日价格同步：onebiji「市场周期律」行情页 → ``data/reference/ammo_prices.json``。

数据源与口径（2026-09-22 修正，经玩家实测价格 4429 逐位确认）：

- 页面 ``https://www.onebiji.com/hykb_tools/sjz/mrmm/tqc.php?immgj=0`` 为全量静态 HTML，
  内嵌 JS 对象以官方 objectID 键控，含两类数据块：
  - ``o_<objectID>`` = **市场全览：交易行真实单发当日价**（本表数据源），
    且带 ``primary_class: "ammo"`` 分类与 rank3/7/14 涨跌数据；
  - ``t_<objectID>`` = 特勤处**制作成本/利润**口径（每日 8:00 更新），
    **不是**市场价格，禁止使用（曾误用导致价格整体错位一档）。
- ``o_`` 块 ``price`` 即单发哈夫币价，无组价换算。

设计要点：

- 标准库 urllib，**零第三方依赖**（与采集层一致）。
- 确定性输出：条目按 ID 排序，无时间戳漂移进数据体。
- **幂等**：解析出的价格与现表完全一致时不重写文件——git 无 diff、Actions 无空提交。
  ``updated_at`` 语义 = 「当前表内价格的抓取时间」。
- 缺价不猜测：解析失败、价格为 0、非 ``ammo`` 分类一律不入价。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SOURCE_URL = "https://www.onebiji.com/hykb_tools/sjz/mrmm/tqc.php?immgj=0"
SOURCE_NAME = "onebiji 市场周期律 · 市场全览"

#: 价格表 schema 与落盘路径
PRICE_SCHEMA = "ammo-price-daily"
DEFAULT_TABLE_PATH = os.path.join("data", "reference", "ammo_prices.json")
AMMO_CATALOG_PATH = os.path.join("data", "game", "ammo.json")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

#: 市场全览块：``"o_<objectID>":{ ... "primary_class":"ammo" ... "price":"4429" ...}``
#: ``price`` 在 rank3 嵌套对象之前出现，``[^{}]*`` 限定同一层内不跨对象。
_PRICE_RE = re.compile(
    r'"o_(\d{11})":\{[^{}]*?"primary_class":"ammo"[^{}]*?"price":"?(\d+)"?'
)


class SourceUnavailable(RuntimeError):
    """行情源不可用。"""


def fetch_page(url: str = SOURCE_URL, timeout: float = 60.0) -> str:
    """抓取行情页 HTML。"""
    request = urllib.request.Request(
        url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except Exception as exc:  # pragma: no cover - 网络异常分支
        raise SourceUnavailable(f"行情页下载失败：{type(exc).__name__} - {exc}") from exc


def parse_prices(page_html: str) -> Dict[str, int]:
    """从行情页解析 ``o_`` 市场全览块，得到单发当日价。

    只收 ``primary_class: "ammo"`` 的对象（弹药分类双保险），价格为正才入价。
    """
    prices: Dict[str, int] = {}
    for item_id, price in _PRICE_RE.findall(page_html):
        per_round = int(price)
        if per_round > 0:
            prices[item_id] = per_round
    return prices


def load_catalog_ids(path: str) -> Dict[str, Dict[str, Any]]:
    """读官方弹药目录，返回 ``ammo_item_id -> 展示元数据``（供全量表骨架）。"""
    with open(path, encoding="utf-8") as fh:
        catalog = json.load(fh)
    return {
        str(record["ammo_item_id"]): {
            "caliber": record.get("caliber") or "",
            "name": record.get("name") or "",
            "penetration_level": record.get("penetration_level"),
        }
        for record in catalog.get("ammo", [])
        if record.get("ammo_item_id")
    }


def _today_beijing() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def build_table(
    catalog: Dict[str, Dict[str, Any]],
    prices: Dict[str, int],
    fetched_date: str,
) -> Dict[str, Any]:
    """构造完整价格表：目录全量条目，命中填价，未命中 ``null``（缺价不猜测）。"""
    return {
        "schema": PRICE_SCHEMA,
        "currency": "哈夫币",
        "window": {"from": fetched_date, "to": fetched_date, "days": 1},
        "updated_at": fetched_date,
        "source": f"{SOURCE_NAME} · 交易行单发当日价（primary_class=ammo）",
        "note": (
            "自动维护：每日 GitHub Actions 抓取第三方行情并换算单发当日价；"
            "交易行无报价的弹药为 null（渲染为 —），非官方数据仅供参考"
        ),
        "ammo": [
            {
                "ammo_item_id": item_id,
                **meta,
                "price_daily": prices.get(item_id),
            }
            for item_id, meta in sorted(catalog.items())
        ],
    }


def sync(
    output_dir: str = ".",
    table_path: str = DEFAULT_TABLE_PATH,
    timeout: float = 60.0,
    fetch: Any = fetch_page,
) -> Dict[str, Any]:
    """执行同步：抓取 → 解析 → 与现表对比 → 幂等写盘。

    Returns:
        ``{"changed": bool, "matched": int, "catalog": int, "table_path": str}``
    """
    page = fetch(timeout=timeout)
    prices = parse_prices(page)

    catalog = load_catalog_ids(os.path.join(output_dir, AMMO_CATALOG_PATH))
    if not catalog:
        raise RuntimeError(f"官方弹药目录为空或缺失：{AMMO_CATALOG_PATH}")

    table = build_table(catalog, prices, _today_beijing())
    matched = sum(1 for row in table["ammo"] if row["price_daily"] is not None)

    target = os.path.join(output_dir, table_path)
    if os.path.exists(target):
        with open(target, encoding="utf-8") as fh:
            try:
                current = json.load(fh)
            except ValueError:
                current = None
        if isinstance(current, dict) and current.get("schema") == PRICE_SCHEMA:
            current_prices = {
                str(row.get("ammo_item_id")): row.get("price_daily")
                for row in current.get("ammo", [])
            }
            new_prices = {row["ammo_item_id"]: row["price_daily"] for row in table["ammo"]}
            if current_prices == new_prices and current.get("currency") == table["currency"]:
                logger.info("价格与现表一致，不重写（matched=%d）", matched)
                return {
                    "changed": False,
                    "matched": matched,
                    "catalog": len(catalog),
                    "table_path": table_path,
                }

    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(table, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    logger.info("价格表已更新：matched=%d / catalog=%d", matched, len(catalog))
    return {
        "changed": True,
        "matched": matched,
        "catalog": len(catalog),
        "table_path": table_path,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="弹药当日价格同步（onebiji 行情）")
    parser.add_argument("--output-dir", default=".", help="输出根目录（默认当前目录）")
    parser.add_argument("--table", default=DEFAULT_TABLE_PATH, help="价格表落盘路径")
    args = parser.parse_args()

    result = sync(output_dir=args.output_dir, table_path=args.table)
    state = "已更新" if result["changed"] else "无变化"
    print(
        f"价格同步完成（{state}）：官方目录 {result['catalog']} 条，"
        f"当日价命中 {result['matched']} 条 → {result['table_path']}"
    )


if __name__ == "__main__":
    main()
