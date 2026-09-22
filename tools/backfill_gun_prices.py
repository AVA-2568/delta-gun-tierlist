"""存量榜单 JSON 回填裸枪价字段（免重算）。

背景：``data/榜单/*.json`` 由重算管线产出（束搜索，本地跑一次很贵）。
新增「裸枪价格 / 裸枪+180发备弹」后，用本工具把枪价直接注入**已有** payload：

- ``weapon_price_meta``（顶层）：来自枪价表（含 ``spare_ammo_rounds``）；
- ``weapons[].gun_price_daily``：本体裸枪当日价（按 ``weapon_id`` 查表）；
- ``weapons[].full_price_180rd``：裸枪价 + 180 × 该行 ``ammo.price_daily``。

注入逻辑与 ``tiering.to_export`` / ``tiering.compute_full_price`` 完全同源
（直接复用引擎函数），保证 CI 全量重算后字段逐位一致、本工具幂等可重跑。

用法::

    python tools/backfill_gun_prices.py            # 回填 data/榜单/*.json
    python tools/backfill_gun_prices.py --dry-run  # 只报告将写入的变化
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.tiering import SPARE_AMMO_ROUNDS, compute_full_price  # noqa: E402
from src.engine.weapon_pricing import DEFAULT_CURRENCY, load_weapon_prices  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = os.path.join("data", "榜单")
DEFAULT_TABLE_PATH = os.path.join("data", "reference", "weapon_prices.json")


def _backfill_payload(payload: dict, table) -> bool:
    """原地注入价格字段；返回 payload 是否发生变化。"""
    meta = {
        "currency": table.currency if table is not None else DEFAULT_CURRENCY,
        "window": dict(table.window) if table is not None else {},
        "updated_at": table.updated_at if table is not None else "",
        "available": bool(table is not None and not table.is_empty),
        "spare_ammo_rounds": SPARE_AMMO_ROUNDS,
    }
    changed = payload.get("weapon_price_meta") != meta
    payload["weapon_price_meta"] = meta

    for weapon in payload.get("weapons") or []:
        gun_price = (
            table.price_for(str(weapon.get("weapon_id")))
            if table is not None
            else None
        )
        ammo_price = (weapon.get("ammo") or {}).get("price_daily")
        full_price = compute_full_price(gun_price, ammo_price)
        if weapon.get("gun_price_daily") != gun_price:
            changed = True
            weapon["gun_price_daily"] = gun_price
        if weapon.get("full_price_180rd") != full_price:
            changed = True
            weapon["full_price_180rd"] = full_price
    return changed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="存量榜单 JSON 回填裸枪价字段（幂等）")
    parser.add_argument("--output-dir", default=".", help="仓库根目录（默认当前目录）")
    parser.add_argument("--table", default=DEFAULT_TABLE_PATH, help="枪价表路径")
    parser.add_argument("--dry-run", action="store_true", help="只报告变化，不写盘")
    args = parser.parse_args()

    table = load_weapon_prices(os.path.join(args.output_dir, args.table))
    if table.is_empty:
        logger.warning("枪价表为空或缺失（%s）——回填只会写入 available=false 的占位元数据", args.table)

    pattern = os.path.join(args.output_dir, DEFAULT_DATA_DIR, "*.json")
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise SystemExit(f"未找到榜单 JSON：{pattern}")

    written = 0
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        if not _backfill_payload(payload, table):
            logger.info("无变化，跳过：%s", path)
            continue
        if args.dry_run:
            logger.info("[dry-run] 将更新：%s", path)
            written += 1
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        logger.info("已回填：%s", path)
        written += 1

    action = "将更新" if args.dry_run else "已回填"
    print(f"回填完成（{action} {written}/{len(paths)} 个情景 JSON；"
          f"枪价表 matched={len(table.prices)}）")


if __name__ == "__main__":
    main()
