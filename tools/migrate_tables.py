"""数据表化迁移工具（契约：docs/superpowers/specs/2026-10-04-data-tables-design.md 第 1/2/3/5 节）。

用法：
    python tools/migrate_tables.py          # 从 data/game/ 生成 data/tables/（幂等可重跑）
    python tools/migrate_tables.py --check  # 校验已生成表按展开规则还原后与 data/game/ 一致

- weapons/：一枪一文件 <weapon_id>.json，{"base": {...}, "variants": [...]}；
  base 块 = 原条目剔除 profile_key/is_variant/variant_item_id/variant_item_name 四键；
  变体块 = 逐字段 diff 实测差异（以数据为准，不止契约所列两字段则全部写入并报告）。
- parts/：按 slot 分文件 <slot>.json，{"slot": ..., "parts": [按 item_id 排序的条目]}。
- ammo.json / armor.json / scenarios.json：字节级原样复制。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_DIR = ROOT / "data" / "game"
TABLES_DIR = ROOT / "data" / "tables"

# base 块剔除的四键（契约第 2 节）
STRIP_KEYS = ("profile_key", "is_variant", "variant_item_id", "variant_item_name")
# 展开规则显式补齐的键，不写入变体差异块
EXPANSION_KEYS = ("profile_key", "is_variant")
# 契约实测结论：变体与本体仅此两数据字段不同；其余差异字段属意外发现，必须打印报告
KNOWN_VARIANT_DIFF_FIELDS = ("display_name", "reference_candidates")
BYTE_COPY_FILES = ("ammo.json", "armor.json", "scenarios.json")

_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9_\-]+")


def validate_component(name: str, what: str) -> str:
    """数据侧取出的标识符用作文件名前，校验为安全组件（无路径分隔/穿越）。"""
    if not _SAFE_COMPONENT.fullmatch(name):
        raise SystemExit(f"{what} 含非法字符，拒绝用作文件名：{name!r}")
    return name


def write_json(path: Path, obj) -> None:
    """在 data/tables/ 白名单目录内写入 JSON（规范化 + 包含性校验）。"""
    resolved = path.resolve()
    allowed = TABLES_DIR.resolve()
    if allowed != resolved and allowed not in resolved.parents:
        raise SystemExit(f"拒绝写入 data/tables/ 之外的路径：{resolved}")
    text = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    resolved.write_text(text, encoding="utf-8", newline="\n")


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- weapons ----

def variant_diff_block(variant: dict, base: dict) -> dict:
    """变体条目相对本体条目的逐字段差异（剔除 profile_key 与展开规则补齐键）。"""
    block = {}
    for key, value in variant.items():
        if key == "profile_key" or key in EXPANSION_KEYS:
            continue
        if key in STRIP_KEYS or base.get(key) != value:
            block[key] = value
    # 契约示例顺序：variant_item_id / variant_item_name 置前，其余按原条目键序
    ordered = {k: block[k] for k in ("variant_item_id", "variant_item_name") if k in block}
    ordered.update({k: v for k, v in block.items() if k not in ordered})
    return ordered


def build_weapon_files() -> dict:
    """生成 data/tables/weapons/<weapon_id>.json；返回 {weapon_id: 表文件对象}。"""
    entries = load_json(GAME_DIR / "weapons.json")["weapons"]
    groups: dict[str, list[dict]] = {}
    for entry in entries:
        groups.setdefault(entry["weapon_id"], []).append(entry)
    files = {}
    for weapon_id in sorted(groups):
        validate_component(weapon_id, "weapon_id")
        group = sorted(groups[weapon_id], key=lambda e: e["profile_key"])
        bases = [e for e in group if not e["is_variant"]]
        variants = [e for e in group if e["is_variant"]]
        if len(bases) != 1:
            raise SystemExit(f"weapon {weapon_id}: 期望恰好 1 个 base 条目，实际 {len(bases)}")
        base = bases[0]
        base_block = {k: v for k, v in base.items() if k not in STRIP_KEYS}
        variant_blocks = [variant_diff_block(v, base) for v in variants]
        files[weapon_id] = {"base": base_block, "variants": variant_blocks}
    return files


def print_variant_report(files: dict) -> None:
    """变体逐字段 diff 校验报告（契约第 2 节：以数据为准）。"""
    total = sum(len(f["variants"]) for f in files.values())
    field_counts: dict[str, int] = {}
    unexpected: dict[str, list[str]] = {}
    for weapon_id, f in files.items():
        for block in f["variants"]:
            for key in block:
                field_counts[key] = field_counts.get(key, 0) + 1
                if key not in KNOWN_VARIANT_DIFF_FIELDS and key not in STRIP_KEYS:
                    unexpected.setdefault(key, []).append(weapon_id)
    known = ("display_name", "reference_candidates",
             "variant_item_id", "variant_item_name")
    print(f"[变体 diff 报告] 变体总数 {total}，差异字段频次：")
    for key, n in sorted(field_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        mark = "（契约已知）" if key in known else ""
        print(f"  {key}: {n}/{total}{mark}")
    if unexpected:
        print("  !! 发现契约两字段之外的差异字段（已一并写入变体块）：")
        for key, wids in unexpected.items():
            print(f"     {key} <- {', '.join(sorted(set(wids)))}")
    else:
        print("  契约外差异字段：无（实测与契约结论一致）")


# ------------------------------------------------------------------ parts ----

def build_part_files() -> dict:
    """生成 data/tables/parts/<slot>.json；返回 {slot: 表文件对象}。"""
    parts = load_json(GAME_DIR / "parts.json")["parts"]
    by_slot: dict[str, list[dict]] = {}
    for item_id, entry in parts.items():
        if entry["item_id"] != item_id:
            raise SystemExit(f"parts 条目键 {item_id} 与其 item_id 字段 {entry['item_id']} 不一致")
        by_slot.setdefault(entry["slot"], []).append(entry)
    files = {}
    for slot in sorted(by_slot):
        validate_component(slot, "slot")
        entries = sorted(by_slot[slot], key=lambda e: e["item_id"])
        files[slot] = {"slot": slot, "parts": entries}
    return files


def print_slot_report(files: dict) -> None:
    print(f"[槽位分布] 共 {len(files)} 个槽位文件：")
    for slot in sorted(files, key=lambda s: (-len(files[s]["parts"]), s)):
        print(f"  {slot}: {len(files[slot]['parts'])}")


# ------------------------------------------------------------------ write ----

def generate() -> None:
    (TABLES_DIR / "weapons").mkdir(parents=True, exist_ok=True)
    (TABLES_DIR / "parts").mkdir(parents=True, exist_ok=True)
    # 清掉两个生成目录内的旧文件，保证重跑后目录内容与源完全对应（幂等）
    for subdir in ("weapons", "parts"):
        for stale in (TABLES_DIR / subdir).glob("*.json"):
            stale.unlink()

    weapon_files = build_weapon_files()
    for weapon_id, obj in weapon_files.items():
        write_json(TABLES_DIR / "weapons" / f"{weapon_id}.json", obj)

    part_files = build_part_files()
    for slot, obj in part_files.items():
        write_json(TABLES_DIR / "parts" / f"{slot}.json", obj)

    for name in BYTE_COPY_FILES:
        shutil.copyfile(GAME_DIR / name, TABLES_DIR / name)

    n_weapons = len(weapon_files)
    n_variants = sum(len(f["variants"]) for f in weapon_files.values())
    n_parts = sum(len(f["parts"]) for f in part_files.values())
    print(f"已生成 data/tables/：weapons {n_weapons} 文件（含 {n_variants} 变体）、"
          f"parts {len(part_files)} 文件（{n_parts} 条）、"
          f"{', '.join(BYTE_COPY_FILES)} 字节级复制")

    print_variant_report(weapon_files)
    print_slot_report(part_files)


# ------------------------------------------------------------------ check ----

def deep_equal(a, b, path: str, errors: list) -> bool:
    """逐键逐值相等（含嵌套结构与浮点）；标量要求类型一致（bool/int/float 不混等）。"""
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            errors.append(f"{path}: 键集合不一致，仅左 {sorted(set(a) - set(b))}，仅右 {sorted(set(b) - set(a))}")
            return False
        ok = True
        for key in a:
            ok = deep_equal(a[key], b[key], f"{path}.{key}", errors) and ok
        return ok
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            errors.append(f"{path}: 长度不一致 {len(a)} != {len(b)}")
            return False
        ok = True
        for i, (x, y) in enumerate(zip(a, b)):
            ok = deep_equal(x, y, f"{path}[{i}]", errors) and ok
        return ok
    if type(a) is type(b) and a == b:
        return True
    errors.append(f"{path}: {a!r} != {b!r}（类型 {type(a).__name__} vs {type(b).__name__}）")
    return False


def expand_weapon_files() -> dict:
    """按契约第 2 节展开规则还原 61 条目 → {profile_key: 条目}。"""
    expanded = {}
    for path in sorted((TABLES_DIR / "weapons").glob("*.json")):
        table = load_json(path)
        base_block = table["base"]
        weapon_id = base_block["weapon_id"]
        base_entry = dict(base_block)
        base_entry.update({
            "profile_key": f"{weapon_id}:base",
            "is_variant": False,
            "variant_item_id": None,
            "variant_item_name": None,
        })
        expanded[base_entry["profile_key"]] = base_entry
        for block in table["variants"]:
            entry = dict(base_block)
            entry.update(block)
            entry.update({
                "profile_key": f"{weapon_id}:{block['variant_item_id']}",
                "is_variant": True,
            })
            expanded[entry["profile_key"]] = entry
    return expanded


def check() -> int:
    if not TABLES_DIR.is_dir():
        print(f"错误：{TABLES_DIR} 不存在，请先运行 python tools/migrate_tables.py", file=sys.stderr)
        return 1

    failed = False

    # weapons：展开后与 data/game/weapons.json 按 profile_key 配对逐键逐值相等
    game_weapons = {e["profile_key"]: e for e in load_json(GAME_DIR / "weapons.json")["weapons"]}
    table_weapons = expand_weapon_files()
    if set(game_weapons) != set(table_weapons):
        failed = True
        only_game = sorted(set(game_weapons) - set(table_weapons))
        only_table = sorted(set(table_weapons) - set(game_weapons))
        print(f"[FAIL] weapons profile_key 集合不一致：仅 game 侧 {only_game}，仅表侧 {only_table}")
    else:
        errors: list[str] = []
        deep_equal(game_weapons, table_weapons, "weapons", errors)
        n = len(game_weapons)
        if errors:
            failed = True
            print(f"[FAIL] weapons 逐键逐值不相等（{n} 条配对）：")
            for err in errors[:20]:
                print(f"  {err}")
        else:
            print(f"[OK] weapons：{n} 条目展开还原后逐键逐值相等")

    # parts：全部槽位文件合并回 {item_id: 条目} 后逐键逐值相等
    game_parts = load_json(GAME_DIR / "parts.json")["parts"]
    table_parts = {}
    for path in sorted((TABLES_DIR / "parts").glob("*.json")):
        table = load_json(path)
        for entry in table["parts"]:
            if entry["item_id"] in table_parts:
                failed = True
                print(f"[FAIL] parts 条目 {entry['item_id']} 在多个槽位文件中重复")
            table_parts[entry["item_id"]] = entry
    if len(table_parts) != len(game_parts):
        failed = True
        print(f"[FAIL] parts 条目数不一致：表侧 {len(table_parts)} != game 侧 {len(game_parts)}")
    errors = []
    deep_equal(game_parts, table_parts, "parts", errors)
    if errors:
        failed = True
        print(f"[FAIL] parts 逐键逐值不相等（{len(game_parts)} 条配对）：")
        for err in errors[:20]:
            print(f"  {err}")
    elif not failed:
        print(f"[OK] parts：{len(table_parts)} 条合并还原后逐键逐值相等")

    # ammo / armor / scenarios：逐字节一致
    for name in BYTE_COPY_FILES:
        game_bytes = (GAME_DIR / name).read_bytes()
        table_path = TABLES_DIR / name
        if not table_path.is_file():
            failed = True
            print(f"[FAIL] {name}: 缺少 data/tables/{name}")
        elif table_path.read_bytes() != game_bytes:
            failed = True
            print(f"[FAIL] {name}: 与 data/game/{name} 逐字节不一致")
        else:
            print(f"[OK] {name}: 逐字节一致")

    if failed:
        print("--check 失败", file=sys.stderr)
        return 1
    print("--check 全部通过")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="data/game/ -> data/tables/ 无损迁移（契约 2026-10-04）")
    parser.add_argument("--check", action="store_true",
                        help="校验已生成表按展开规则还原后与 data/game/ 一致")
    args = parser.parse_args()
    if args.check:
        return check()
    generate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
