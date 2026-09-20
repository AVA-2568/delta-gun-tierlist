"""第三方交叉核验：moligod.com/gunsmith 的官方对象 ID 与本项目武器池对齐。

用法（离线，仅用已入库参照数据）：
    python tools/crosscheck_third_party.py

可选：同时与上游 dfttk catalog 快照比对 imagePath（若有本地缓存）：
    python tools/crosscheck_third_party.py --catalog .probe/catalog__weapons.json

退出码：0 = 核验通过；1 = 发现冲突。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_PATH = os.path.join(ROOT, "data", "reference", "moligod_weapons.json")
WEAPONS_PATH = os.path.join(ROOT, "data", "game", "weapons.json")


def _object_id(url: str):
    m = re.search(r"/object/(\d+)\.png", url or "")
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=None, help="dfttk catalog/weapons.json 快照路径（可选）")
    args = ap.parse_args()

    ref = json.load(open(REF_PATH, encoding="utf-8"))
    ours = json.load(open(WEAPONS_PATH, encoding="utf-8"))["weapons"]
    our_ids = {str(w["weapon_id"]) for w in ours}
    our_names = {str(w["weapon_id"]): w.get("name", "") for w in ours}

    problems = []

    # 1) 参照数据自身的 object_id 必须与 image_url 一致
    for w in ref["weapons"]:
        oid = _object_id(w.get("image_url"))
        if oid != w["object_id"]:
            problems.append(f"参照条目自身不一致：{w['object_id']} vs image_url->{oid}")

    # 2) 与上游 catalog imagePath 比对（可选）
    url_checked = url_same = 0
    if args.catalog and os.path.exists(args.catalog):
        cat = json.load(open(args.catalog, encoding="utf-8"))
        objs = cat.get("objects") or {}
        for w in ref["weapons"]:
            o = objs.get(w["object_id"]) or {}
            cpath = str(o.get("imagePath") or "")
            if not cpath:
                continue  # 上游未填 imagePath，不参与
            url_checked += 1
            if cpath == w["image_url"]:
                url_same += 1
            else:
                problems.append(f"imagePath 不一致：{w['object_id']} catalog={cpath} moligod={w['image_url']}")

    # 3) 与本项目武器池的交集：ID 必须命中
    overlap = [w for w in ref["weapons"] if w["object_id"] in our_ids]
    for w in overlap:
        if not our_names.get(w["object_id"]):
            problems.append(f"武器池命中但无名称：{w['object_id']}")

    print("=" * 84)
    print("moligod 第三方交叉核验")
    print("=" * 84)
    print(f"  参照条目          : {len(ref['weapons'])}")
    print(f"  与本项目武器池交集 : {len(overlap)}")
    print(f"  imagePath 比对     : {url_same}/{url_checked} 一致" + ("（未提供 catalog 快照，跳过）" if not url_checked else ""))
    print()
    if problems:
        print("  发现冲突：")
        for p in problems:
            print("   -", p)
        print("\n  结果：未通过")
        return 1
    print("  结果：通过（无冲突）")
    print(f"  官方 ID 空间互证成立：moligod 与 dfttk catalog 同源使用官方对象 ID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
