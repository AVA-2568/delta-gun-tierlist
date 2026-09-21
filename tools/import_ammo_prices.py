# -*- coding: utf-8 -*-
"""把第三方抓取的弹药价格按名称匹配到官方 ammo_item_id，并写入均价表。

用法::

    python tools/import_ammo_prices.py <scraped.json>            # dry-run，只报告匹配情况
    python tools/import_ammo_prices.py <scraped.json> --write    # 实际写盘

设计要点
--------
- **幂等**：已填的 `price_avg_30d` 会被本次抓取到的值**覆盖**（这是刷新语义，与骨架脚本的
  「保护人工填写」不同——本脚本的输入就是新的权威价源）。未匹配到的弹药保持原值不动。
- **零价即缺价**：抓取结果中价格为 0（站点尚未形成有效报价）视为缺价，写 `null`。
- 官方目录 `name` 与站点显示名存在排版差异（空格/连字符/中文），故用归一化键匹配。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AMMO_CATALOGUE = os.path.join(ROOT, "data", "game", "ammo.json")
PRICE_TABLE = os.path.join(ROOT, "data", "reference", "ammo_prices.json")

_NOISE = re.compile(r"[\s\-_.+/]+")
#: 站点在口径后带 ``mm`` 后缀（如 ``12.7x55mm``），官方目录不带（``12.7x55``）。
_MM_SUFFIX = re.compile(r"(\d)mm(?=[^\d]|$)")
#: 中英文引号统一，避免「鼠弹」这类带引号的名称因引号形态不同而漏匹配。
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "「": '"', "」": '"'})


def normalize(text: Any) -> str:
    """归一化弹药名：统一引号、去 ``mm`` 口径后缀、去空白/连字符等、转小写。

    只抹平**同一弹药的不同书写方式**，不做模糊近似——不同弹种（如 7mm 与 8.5mm 鹿弹）
    必须保持可区分，否则会把错误的价格填进去。
    """
    value = str(text or "").translate(_QUOTES)
    value = _MM_SUFFIX.sub(r"\1", value)
    return _NOISE.sub("", value).lower()


def build_keys(caliber: Any, name: Any) -> List[str]:
    """一个弹药可被多个键命中（口径+名、仅名），提高匹配率。"""
    joined = normalize(f"{caliber}{name}")
    keys = [joined]
    only_name = normalize(name)
    if only_name and only_name != joined:
        keys.append(only_name)
    return keys


def load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def match_prices(
    catalogue: Sequence[Mapping[str, Any]],
    scraped: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[str], List[str]]:
    """返回 (ammo_item_id -> 匹配到的站点条目, 目录中未匹配的弹药名, 站点中未用上的名称)。

    两级匹配：
    1. **名称匹配**——归一化后完全相等（含 ``mm`` / 引号 / 空格差异的抹平）。
    2. **等级匹配**——站点对少数口径用「口径_等级」写法（如 ``.300BLK_5``），
       此时按「口径 + 穿透等级 + 是否亚音速(SUB)」定位官方弹药。
       **仅在该组合唯一时匹配**；有多个候选（如同口径同等级有两款普通弹）则放弃，
       宁可留空也不填错价格。
    """
    index: Dict[str, Mapping[str, Any]] = {}
    for row in scraped:
        for key in build_keys("", row.get("name")):
            index.setdefault(key, row)

    matched: Dict[str, Dict[str, Any]] = {}
    unmatched: List[str] = []
    used: set = set()

    # ---- 第 2 级：站点「口径_等级」写法 -> 官方弹药（唯一才用）----
    by_level: Dict[Tuple[str, int, bool], List[Mapping[str, Any]]] = {}
    for record in catalogue:
        cal = normalize(record.get("caliber"))
        level = record.get("penetration_level")
        if not cal or not isinstance(level, int):
            continue
        is_sub = "sub" in normalize(record.get("name"))
        by_level.setdefault((cal, level, is_sub), []).append(record)

    level_lookup: Dict[str, str] = {}
    for row in scraped:
        site = str(row.get("name") or "")
        m = re.fullmatch(r"\s*(.+?)\s*(SUB)?_(\d+)\s*", site, flags=re.I)
        if not m:
            continue
        cal = normalize(m.group(1))
        is_sub = bool(m.group(2))
        level = int(m.group(3))
        candidates = by_level.get((cal, level, is_sub), [])
        if len(candidates) == 1:
            level_lookup[str(candidates[0]["ammo_item_id"])] = site

    for record in catalogue:
        item_id = str(record.get("ammo_item_id") or "")
        if not item_id:
            continue

        hit = None
        for key in build_keys(record.get("caliber"), record.get("name")):
            if key in index:
                hit = index[key]
                break

        if hit is None and item_id in level_lookup:
            site_name = level_lookup[item_id]
            hit = next(r for r in scraped if str(r.get("name")) == site_name)

        if hit is None:
            unmatched.append(f"{record.get('caliber')} {record.get('name')}".strip())
            continue

        matched[item_id] = dict(hit)
        used.add(normalize(hit.get("name")))

    unused = [str(r.get("name")) for r in scraped if normalize(r.get("name")) not in used]
    return matched, unmatched, unused


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="导入第三方弹药价格到均价表")
    parser.add_argument("scraped", help="抓取结果 JSON 路径")
    parser.add_argument("--write", action="store_true", help="实际写盘（默认只报告）")
    args = parser.parse_args(argv)

    catalogue = load_json(AMMO_CATALOGUE).get("ammo") or []
    scraped_doc = load_json(args.scraped)
    scraped = scraped_doc.get("items") or []

    matched, unmatched, unused = match_prices(catalogue, scraped)

    priced = 0
    price_map: Dict[str, Optional[int]] = {}
    for item_id, row in matched.items():
        value = row.get("d30")
        if isinstance(value, (int, float)) and value > 0:
            price_map[item_id] = int(value)
            priced += 1
        else:
            price_map[item_id] = None

    print(f"官方目录弹药    : {len(catalogue)}")
    print(f"站点抓取条目    : {len(scraped)}")
    print(f"匹配成功        : {len(matched)}（其中有有效 30 日价 {priced} 条）")
    print(f"目录未匹配      : {len(unmatched)}")

    if unmatched:
        print("\n--- 官方目录中未匹配到价格的弹药 ---")
        for name in unmatched:
            print(f"  {name}")
    if unused:
        print(f"\n--- 站点上有但官方目录未引用的条目（{len(unused)} 条）---")
        for name in unused:
            print(f"  {name}")

    if not args.write:
        print("\n[dry-run] 未写盘。加 --write 生效。")
        return 0

    table = load_json(PRICE_TABLE)
    original = {str(r.get("ammo_item_id")): r for r in (table.get("ammo") or [])}
    updated = 0
    for row in table.get("ammo") or []:
        item_id = str(row.get("ammo_item_id") or "")
        if item_id in price_map:
            row["price_avg_30d"] = price_map[item_id]
            updated += 1
    table["source"] = f"orzice.com/v/ammo（30 日价格档）· 抓取于 {scraped_doc.get('fetched_at', '')}"
    table["updated_at"] = str(scraped_doc.get("fetched_at") or "")
    table["window"] = {
        "from": str(scraped_doc.get("fetched_at") or ""),
        "to": str(scraped_doc.get("fetched_at") or ""),
        "days": 30,
    }
    table["note"] = (
        "自动导入：price_avg_30d = 第三方站点「30 日价格」档（30 天前成交价），非实时价，"
        "亦非严格的 30 天滚动均价"
    )

    with open(PRICE_TABLE, "w", encoding="utf-8") as fh:
        json.dump(table, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    print(f"\n已写入 {PRICE_TABLE}：更新 {updated} 条（表内共 {len(original)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
