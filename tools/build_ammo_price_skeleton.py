"""生成 / 刷新弹药均价表骨架。

用法::

    python tools/build_ammo_price_skeleton.py            # 就地刷新 data/reference/ammo_prices.json
    python tools/build_ammo_price_skeleton.py --check    # 只报告差异，不写盘

**幂等保证**：``price_avg_30d`` 是唯一受保护的用户数据——已有值原样保留；
``caliber`` / ``name`` / ``penetration_level`` 属冗余辨认字段，每次从 ``ammo.json`` 刷新。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AMMO_CATALOGUE = os.path.join(ROOT, "data", "game", "ammo.json")
PRICE_TABLE = os.path.join(ROOT, "data", "reference", "ammo_prices.json")

SCHEMA = "ammo-price-avg-30d"
CURRENCY = "哈夫币"
DEFAULT_NOTE = "手工维护：price_avg_30d = 近 30 天成交均价，非实时价"


def build_skeleton(
    ammo_records: Sequence[Mapping[str, Any]],
    existing: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """按官方弹药目录重建价格表，保留已填价格。"""
    old = existing or {}
    old_rows: Dict[str, Mapping[str, Any]] = {}
    for row in old.get("ammo") or []:
        if isinstance(row, dict) and row.get("ammo_item_id"):
            old_rows[str(row["ammo_item_id"])] = row

    rows: List[Dict[str, Any]] = []
    for record in ammo_records:
        item_id = str(record.get("ammo_item_id") or "")
        if not item_id:
            continue
        previous = old_rows.get(item_id) or {}
        rows.append(
            {
                "ammo_item_id": item_id,
                "caliber": str(record.get("caliber") or ""),
                "name": str(record.get("name") or ""),
                "penetration_level": record.get("penetration_level"),
                "price_avg_30d": previous.get("price_avg_30d"),
            }
        )

    return {
        "schema": SCHEMA,
        "currency": str(old.get("currency") or CURRENCY),
        "window": dict(old.get("window") or {}),
        "updated_at": str(old.get("updated_at") or ""),
        "note": str(old.get("note") or DEFAULT_NOTE),
        "ammo": rows,
    }


def _load_json(path: str) -> Optional[Any]:
    """读取 JSON 文件；不存在或解析失败均返回 ``None``（不让「修数据的工具」因坏文件崩溃）。

    文件不存在返回 ``None`` 是既有约定（``main()`` 据此判断是否需要新建骨架）；
    解析失败也返回 ``None`` 并打印一行提示，便于用户定位坏文件。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"警告：无法读取 JSON（{path}）：{exc}")
        return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成弹药均价表骨架")
    parser.add_argument("--check", action="store_true", help="只报告差异，不写盘")
    args = parser.parse_args(argv)

    catalogue = _load_json(AMMO_CATALOGUE) or {}
    existing = _load_json(PRICE_TABLE)
    skeleton = build_skeleton(catalogue.get("ammo") or [], existing)

    filled = sum(1 for r in skeleton["ammo"] if r["price_avg_30d"] is not None)
    total = len(skeleton["ammo"])

    if args.check:
        same = existing is not None and existing.get("ammo") == skeleton["ammo"]
        print(f"弹药 {total} 款，已填价 {filled} 款；与现有表{'一致' if same else '有差异'}")
        return 0 if same else 1

    os.makedirs(os.path.dirname(PRICE_TABLE), exist_ok=True)
    with open(PRICE_TABLE, "w", encoding="utf-8") as fh:
        json.dump(skeleton, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"已写出 {PRICE_TABLE}：弹药 {total} 款，已填价 {filled} 款")
    return 0


if __name__ == "__main__":
    sys.exit(main())
