"""审计配件互斥槽位（extra_occupancy）违规。

官方 ``assembly.extraOccupancy`` 为配件声明 ``occupiedSocketIds``：装配该件后
除自身安装槽位外**同时被占用**的槽位。两个配件的占用集合相交即互斥。

采集层已把该字段固化进 `data/tables` 与 `data/game`（``extra_occupancy``），
但引擎未消费，导致三类违规：

- ``ranking``：榜单实际配装里两个玩家可选件同时占用同一槽位（游戏内装不出来）；
- ``space``：数据层声明的互斥对（枚举候选空间的静态清单，供人工核对）；
- ``official``：官方 reference_candidates 中「可选件覆盖内部默认件」的情况，
  用于确认覆盖语义（内部件应被移除，不计冲突）。

用法：
    python tools/audit_slot_occupancy.py [ranking|space|official]
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.engine.game_data import GameData  # noqa: E402
from src.engine.loadout import part_affects_ttk  # noqa: E402
from src.engine.weapon_state import build_loadout  # noqa: E402


def occupancy(weapon: Dict[str, Any], item: str) -> Set[str]:
    return {str(x) for x in (weapon.get("extra_occupancy") or {}).get(str(item), [])}


class Auditor:
    def __init__(self) -> None:
        self.gd = GameData()
        self.parts = self.gd.parts
        self.weapons = {w["profile_key"]: w for w in self.gd.weapons}

    def name(self, item: str) -> str:
        return f"{(self.parts.get(str(item)) or {}).get('name', '?')}({item})"

    def selectable(self, item: str) -> bool:
        return bool((self.parts.get(str(item)) or {}).get("selectable", True))

    def ttk(self, item: str) -> bool:
        return part_affects_ttk(self.parts.get(str(item)))

    @staticmethod
    def pairs(weapon: Dict[str, Any], mounted: Dict[str, str]) -> List[Tuple[str, str, str, str, List[str]]]:
        """mounted 中占用集相交的配件对。"""
        items = {str(s): str(i) for s, i in mounted.items()}
        sids = sorted(items, key=lambda x: int(x) if x.isdigit() else 0)
        out = []
        for i, sa in enumerate(sids):
            for sb in sids[i + 1 :]:
                a, b = items[sa], items[sb]
                if a == b:
                    continue
                inter = ({sa} | occupancy(weapon, a)) & ({sb} | occupancy(weapon, b))
                if inter:
                    out.append((sa, a, sb, b, sorted(inter, key=lambda x: int(x) if x.isdigit() else 0)))
        return out

    # ------------------------------------------------------------------ #
    def ranking(self) -> None:
        hits: Counter = Counter()
        examples: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        per_file: Counter = Counter()
        entries = 0
        for path in sorted((ROOT / "data" / "榜单").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            for entry in doc.get("weapons") or []:
                entries += 1
                weapon = self.weapons[entry["profile_key"]]
                mounted, _ = build_loadout(weapon, entry.get("loadout") or {}, parts=self.parts)
                bad = [
                    p
                    for p in self.pairs(weapon, mounted)
                    if self.selectable(p[1]) and self.selectable(p[3])
                ]
                if not bad:
                    continue
                per_file[path.name] += 1
                for sa, a, sb, b, inter in bad:
                    hits[(a, b)] += 1
                    if len(examples[(a, b)]) < 2:
                        examples[(a, b)].append(
                            f"{path.stem} | {entry['profile_key']} {entry.get('name')} | "
                            f"弹={entry.get('ammo', {}).get('name')} | loadout={entry.get('loadout')}"
                        )
        print(f"榜单条目 {entries} 条，非法配装 {sum(per_file.values())} 条：{dict(per_file)}")
        for (a, b), cnt in hits.most_common():
            print(f"  {cnt:4d}×  {self.name(a)} × {self.name(b)}")
            for ex in examples[(a, b)]:
                print(f"         {ex}")

    # ------------------------------------------------------------------ #
    def space(self) -> None:
        rows: Dict[Tuple[str, str, str], str] = {}
        for weapon in self.gd.weapons:
            candidates: Dict[str, Set[str]] = defaultdict(set)
            for socket in weapon.get("sockets") or []:
                sid = str(socket["socket_id"])
                for opt in socket.get("options") or []:
                    if self.selectable(str(opt)):
                        candidates[str(opt)].add(sid)
            for _p, sockets in (weapon.get("provider_sockets") or {}).items():
                for socket in sockets:
                    sid = str(socket["socket_id"])
                    for opt in socket.get("options") or []:
                        if self.selectable(str(opt)):
                            candidates[str(opt)].add(sid)
            items = sorted(candidates)
            for i, a in enumerate(items):
                for b in items[i + 1 :]:
                    found: Set[str] = set()
                    for sa in candidates[a]:
                        for sb in candidates[b]:
                            if sa != sb:
                                found |= ({sa} | occupancy(weapon, a)) & ({sb} | occupancy(weapon, b))
                    if found and self.ttk(a) and self.ttk(b):
                        rows[(weapon["profile_key"], a, b)] = (
                            f"{weapon['profile_key']} {weapon['display_name']}: "
                            f"{self.name(a)} × {self.name(b)} 互斥槽位"
                            f"{sorted(found, key=lambda x: int(x) if x.isdigit() else 0)}"
                        )
        print(f"数据层声明的互斥对（双方均 TTK 敏感）：{len(rows)} 对")
        print("  注：引擎已在枚举层剪枝，这些组合不会进入榜单；清单用于核对数据口径。")
        for row in rows.values():
            print("  " + row)

    # ------------------------------------------------------------------ #
    def official(self) -> None:
        total = 0
        bad_pairs: Counter = Counter()
        bad_selectable: Counter = Counter()
        for weapon in self.gd.weapons:
            for cand in weapon.get("reference_candidates") or []:
                loadout = {
                    str(e.get("slotPath")): str(e.get("itemId"))
                    for e in cand.get("loadout_config") or []
                }
                mounted, _ = build_loadout(weapon, loadout, parts=self.parts)
                total += 1
                for sa, a, sb, b, _inter in self.pairs(weapon, mounted):
                    if self.selectable(a) and self.selectable(b):
                        bad_selectable[(a, b)] += 1
                    else:
                        bad_pairs[(a, b)] += 1
        print(f"官方候选配装 {total} 条")
        print(f"  可选件互斥（应为 0）: {sum(bad_selectable.values())} 处 / {len(bad_selectable)} 对")
        for (a, b), c in bad_selectable.most_common():
            print(f"    {c:3d}× {self.name(a)} × {self.name(b)}")
        print(f"  可选件覆盖内部件（合法，需在合成时移除）: {sum(bad_pairs.values())} 处 / {len(bad_pairs)} 对")
        for (a, b), c in bad_pairs.most_common(10):
            print(f"    {c:3d}× {self.name(a)} × {self.name(b)}")


def main() -> None:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "ranking").lower()
    auditor = Auditor()
    {"ranking": auditor.ranking, "space": auditor.space, "official": auditor.official}[mode]()


if __name__ == "__main__":
    main()
