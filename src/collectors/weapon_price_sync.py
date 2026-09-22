"""枪械当日价格同步：onebiji「市场周期律」行情页 → ``data/reference/weapon_prices.json``。

数据源与口径（2026-09-22）：

- 与 :mod:`src.collectors.ammo_price_sync` 同一行情页：``o_<objectID>`` 块为
  **市场全览：交易行真实当日价**；``t_`` 块为特勤处制作成本口径，禁止使用。
- 只收 ``primary_class: "weapon"`` 的对象（枪械分类双保险），``price`` 即
  该枪本体裸枪的当日哈夫币价。
- **目录对齐**：表骨架来自官方武器目录 ``data/game/weapons.json`` 的
  **本体条目**（``is_variant=false``）。官方变体只是本体预装了官方改件
  （改件在交易行按 ``attachment`` 分类出售），**不建独立条目、不计配件价**。

设计要点（与弹药同步一致）：

- 标准库 urllib，**零第三方依赖**。
- 确定性输出：条目按 weapon_id 排序，无时间戳漂移进数据体。
- **幂等**：解析出的价格与现表完全一致时不重写文件。
- 缺价不猜测：解析失败、价格为 0、非 ``weapon`` 分类一律不入价
  （交易行未上架的本体，如 MDR / 汤姆逊冲锋枪，落盘为 ``null``）。
- **缺价回填**（2026-09-22）：onebiji 未收录的本体由
  :mod:`src.collectors.zxfps_price_sync`（zxfps 三角洲工具站）补全，仅补主源缺失条目。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional

from src.collectors import zxfps_price_sync

logger = logging.getLogger(__name__)

SOURCE_URL = "https://www.onebiji.com/hykb_tools/sjz/mrmm/tqc.php?immgj=0"
SOURCE_NAME = "onebiji 市场周期律 · 市场全览"

#: 价格表 schema 与落盘路径
PRICE_SCHEMA = "weapon-price-daily"
DEFAULT_TABLE_PATH = os.path.join("data", "reference", "weapon_prices.json")
WEAPON_CATALOG_PATH = os.path.join("data", "game", "weapons.json")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

#: 市场全览块：``"o_<objectID>":{ ... "primary_class":"weapon" ... "price":"87591" ...}``
#: ``price`` 在 rank3 等嵌套对象之前出现，``[^{}]*`` 限定同一层内不跨对象。
_PRICE_RE = re.compile(
    r'"o_(\d{11})":\{[^{}]*?"primary_class":"weapon"[^{}]*?"price":"?(\d+)"?'
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
    """从行情页解析 ``o_`` 市场全览块，得到本体裸枪当日价。

    只收 ``primary_class: "weapon"`` 的对象（枪械分类双保险），价格为正才入价。
    """
    prices: Dict[str, int] = {}
    for item_id, price in _PRICE_RE.findall(page_html):
        bare_price = int(price)
        if bare_price > 0:
            prices[item_id] = bare_price
    return prices


def load_catalog_ids(path: str) -> Dict[str, Dict[str, Any]]:
    """读官方武器目录，返回 ``weapon_id -> 展示元数据``（仅本体，供全量表骨架）。

    官方变体条目（``is_variant=true``）跳过：变体 = 本体 + 预装改件，
    改件按配件口径出售、不计入枪价表。
    """
    with open(path, encoding="utf-8") as fh:
        catalog = json.load(fh)
    return {
        str(record["weapon_id"]): {
            "name": record.get("name") or "",
            "category": record.get("category") or "",
            "caliber": record.get("caliber") or "",
        }
        for record in catalog.get("weapons", [])
        if record.get("weapon_id") and not record.get("is_variant")
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
        "source": f"{SOURCE_NAME} · 交易行本体裸枪当日价（primary_class=weapon）",
        "note": (
            "自动维护：每日 GitHub Actions 抓取第三方行情的本体裸枪当日价；"
            "变体 = 本体 + 官方预装件，共用本体价（配件价不计入）；"
            "交易行无报价的枪械为 null（渲染为 —），非官方数据仅供参考"
        ),
        "weapons": [
            {
                "weapon_id": weapon_id,
                **meta,
                "price_daily": prices.get(weapon_id),
            }
            for weapon_id, meta in sorted(catalog.items())
        ],
    }


def sync(
    output_dir: str = ".",
    table_path: str = DEFAULT_TABLE_PATH,
    timeout: float = 60.0,
    fetch: Any = fetch_page,
    use_fallback: bool = True,
    zxfps_fetch: Optional[Callable[[str, list], Dict[str, int]]] = None,
) -> Dict[str, Any]:
    """执行同步：抓取 → 解析 → 缺价回填 → 与现表对比 → 幂等写盘。

    Args:
        fetch: 行情页抓取函数（测试注入用）。
        use_fallback: 主源缺价时是否用 zxfps 工具站回填。
        zxfps_fetch: 回填函数注入点（测试用），默认走真实网络。

    Returns:
        ``{"changed": bool, "matched": int, "catalog": int, "fallback": int,
        "table_path": str}``
    """
    page = fetch(timeout=timeout)
    prices = parse_prices(page)

    catalog = load_catalog_ids(os.path.join(output_dir, WEAPON_CATALOG_PATH))
    if not catalog:
        raise RuntimeError(f"官方武器目录为空或缺失：{WEAPON_CATALOG_PATH}")

    table = build_table(catalog, prices, _today_beijing())

    # ---- 缺价回填：onebiji 未收录的本体（MDR / 汤姆逊冲锋枪等）由 zxfps 补全 ----
    fallback_used = 0
    if use_fallback:
        missing = [row["weapon_id"] for row in table["weapons"] if row["price_daily"] is None]
        if missing:
            try:
                fetcher = zxfps_fetch or zxfps_price_sync.collect_missing_prices
                filled = fetcher("gun", missing) or {}
            except Exception as exc:  # noqa: BLE001 - 回填失败不致命
                logger.warning("zxfps 枪价回填失败（%s：%s），仅用主源数据", type(exc).__name__, exc)
                filled = {}
            for row in table["weapons"]:
                if row["price_daily"] is None and row["weapon_id"] in filled:
                    row["price_daily"] = int(filled[row["weapon_id"]])
                    fallback_used += 1
            if fallback_used:
                table["source"] += f"；缺价条目由 {zxfps_price_sync.SOURCE_NAME} 补全"
                table["note"] = (
                    "自动维护：每日 GitHub Actions 抓取第三方行情的本体裸枪当日价；"
                    f"主源（onebiji）缺价条目由 {zxfps_price_sync.SOURCE_NAME} 补全；"
                    "变体 = 本体 + 官方预装件，共用本体价（配件价不计入）；"
                    "无任何报价的枪械为 null（渲染为 —），非官方数据仅供参考"
                )

    matched = sum(1 for row in table["weapons"] if row["price_daily"] is not None)

    target = os.path.join(output_dir, table_path)
    if os.path.exists(target):
        with open(target, encoding="utf-8") as fh:
            try:
                current = json.load(fh)
            except ValueError:
                current = None
        if isinstance(current, dict) and current.get("schema") == PRICE_SCHEMA:
            current_prices = {
                str(row.get("weapon_id")): row.get("price_daily")
                for row in current.get("weapons", [])
            }
            new_prices = {row["weapon_id"]: row["price_daily"] for row in table["weapons"]}
            if current_prices == new_prices and current.get("currency") == table["currency"]:
                logger.info("价格与现表一致，不重写（matched=%d）", matched)
                return {
                    "changed": False,
                    "matched": matched,
                    "catalog": len(catalog),
                    "fallback": fallback_used,
                    "table_path": table_path,
                }

    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(table, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    logger.info("价格表已更新：matched=%d / catalog=%d（回填 %d 条）", matched, len(catalog), fallback_used)
    return {
        "changed": True,
        "matched": matched,
        "catalog": len(catalog),
        "fallback": fallback_used,
        "table_path": table_path,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="枪械本体裸枪当日价同步（onebiji 行情）")
    parser.add_argument("--output-dir", default=".", help="输出根目录（默认当前目录）")
    parser.add_argument("--table", default=DEFAULT_TABLE_PATH, help="价格表落盘路径")
    parser.add_argument(
        "--no-fallback", action="store_true",
        help="禁用 zxfps 缺价回填（仅用 onebiji 主源）",
    )
    args = parser.parse_args()

    result = sync(
        output_dir=args.output_dir, table_path=args.table,
        use_fallback=not args.no_fallback,
    )
    state = "已更新" if result["changed"] else "无变化"
    print(
        f"枪价同步完成（{state}）：官方目录 {result['catalog']} 把本体，"
        f"当日价命中 {result['matched']} 把（zxfps 回填 {result['fallback']} 条）"
        f" → {result['table_path']}"
    )


if __name__ == "__main__":
    main()
