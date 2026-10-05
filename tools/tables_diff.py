"""数据表对账工具（契约：docs/superpowers/specs/2026-10-04-data-tables-design.md 第 6 节）。

用法：
    python tools/tables_diff.py    # 人工表 data/tables/（真源）vs data/game/（上游参考层）字段级差异报告

对账口径：
- weapons：表侧按契约第 2 节展开规则展开为 61 条目后，与 data/game/weapons.json 按
  profile_key 配对，逐字段 diff（输出哪把枪的哪个字段、两侧各是什么值）；
- parts：parts/*.json 合并回 {item_id: 条目} 后与 data/game/parts.json 按 item_id 配对逐字段 diff；
- ammo / armor / scenarios：条目级 diff——ammo 按 ammo_item_id、armor 按等级键（候选清单
  按 item_id）、scenarios 按 scenario_id（weapon_pool 按 profile_key）配对；
- 有差异退出码 1，零差异退出码 0。复用 tools/migrate_tables.py 的展开规则与加载函数，
  保证对账口径与迁移校验（migrate_tables.py --check）永远一致。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import migrate_tables as mt  # noqa: E402  (复用同一套展开规则，禁止另写一份导致口径漂移)

# 单个域最多逐条打印的差异行数（超出部分只报计数，避免上游大改时刷屏）
MAX_PRINT_PER_DOMAIN = 40
# 单个值打印的最大字符数
MAX_VALUE_CHARS = 160

# 带键清单的条目配对键：路径模式（* 通配一段）→ 条目键字段。
# 其余 dict 按键配对、无键 list 按下标配对。
KEYED_LISTS = {
    ("ammo", "ammo"): "ammo_item_id",
    ("scenarios", "scenarios"): "scenario_id",
    ("scenarios", "weapon_pool"): "profile_key",
    ("armor", "levels", "*", "armor_options"): "item_id",
    ("armor", "levels", "*", "helmet_options"): "item_id",
}


def match_keyed(path: tuple) -> str | None:
    """返回该路径对应的清单条目键字段；非带键清单返回 None。"""
    for pattern, key in KEYED_LISTS.items():
        if len(pattern) == len(path) and all(p == "*" or p == seg for p, seg in zip(pattern, path)):
            return key
    return None


def render(path: tuple) -> str:
    """路径元组 → 可读字符串：'ammo[ammo_item_id=x].field'、'weapons.18010000037:base.damage'、'parts.13020000616.effects'。"""
    s = ""
    for seg in path:
        if isinstance(seg, int):  # 仅列表下标用方括号；数字字符串键（如 item_id）按普通键处理
            s += f"[{seg}]"
        elif "=" in str(seg):
            s += f"[{seg}]"
        else:
            s += f".{seg}" if s else str(seg)
    return s


def collect(a, b, path: tuple, diffs: list) -> None:
    """递归收集 a（表侧）与 b（参考层）的字段级差异，追加进 diffs。

    差异记录为 (kind, path_str, 表侧值, 参考层值)；
    kind: diff=两侧都有但值不同 / only_table=仅表侧有 / only_game=仅参考层有。
    """
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                diffs.append(("only_game", render(path + (key,)), None, b[key]))
            elif key not in b:
                diffs.append(("only_table", render(path + (key,)), a[key], None))
            else:
                collect(a[key], b[key], path + (key,), diffs)
        return
    if isinstance(a, list) and isinstance(b, list):
        key_field = match_keyed(path)
        if key_field is not None:
            collect_keyed(a, b, path, key_field, diffs)
            return
        if len(a) != len(b):
            diffs.append(("diff", f"{render(path)}（长度 {len(a)} != {len(b)}，按下标逐位比对）", len(a), len(b)))
        for i in range(max(len(a), len(b))):
            x = a[i] if i < len(a) else None
            y = b[i] if i < len(b) else None
            collect(x, y, path + (i,), diffs)
        return
    if type(a) is type(b) and a == b:  # 类型敏感（bool/int/float 不混等），与迁移校验口径一致
        return
    diffs.append(("diff", render(path), a, b))


def collect_keyed(a: list, b: list, path: tuple, key_field: str, diffs: list) -> None:
    """带键清单：按条目键字段配对后再逐字段 diff（插入/乱序不产生伪差异）。"""
    def by_key(items: list) -> dict:
        keyed: dict = {}
        for item in items:
            keyed.setdefault(str(item.get(key_field)), []).append(item)
        return keyed

    ka, kb = by_key(a), by_key(b)
    dup_a = [k for k, v in ka.items() if len(v) > 1]
    dup_b = [k for k, v in kb.items() if len(v) > 1]
    if dup_a or dup_b:
        diffs.append(("diff", f"{render(path)}（键 {key_field} 重复，退化为按下标比对）",
                      dup_a or None, dup_b or None))
        for i in range(max(len(a), len(b))):
            x = a[i] if i < len(a) else None
            y = b[i] if i < len(b) else None
            collect(x, y, path + (i,), diffs)
        return
    for k in sorted(set(ka) | set(kb)):
        item_path = path + (f"{key_field}={k}",)
        if k not in ka:
            diffs.append(("only_game", render(item_path), None, kb[k][0]))
        elif k not in kb:
            diffs.append(("only_table", render(item_path), ka[k][0], None))
        else:
            collect(ka[k][0], kb[k][0], item_path, diffs)


def fmt(value) -> str:
    if value is None:
        return "（无）"
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) > MAX_VALUE_CHARS:
        text = text[:MAX_VALUE_CHARS] + f"…（截断，全长 {len(text)} 字符）"
    return text


# ----------------------------------------------------------------- 域加载 ----

def domain_weapons():
    game = {e["profile_key"]: e for e in mt.load_json(mt.GAME_DIR / "weapons.json")["weapons"]}
    table = mt.expand_weapon_files()
    return table, game, "按 profile_key 配对，表侧按契约第 2 节展开规则展开"


def domain_parts():
    game = mt.load_json(mt.GAME_DIR / "parts.json")["parts"]
    table = {}
    for path in sorted((mt.TABLES_DIR / "parts").glob("*.json")):
        for entry in mt.load_json(path)["parts"]:
            table[entry["item_id"]] = entry
    return table, game, "按 item_id 配对，表侧为 parts/*.json 合并"


def domain_ammo():
    return (mt.load_json(mt.TABLES_DIR / "ammo.json"),
            mt.load_json(mt.GAME_DIR / "ammo.json"),
            "条目按 ammo_item_id 配对")


def domain_armor():
    return (mt.load_json(mt.TABLES_DIR / "armor.json"),
            mt.load_json(mt.GAME_DIR / "armor.json"),
            "levels 按等级键配对，armor/helmet 候选清单按 item_id 配对")


def domain_scenarios():
    return (mt.load_json(mt.TABLES_DIR / "scenarios.json"),
            mt.load_json(mt.GAME_DIR / "scenarios.json"),
            "scenarios 按 scenario_id 配对，weapon_pool 按 profile_key 配对")


DOMAINS = (
    ("weapons", domain_weapons),
    ("parts", domain_parts),
    ("ammo", domain_ammo),
    ("armor", domain_armor),
    ("scenarios", domain_scenarios),
)


# ------------------------------------------------------------------ 主流程 ----

def run() -> int:
    if not mt.TABLES_DIR.is_dir():
        print(f"错误：{mt.TABLES_DIR} 不存在，请先运行 python tools/migrate_tables.py", file=sys.stderr)
        return 1

    total = 0
    for name, loader in DOMAINS:
        try:
            table, game, pairing = loader()
        except FileNotFoundError as e:
            print(f"错误：加载 {name} 数据失败（{e}）。请确认 data/tables/ 已由 "
                  f"python tools/migrate_tables.py 生成、data/game/ 参考层完整。", file=sys.stderr)
            return 1
        diffs: list = []
        collect(table, game, (name,), diffs)
        header = f"== {name}（{pairing}）=="
        if not diffs:
            print(f"{header} 零差异")
            continue
        total += len(diffs)
        print(f"{header} {len(diffs)} 处差异")
        for kind, path_str, left, right in diffs[:MAX_PRINT_PER_DOMAIN]:
            print(f"  {path_str}")
            if kind == "diff":
                print(f"      表侧  : {fmt(left)}")
                print(f"      参考层: {fmt(right)}")
            elif kind == "only_table":
                print(f"      仅表侧有（参考层无此键）: {fmt(left)}")
            else:
                print(f"      仅参考层有（表侧无此键）: {fmt(right)}")
        if len(diffs) > MAX_PRINT_PER_DOMAIN:
            print(f"  …另有 {len(diffs) - MAX_PRINT_PER_DOMAIN} 处差异未逐条展开")

    if total:
        print(f"对账结论：共 {total} 处差异（表侧=data/tables 真源，参考层=data/game 上游）。"
              f"审阅上游变化后人工合入表侧。")
        return 1
    print("对账结论：零差异——人工表与 data/game 参考层完全一致。")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
