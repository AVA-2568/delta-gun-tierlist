"""对外数据表导出：枪械表 / 配件表 / 配件×枪械对接表。

三张表与 TTK 榜单**同源同真**：枪械状态全部经 :class:`WeaponStateResolver`
实测产出（官方默认配装口径，与榜单 base/变体行一致），不引入第二套口径。

- ``weapons.json`` —— 全部收录枪械（68 本体 + 18 官方变体出厂态）的完整状态
- ``parts.json``   —— 全部配件的属性加成 / profile 换挡 / 精校声明（target 附语义化键）
- ``links.json``   —— 全部「单配件 × 本体枪」对接记录：在本体官方默认态上
  单装一件配件后的关键状态，外部工具据此即可对接两表计算任意配装

收录范围 = 上游 manifest.weaponPacks 全量（官方 TTK 榜仅覆盖其中 43 把）；
精确条目数以 ``data/game/provenance.json`` 的 ``counts`` 与
``tests/test_export.py`` 规模契约为准。

确定性：不写时间戳（同一份上游数据逐字节一致的产出）；数据集版本取自
``data/game/provenance.json``。用法：``python -m src.export``。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src.engine.game_data import DEFAULT_DATA_DIR, load_game_data
from src.engine.modifiers import PROFILE_SLOT_TARGETS, hitbox_key
from src.engine.weapon_state import PANEL_ATTR_NAMES, WeaponStateResolver

EXPORT_DIR = os.path.join("data", "export")
PROVENANCE_PATH = os.path.join("data", "game", "provenance.json")

#: link 表 state_changed 判定与 after 输出的字段集（TTK 语义 + 手感语义的最小完备集）
_STATE_FIELDS = (
    "rpm",
    "fire_interval_s",
    "flesh_damage",
    "armor_damage",
    "penetration_level",
    "hitbox_multipliers",
    "muzzle_velocity_mps",
    "effective_range_m",
    "falloff_segments",
    "ads_ms",
    "clip_capacity",
    "panel",
)


def _dataset_version_ref() -> Optional[str]:
    if not os.path.exists(PROVENANCE_PATH):
        return None
    with open(PROVENANCE_PATH, encoding="utf-8") as fh:
        return json.load(fh).get("source", {}).get("dataset_version")


def _panel_dict(panel: Mapping[str, float]) -> Dict[str, float]:
    return {PANEL_ATTR_NAMES[k]: round(float(v), 4) for k, v in panel.items()}


def _state_summary(state: Any) -> Dict[str, Any]:
    """从 WeaponState 提取对接表与枪械表共用的关键状态（单一定义防口径漂移）。"""
    return {
        "rpm": round(float(state.rpm), 2),
        "fire_interval_s": round(float(state.fire_interval_seconds), 6),
        "flesh_damage": float(state.base_damage),
        "armor_damage": float(state.base_armor_damage),
        "penetration_level": int(state.base_penetration_level),
        "hitbox_multipliers": {k: float(v) for k, v in state.hitbox_multipliers.items()},
        "muzzle_velocity_mps": round(float(state.muzzle_velocity_mps), 2),
        "effective_range_m": round(float(state.effective_range_m), 2),
        "falloff_segments": [dict(s) for s in state.falloff_segments],
        "ads_ms": round(float(state.ads_seconds) * 1000.0, 1),
        "clip_capacity": int(state.clip_capacity),
        "panel": _panel_dict(state.panel),
    }


def _target_semantic(target: Optional[str]) -> Optional[str]:
    """效果 target 的语义化键：panel.<语义> / panel_display.<语义> / profile.<槽位> / hitbox.<部位>；其余原样。"""
    if not target:
        return None
    for prefix, kind in (("WeaponMainAttribute.MainAttrValues.", "panel"), ("DisplayAttrValues.", "panel_display")):
        if target.startswith(prefix):
            index = target[len(prefix):]
            return f"{kind}.{PANEL_ATTR_NAMES.get(index, index)}"
    slot = PROFILE_SLOT_TARGETS.get(target)
    if slot is not None:
        return f"profile.{slot}"
    hitbox = hitbox_key(target)
    if hitbox is not None:
        return f"hitbox.{hitbox}"
    return target


def export_parts(gd: Any) -> Dict[str, Any]:
    parts = []
    for item_id in sorted(gd.parts):
        part = gd.parts[item_id]
        effects = []
        for effect in part.get("effects") or []:
            entry = dict(effect)
            entry["target_semantic"] = _target_semantic(effect.get("target"))
            effects.append(entry)
        parts.append(
            {
                "item_id": str(item_id),
                "name": part.get("name"),
                "slot": part.get("slot"),
                "selectable": bool(part.get("selectable", True)),
                "effects": effects,
                "tunes": [dict(t) for t in part.get("tunes") or []],
            }
        )
    return {"dataset_version_ref": _dataset_version_ref(), "parts": parts}


def export_weapons(gd: Any, resolver: WeaponStateResolver) -> Dict[str, Any]:
    weapons = []
    for weapon in gd.weapons:
        state = resolver.resolve(str(weapon["profile_key"]))
        weapons.append(
            {
                "weapon_id": str(weapon["weapon_id"]),
                "profile_key": str(weapon["profile_key"]),
                "name": weapon.get("name"),
                "display_name": weapon.get("display_name"),
                "category": weapon.get("category"),
                "category_id": weapon.get("category_id"),
                "weapon_type": weapon.get("weapon_type"),
                "caliber": weapon.get("caliber"),
                "is_variant": bool(weapon.get("is_variant")),
                "variant_item_id": weapon.get("variant_item_id"),
                "variant_item_name": weapon.get("variant_item_name"),
                **_state_summary(state),
                "fire_modes": weapon.get("fire_modes"),
                "selected_fire_mode": weapon.get("selected_fire_mode"),
                "max_carried_ammo": weapon.get("max_carried_ammo"),
                "max_distance_m": weapon.get("max_distance_m"),
                "projectile_count": int(weapon.get("projectile_count") or 1),
                "burst_count": weapon.get("burst_count"),
                "ammo_type_id": weapon.get("ammo_type_id"),
                "ammo_item_ids": weapon.get("ammo_item_ids"),
                "default_items": {str(k): str(v) for k, v in (weapon.get("default_items") or {}).items()},
                "sockets": [
                    {"socket_id": s["socket_id"], "options": [str(x) for x in s["options"]]}
                    for s in weapon.get("sockets") or []
                ],
                "provider_sockets": {
                    str(k): [
                        {"socket_id": s["socket_id"], "options": [str(x) for x in s["options"]]}
                        for s in v
                    ]
                    for k, v in (weapon.get("provider_sockets") or {}).items()
                },
                "notes": list(state.notes),
            }
        )
    return {"dataset_version_ref": _dataset_version_ref(), "weapons": weapons}


def export_links(gd: Any, resolver: WeaponStateResolver) -> Dict[str, Any]:
    """「单配件 × 本体枪」对接表：在本体官方默认态上单装一件配件后的状态。

    变体条目不参与枚举：变体 = 本体 + 官方预装件，其完整状态已在枪械表；
    在变体上继续改装可由外部工具以本表 + 枪械表组合推得。
    """
    links: List[Dict[str, Any]] = []
    for weapon in gd.weapons:
        if weapon.get("is_variant"):
            continue
        profile_key = str(weapon["profile_key"])
        base = resolver.resolve(profile_key)
        base_state = _state_summary(base)
        name_by_id = {
            str(pid): rec.get("name") for pid, rec in gd.parts.items()
        }
        for socket in weapon.get("sockets") or []:
            socket_id = str(socket["socket_id"])
            for item_id in socket["options"]:
                item_id = str(item_id)
                after = _state_summary(resolver.resolve(profile_key, loadout={socket_id: item_id}))
                links.append(
                    {
                        "weapon_id": str(weapon["weapon_id"]),
                        "weapon_name": weapon.get("display_name"),
                        "profile_key": profile_key,
                        "socket_id": socket_id,
                        "item_id": item_id,
                        "item_name": name_by_id.get(item_id),
                        "state_changed": after != base_state,
                        "after": after,
                        "opens_sockets": [
                            {"socket_id": s["socket_id"], "options": [str(x) for x in s["options"]]}
                            for s in (weapon.get("provider_sockets") or {}).get(item_id) or []
                        ],
                    }
                )
    return {"dataset_version_ref": _dataset_version_ref(), "links": links}


def _write_json(path: str, payload: Any) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False) + "\n"
    target.write_text(text, encoding="utf-8", newline="\n")


def export_all(output_dir: str = EXPORT_DIR) -> Dict[str, int]:
    gd = load_game_data(DEFAULT_DATA_DIR)
    resolver = WeaponStateResolver(gd)
    _write_json(os.path.join(output_dir, "weapons.json"), export_weapons(gd, resolver))
    _write_json(os.path.join(output_dir, "parts.json"), export_parts(gd))
    _write_json(os.path.join(output_dir, "links.json"), export_links(gd, resolver))
    return {
        "weapons": len(gd.weapons),
        "parts": len(gd.parts),
        "links": sum(len(s["options"]) for w in gd.weapons if not w.get("is_variant") for s in w.get("sockets") or []),
    }


def main() -> None:
    counts = export_all()
    print(
        f"数据表导出完成 → {EXPORT_DIR}/（weapons.json {counts['weapons']} 条目 · "
        f"parts.json {counts['parts']} 配件 · links.json {counts['links']} 对接记录）"
    )


if __name__ == "__main__":
    main()
