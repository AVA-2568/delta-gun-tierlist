"""归一化官方游戏数据的加载与索引层。

只读数据访问，不做任何战斗推导。所有文件由 ``src.collectors.game_data_sync`` 产出。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

from src.engine.curves import CurveLibrary

DEFAULT_DATA_DIR = os.path.join("data", "game")


class GameData:
    """官方对齐游戏数据集的只读视图。"""

    def __init__(self, data_dir: str = DEFAULT_DATA_DIR):
        self.data_dir = data_dir
        self._cache: Dict[str, Any] = {}
        self.weapons: List[Dict[str, Any]] = self._load("weapons.json").get("weapons", [])
        self.ammo: List[Dict[str, Any]] = self._load("ammo.json").get("ammo", [])
        self.armor: Dict[str, Any] = self._load("armor.json")
        self.parts: Dict[str, Dict[str, Any]] = self._load("parts.json").get("parts", {})
        self.profiles: Dict[str, Dict[str, Any]] = self._load("profiles.json").get("profiles", {})
        self.mechanism: Dict[str, Any] = self._load("mechanism.json")
        self.scenarios_raw: Dict[str, Any] = self._load("scenarios.json")
        self.validation_samples: Dict[str, Any] = self._load("validation_samples.json").get("samples", {})
        self.stat_labels: Dict[str, str] = self._load("stat_labels.json").get("stats", {})
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
    def _load(self, filename: str) -> Any:
        if filename in self._cache:
            return self._cache[filename]
        path = os.path.join(self.data_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"缺少归一化数据文件 {path}，请先运行 `python -m src.collectors.game_data_sync`"
            )
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        self._cache[filename] = payload
        return payload

    # ------------------------------------------------------------------ #
    @property
    def dataset_version(self) -> Optional[str]:
        return (self.provenance.get("source") or {}).get("dataset_version")

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

    def require_profile(self, profile_id: Optional[str]) -> Dict[str, Any]:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise KeyError(f"未收录的 profile：{profile_id}")
        return profile

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

    def ammo_levels(self, weapon: Dict[str, Any]) -> List[int]:
        return sorted({a["penetration_level"] for a in self.ammo_for_weapon(weapon)})

    def defense(self, level: int) -> Optional[Dict[str, Any]]:
        return (self.armor.get("levels") or {}).get(str(level))

    @lru_cache(maxsize=None)
    def scenario_ids(self) -> List[str]:  # pragma: no cover - 便捷方法
        return [s["scenario_id"] for s in self.scenarios_raw.get("scenarios", [])]

    @property
    def distance_range(self) -> Dict[str, int]:
        return self.scenarios_raw.get("distance_range", {"min": 0, "max": 80, "step": 1, "default_min": 15, "default_max": 40})


def load_game_data(data_dir: str = DEFAULT_DATA_DIR) -> GameData:
    return GameData(data_dir=data_dir)
