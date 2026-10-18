"""游戏数据的加载与索引层（只读，不做任何战斗推导）。

数据来源（ADR-0004：``data/tables/`` 是唯一运行期真源）：

- 人工真源 ``data/tables/``：weapons（一枪一文件按第 2 节展开）/ parts（按槽位
  文件合并）/ ammo / armor / scenarios。引擎与价格同步都只读它。
- 上游参考层 ``data/game/``：profiles / mechanism / validation_samples / provenance
  （官方机制的结构性固化，冻结维护，引擎继续读取）。其余表域文件在
  ``data/game/`` 中降为只读审计快照，仅 ``tools/migrate_tables.py --check`` /
  ``tools/tables_diff.py`` 逐键对账用，运行期不再读取。

``tables_dir`` 默认取模块级 :data:`TABLES_DIR`（运行时读取，便于测试 monkeypatch）；
显式传参可指向别的表目录。表域字段与审计快照的逐键相等由 ``migrate_tables
--check`` 承担，常驻测试只钉结构与来源（``tests/test_tables.py``）。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from src.engine.curves import CurveLibrary

DEFAULT_DATA_DIR = os.path.join("data", "game")
#: 人工维护的数据表真源（仓库根定位，不随 data_dir 变化）
TABLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "tables",
)
_TABLES_HINT = "python tools/migrate_tables.py"
_GAME_HINT = "python -m src.collectors.game_data_sync"


class GameData:
    """对齐游戏数据集的只读视图。"""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR, tables_dir: Optional[str] = None):
        self.data_dir = data_dir
        # 默认值在运行时读取模块级常量：测试 monkeypatch ``TABLES_DIR`` 后仍然生效
        self.tables_dir = tables_dir or TABLES_DIR
        self._cache: Dict[str, Any] = {}
        self.weapons: List[Dict[str, Any]] = self._load_table_weapons()
        self.ammo: List[Dict[str, Any]] = self._load("ammo.json", self.tables_dir, hint=_TABLES_HINT).get("ammo", [])
        self.armor: Dict[str, Any] = self._load("armor.json", self.tables_dir, hint=_TABLES_HINT)
        self.parts: Dict[str, Dict[str, Any]] = self._load_table_parts()
        self.profiles: Dict[str, Dict[str, Any]] = self._load("profiles.json").get("profiles", {})
        self.mechanism: Dict[str, Any] = self._load("mechanism.json")
        self.scenarios_raw: Dict[str, Any] = self._load("scenarios.json", self.tables_dir, hint=_TABLES_HINT)
        self.validation_samples: Dict[str, Any] = self._load("validation_samples.json").get("samples", {})
        self.provenance: Dict[str, Any] = self._load("provenance.json")

        self.curves = CurveLibrary(self.mechanism.get("curves", {}))

        self.weapon_by_profile_key: Dict[str, Dict[str, Any]] = {
            weapon["profile_key"]: weapon for weapon in self.weapons
        }
        self.ammo_by_id: Dict[str, Dict[str, Any]] = {record["ammo_item_id"]: record for record in self.ammo}
        self.ammo_by_type: Dict[str, List[Dict[str, Any]]] = {}
        for record in self.ammo:
            self.ammo_by_type.setdefault(record["ammo_type_id"], []).append(record)
        for records in self.ammo_by_type.values():
            records.sort(key=lambda r: (r["penetration_level"], r["ammo_item_id"]))

    # ------------------------------------------------------------------ #
    def _load(self, filename: str, directory: Optional[str] = None, hint: str = _GAME_HINT) -> Any:
        directory = self.data_dir if directory is None else directory
        path = os.path.join(directory, filename)
        if path in self._cache:
            return self._cache[path]
        if not os.path.exists(path):
            raise FileNotFoundError(f"缺少数据文件 {path}，请先运行 `{hint}`")
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self._cache[path] = payload
        return payload

    def _load_table_weapons(self) -> List[Dict[str, Any]]:
        """从 data/tables/weapons/ 按契约第 2 节展开规则还原 61 条目。

        base 条目   = base 块 + {profile_key: "<weapon_id>:base", is_variant: false,
                                  variant_item_id: null, variant_item_name: null}
        变体条目   = copy(base 块) + 变体差异块覆盖
                    + {profile_key: "<weapon_id>:<variant_item_id>", is_variant: true}

        顺序：weapon_id 升序、base 先于变体（与原 weapons.json 一致）。
        """
        weapons_dir = os.path.join(self.tables_dir, "weapons")
        if not os.path.isdir(weapons_dir):
            raise FileNotFoundError(
                f"缺少枪械表目录 {weapons_dir}，请先运行 `{_TABLES_HINT}`"
            )
        weapons: List[Dict[str, Any]] = []
        for filename in sorted(os.listdir(weapons_dir)):
            if not filename.endswith(".json"):
                continue
            table = self._load(filename, weapons_dir, hint=_TABLES_HINT)
            base_block = table.get("base")
            if not isinstance(base_block, dict):
                raise ValueError(f"枪械表 {filename} 缺少 base 块")
            weapon_id = base_block["weapon_id"]
            base = dict(base_block)
            base.update(
                {
                    "profile_key": f"{weapon_id}:base",
                    "is_variant": False,
                    "variant_item_id": None,
                    "variant_item_name": None,
                }
            )
            weapons.append(base)
            for block in table.get("variants") or []:
                entry = dict(base_block)
                entry.update(block)
                entry["profile_key"] = f"{weapon_id}:{block['variant_item_id']}"
                entry["is_variant"] = True
                weapons.append(entry)
        if not weapons:
            raise FileNotFoundError(f"枪械表目录 {weapons_dir} 为空，请先运行 `{_TABLES_HINT}`")
        return weapons

    def _load_table_parts(self) -> Dict[str, Dict[str, Any]]:
        """合并 data/tables/parts/ 全部槽位文件为 {item_id: 条目}（契约第 3 节）。"""
        parts_dir = os.path.join(self.tables_dir, "parts")
        if not os.path.isdir(parts_dir):
            raise FileNotFoundError(
                f"缺少配件表目录 {parts_dir}，请先运行 `{_TABLES_HINT}`"
            )
        parts: Dict[str, Dict[str, Any]] = {}
        for filename in sorted(os.listdir(parts_dir)):
            if not filename.endswith(".json"):
                continue
            table = self._load(filename, parts_dir, hint=_TABLES_HINT)
            for entry in table.get("parts") or []:
                item_id = entry["item_id"]
                if item_id in parts:
                    raise ValueError(f"配件 {item_id} 在多个槽位文件中重复")
                parts[item_id] = entry
        if not parts:
            raise FileNotFoundError(f"配件表目录 {parts_dir} 为空，请先运行 `{_TABLES_HINT}`")
        return parts

    # ------------------------------------------------------------------ #
    def get_weapon(self, profile_key: str) -> Dict[str, Any]:
        try:
            return self.weapon_by_profile_key[profile_key]
        except KeyError as exc:
            raise KeyError(f"未收录的武器 profile_key：{profile_key}") from exc

    def get_part(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.parts.get(str(item_id))

    def get_profile(self, profile_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """取 profile 库条目（散布/后坐/机动/瞄具/弹道）。

        配件可通过 ``Initial`` 修饰符把武器默认 profile 换成自带 profile，
        求值链因此必须能按 id 查库。
        """
        if not profile_id:
            return None
        return self.profiles.get(str(profile_id))

    def get_ammo(self, ammo_item_id: str) -> Dict[str, Any]:
        try:
            return self.ammo_by_id[str(ammo_item_id)]
        except KeyError as exc:
            raise KeyError(f"未收录的弹药：{ammo_item_id}") from exc

    def ammo_for_weapon(self, weapon: Dict[str, Any]) -> List[Dict[str, Any]]:
        """按武器弹药类型取可用弹药，按穿透等级升序。"""
        return list(self.ammo_by_type.get(weapon["ammo_type_id"], []))

    def ammo_at_level(self, weapon: Dict[str, Any], level: int) -> Optional[Dict[str, Any]]:
        """取该武器口径下指定穿透等级的弹药；同等级有多款时取 ``ammo_item_id`` 最小者。"""
        candidates = [a for a in self.ammo_for_weapon(weapon) if a["penetration_level"] == level]
        if not candidates:
            return None
        candidates.sort(key=lambda a: (-a["penetration_level"], a["ammo_item_id"]))
        return candidates[0]

    def defense(self, level: int) -> Optional[Dict[str, Any]]:
        return (self.armor.get("levels") or {}).get(str(level))


def load_game_data(data_dir: str = DEFAULT_DATA_DIR, tables_dir: Optional[str] = None) -> GameData:
    return GameData(data_dir=data_dir, tables_dir=tables_dir)


# --------------------------------------------------------------------------- #
# 表目录的轻量目录视图（价格同步的骨架来源，不展开武器变体）
# --------------------------------------------------------------------------- #
def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_weapon_catalog(tables_dir: str) -> Dict[str, Dict[str, Any]]:
    """读 ``tables_dir/weapons/*.json`` 的 ``base`` 块，返回 ``weapon_id -> 展示元数据``。

    只取本体：变体 = 本体 + 预装改件，不存在独立的"变体枪"商品，同枪所有
    状态行共用本体价（:func:`GameData._load_table_weapons` 的展开逻辑不在此重复）。
    """
    weapons_dir = os.path.join(tables_dir, "weapons")
    if not os.path.isdir(weapons_dir):
        raise FileNotFoundError(f"缺少枪械表目录 {weapons_dir}，请先运行 `{_TABLES_HINT}`")
    catalog: Dict[str, Dict[str, Any]] = {}
    for filename in sorted(os.listdir(weapons_dir)):
        if not filename.endswith(".json"):
            continue
        base = _read_json(os.path.join(weapons_dir, filename)).get("base") or {}
        weapon_id = base.get("weapon_id")
        if not weapon_id:
            continue
        catalog[str(weapon_id)] = {
            "name": base.get("name") or "",
            "category": base.get("category") or "",
            "caliber": base.get("caliber") or "",
        }
    return catalog


def load_ammo_catalog(tables_dir: str) -> Dict[str, Dict[str, Any]]:
    """读 ``tables_dir/ammo.json``，返回 ``ammo_item_id -> 展示元数据``。

    表侧已剔除被合并的历史条目，此处不再做二次过滤（引擎不反向依赖采集层）。
    """
    records = _read_json(os.path.join(tables_dir, "ammo.json")).get("ammo", [])
    return {
        str(record["ammo_item_id"]): {
            "caliber": record.get("caliber") or "",
            "name": record.get("name") or "",
            "penetration_level": record.get("penetration_level"),
            "is_season_limited": bool(record.get("is_season_limited")),
            "season_note": record.get("season_note"),
        }
        for record in records
        if record.get("ammo_item_id")
    }


def load_part_catalog(tables_dir: str) -> Dict[str, Dict[str, Any]]:
    """合并 ``tables_dir/parts/*.json`` 的 ``parts`` 数组，返回 ``part_id -> 展示元数据``。

    配件表目录缺失时返回 ``{}``（配件价格表是可选产物，缺失不阻塞枪械/弹药落盘）。
    """
    parts_dir = os.path.join(tables_dir, "parts")
    if not os.path.isdir(parts_dir):
        return {}
    catalog: Dict[str, Dict[str, Any]] = {}
    for filename in sorted(os.listdir(parts_dir)):
        if not filename.endswith(".json"):
            continue
        for entry in _read_json(os.path.join(parts_dir, filename)).get("parts") or []:
            item_id = entry.get("item_id")
            if not item_id or not entry.get("name"):
                continue
            catalog[str(item_id)] = {
                "name": entry["name"],
                "slot": entry.get("slot") or "",
            }
    return catalog
