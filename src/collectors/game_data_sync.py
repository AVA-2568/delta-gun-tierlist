"""官方游戏数据同步与归一化。

数据来源：`https://dfttk.com/data/v3`（公开数据同步副本，非腾讯官方 API）。
本模块只负责「下载 → 归一化 → 落盘 → 记录溯源」，不参与任何战斗建模。

设计要点
--------
1. 逐块溯源：所有产出文件写入 ``provenance.json``，记录来源 URL、数据集版本与
   ``version`` hash、文件 sha256、抓取时间、条目数、核验状态与置信度。
2. 人工覆盖：``data/overrides/manual_corrections.json`` 优先级最高，可覆盖枪械/弹药的
   任意字段，覆盖生效时 provenance 标记为 ``verified-in-game``。
3. 确定性：同一份上游数据必然产出逐字节一致的本地数据（字典有序、无时间戳漂移
   写入数据体，时间戳只进 provenance）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SOURCE_BASE = "https://dfttk.com/data/v3/"
SOURCE_NAME = "dfttk-v3"

# 面板属性索引 → 语义键（来自 common.json mainAttributes）
PANEL_ATTR_KEYS: Dict[int, str] = {
    2: "effective_range",
    3: "recoil_control",
    4: "waist_accuracy",
    5: "handling",
    6: "stability",
}

# 官方类别 ID → 中文类别名
CATEGORY_ZH: Dict[str, str] = {
    "assaultRifle": "突击步枪",
    "battleRifle": "战斗步枪",
    "submachineGun": "冲锋枪",
    "lightMachineGun": "轻机枪",
    "marksmanRifle": "精确射手步枪",
    "sniperRifle": "狙击步枪",
    "shotgun": "霰弹枪",
    "pistol": "手枪",
    "specialWeapon": "特殊武器",
}

# 官方部件类别 ID → 中文槽位名
SLOT_ZH: Dict[str, str] = {
    "barrel": "枪管",
    "muzzle": "枪口",
    "foregrip": "前握把",
    "rearGrip": "后握把",
    "stock": "枪托",
    "handguard": "护木",
    "magazine": "弹匣",
    "scope": "瞄具",
    "functional": "功能件",
}

# 部件 itemId 前缀 → 槽位（当 display.categoryId 缺失时的回退）
SLOT_BY_PREFIX: Dict[str, str] = {
    "1302": "barrel",
    "1303": "rearGrip",
    "1304": "stock",
    "1305": "handguard",
    "1311": "scope",
    "1312": "magazine",
    "1313": "muzzle",
    "1314": "functional",
    "1317": "functional",
    "1320": "functional",
    "1321": "functional",
    "1333": "functional",
}

DEFAULT_CACHE_DIR = os.path.join(".cache", "dfttk")
DEFAULT_OUTPUT_DIR = os.path.join("data", "game")
DEFAULT_OVERRIDES_PATH = os.path.join("data", "overrides", "manual_corrections.json")

# 参与排行榜的武器类别（与官方 firefight 排行武器池一致：步枪/冲锋枪/机枪/精确射手步枪）
RANKED_WEAPON_TYPES = {"rifle", "smg", "lmg", "marksman"}

# 作战模式：烽火地带采用 sol（soldier）。sol/mp 在初速、后坐机制曲线等条目上确有差异，
# 不可混用。所有归一化与求值默认锁定 sol。
DEFAULT_MODE = "sol"

# 需要落盘的 profile 库：散布 / 后坐 / 机动 / 瞄具 / 弹道。
# 配件可通过 `Initial` 修饰符替换这些引用（例如消音枪管自带更优的 hipSpread 与 recoil），
# 因此必须保存库本体，否则求值链会在换装后断裂。
PROFILE_LIBRARIES: Tuple[Tuple[str, str], ...] = (
    ("spread", "spreadProfiles"),
    ("recoil", "recoilProfiles"),
    ("movement", "movementProfiles"),
    ("aiming", "aimingProfiles"),
)


class SourceUnavailable(RuntimeError):
    """上游数据不可用。"""


# --------------------------------------------------------------------------- #
# 下载层
# --------------------------------------------------------------------------- #
def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _download(path: str, cache_dir: str, timeout: float = 120.0, refresh: bool = False) -> bytes:
    """下载单文件，带磁盘缓存。缓存命中时直接返回，避免重复流量。"""
    cache_path = os.path.join(cache_dir, path.replace("/", "__"))
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    if os.path.exists(cache_path) and not refresh:
        with open(cache_path, "rb") as fh:
            return fh.read()
    url = SOURCE_BASE + path
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; delta-gun-tierlist)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:  # pragma: no cover - 网络异常分支
        raise SourceUnavailable(f"下载 {url} 失败：{type(exc).__name__} - {exc}") from exc
    with open(cache_path, "wb") as fh:
        fh.write(payload)
    return payload


def _download_json(path: str, cache_dir: str, timeout: float = 120.0, refresh: bool = False) -> Tuple[Any, str]:
    payload = _download(path, cache_dir, timeout=timeout, refresh=refresh)
    return json.loads(payload.decode("utf-8")), _sha256_bytes(payload)


# --------------------------------------------------------------------------- #
# 覆盖层
# --------------------------------------------------------------------------- #
def load_overrides(path: str = DEFAULT_OVERRIDES_PATH) -> Dict[str, Any]:
    """读取人工校正层。文件缺失视为无覆盖。"""
    if not os.path.exists(path):
        return {"weapons": {}, "ammo": {}, "armor": {}, "notes": []}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("weapons", "ammo", "armor"):
        data.setdefault(key, {})
    data.setdefault("notes", [])
    return data


def _apply_field_overrides(
    record: Dict[str, Any],
    overrides: Dict[str, Any],
    key: str,
    applied: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """把某条记录的字段覆盖应用到记录上，并登记覆盖痕迹。"""
    entry = overrides.get(key)
    if not entry:
        return record
    fields = entry.get("fields", entry)
    for field, spec in fields.items():
        if field in ("basis", "verified_at", "note"):
            continue
        if isinstance(spec, dict) and "value" in spec:
            value = spec["value"]
            basis = spec.get("basis", entry.get("basis", "manual"))
            verified_at = spec.get("verified_at", entry.get("verified_at"))
            note = spec.get("note", entry.get("note", ""))
        else:
            value = spec
            basis = entry.get("basis", "manual")
            verified_at = entry.get("verified_at")
            note = entry.get("note", "")
        record[field] = value
        applied.append(
            {
                "key": key,
                "field": field,
                "value": value,
                "basis": basis,
                "verified_at": verified_at,
                "note": note,
            }
        )
    return record


# --------------------------------------------------------------------------- #
# 归一化：弹药 / 护甲 / 穿透矩阵
# --------------------------------------------------------------------------- #
def normalize_ammo(
    ammo_catalog: Dict[str, Any],
    interactions: Dict[str, Any],
    overrides: Dict[str, Any],
    applied: List[Dict[str, Any]],
    ammo_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
    cross_checks: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """归一化弹药表，合并官方穿透矩阵与 combat 包弹药档案。

    ``catalog/ammo.json`` 只给出 ``fleshDamageMultiplier`` / ``armorDamageMultiplier``；
    伤害建模还需要的 ``limbDamageMultiplier`` / ``woundRate`` /
    ``penetrateAmmoLevelDecrease`` 仅存在于 combat 包的 ``ammoProfiles``，故一并合并并交叉校验。
    """
    interaction_profiles = interactions.get("profiles", {})
    profiles = ammo_profiles or {}
    checks = cross_checks if cross_checks is not None else []
    records: List[Dict[str, Any]] = []

    for ammo_id in sorted(ammo_catalog.get("ammo", {}).keys()):
        raw = ammo_catalog["ammo"][ammo_id]
        profile = interaction_profiles.get(ammo_id, {})
        correction = profile.get("armorCorrection", {})
        combat = profiles.get(ammo_id) or {}

        matrix: Dict[str, Dict[str, Any]] = {}
        for armor_level, entry in correction.items():
            matrix[str(armor_level)] = {
                "body_health_rate": float(entry.get("bodyHealthRate", 0.0)),
                "helmet_health_rate": float(entry.get("helmetHealthRate", 0.0)),
                "body_durability_rate": float(entry.get("bodyDurabilityRate", 0.0)),
                "helmet_durability_rate": float(entry.get("helmetDurabilityRate", 0.0)),
                "penetrates": bool(entry.get("penetrates", False)),
            }

        caliber = (raw.get("caliber") or "").replace("*", "x")

        flesh_cat = float(raw.get("fleshDamageMultiplier") or 1.0)
        armor_cat = float(raw.get("armorDamageMultiplier") or 1.0)
        if combat:
            flesh_combat = float(combat.get("damageMultiplier") or 1.0)
            armor_combat = float(combat.get("armorDamageMultiplier") or 1.0)
            if abs(flesh_cat - flesh_combat) > 1e-9:
                checks.append({"kind": "ammo_flesh_multiplier", "key": ammo_id,
                               "catalog": flesh_cat, "combat_pack": flesh_combat})
            if abs(armor_cat - armor_combat) > 1e-9:
                checks.append({"kind": "ammo_armor_multiplier", "key": ammo_id,
                               "catalog": armor_cat, "combat_pack": armor_combat})

        record: Dict[str, Any] = {
            "ammo_item_id": ammo_id,
            "name": raw.get("name") or ammo_id,
            "caliber": caliber,
            "ammo_type_id": str(raw.get("ammoTypeId") or ""),
            "rarity": raw.get("rarity"),
            "penetration_level": int(raw.get("penetrationLevel") or 0),
            "flesh_damage_multiplier": flesh_cat,
            "armor_damage_multiplier": armor_cat,
            "limb_damage_multiplier": float(combat.get("limbDamageMultiplier") or 1.0),
            "wound_rate": float(combat.get("woundRate") or 0.0),
            "throw_blocking_damage_rate": float(combat.get("throwBlockingDamageRate") or 1.0),
            "penetrate_ammo_level_decrease": int(combat.get("penetrateAmmoLevelDecrease") or 0),
            "profile_source": "combat-pack" if combat else "catalog-only",
            "penetration_matrix": matrix,
            "source_legacy_ammo_id": raw.get("sourceLegacyAmmoId"),
        }
        records.append(_apply_field_overrides(record, overrides["ammo"], ammo_id, applied))

    return records


def normalize_armor(
    armors: Dict[str, Any],
    helmets: Dict[str, Any],
    scenario_index: Dict[str, Any],
    overrides: Dict[str, Any],
    applied: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """归一化护具表与官方作战预设。

    官方排行预设（scenarioIndex.scenarios[].defense）给出每个等级的代表护具，
    以其为「该等级基准护具」，同时保留该等级的全部条目供人工对照。
    """
    def _collect(container: Dict[str, Any], id_field: str) -> Dict[int, List[Dict[str, Any]]]:
        by_level: Dict[int, List[Dict[str, Any]]] = {}
        for item_id in sorted(container.get("profiles", {}).keys()):
            raw = container["profiles"][item_id]
            level = int(raw.get("level") or 0)
            by_level.setdefault(level, []).append(
                {
                    "item_id": raw.get(id_field) or item_id,
                    "name": raw.get("name"),
                    "level": level,
                    "max_durability": int(raw.get("maxDurability") or 0),
                    "covered_hit_areas": list(raw.get("coveredHitAreas") or []),
                    "source_legacy_id": raw.get("sourceLegacyId"),
                }
            )
        for level in by_level:
            by_level[level].sort(key=lambda item: (-item["max_durability"], item["item_id"]))
        return by_level

    armors_by_level = _collect(armors, "armorItemId")
    helmets_by_level = _collect(helmets, "helmetItemId")

    # 官方预设：defensePresetKey → {helmetId(legacy), armorId(legacy), durabilities}
    presets: Dict[str, Dict[str, Any]] = {}
    for scenario in scenario_index.get("scenarios", []):
        key = str(scenario.get("defensePresetKey"))
        if key in presets:
            continue
        defense = scenario.get("defense") or {}
        presets[key] = {
            "level": int(defense.get("helmetLevel") or defense.get("armorLevel") or 0),
            "helmet_source_legacy_id": defense.get("helmetId"),
            "helmet_level": defense.get("helmetLevel"),
            "helmet_durability": defense.get("helmetDurability"),
            "armor_source_legacy_id": defense.get("armorId"),
            "armor_level": defense.get("armorLevel"),
            "armor_durability": defense.get("armorDurability"),
        }

    levels: Dict[str, Dict[str, Any]] = {}
    for level in sorted(set(armors_by_level) | set(helmets_by_level)):
        preset = presets.get(str(level), {})
        armor_options = armors_by_level.get(level, [])
        helmet_options = helmets_by_level.get(level, [])

        def _pick(options: Sequence[Dict[str, Any]], legacy_id: Optional[str], durability: Optional[int]) -> Optional[Dict[str, Any]]:
            if legacy_id is not None:
                for option in options:
                    if str(option["source_legacy_id"]) == str(legacy_id):
                        return option
            if durability is not None:
                for option in options:
                    if option["max_durability"] == durability:
                        return option
            return options[0] if options else None

        armor_pick = _pick(armor_options, preset.get("armor_source_legacy_id"), preset.get("armor_durability"))
        helmet_pick = _pick(helmet_options, preset.get("helmet_source_legacy_id"), preset.get("helmet_durability"))

        if armor_pick is None or helmet_pick is None:
            continue

        records: Dict[str, Any] = {
            "level": level,
            "armor": {
                **armor_pick,
                "max_durability": int(preset.get("armor_durability") or armor_pick["max_durability"]),
            },
            "helmet": {
                **helmet_pick,
                "max_durability": int(preset.get("helmet_durability") or helmet_pick["max_durability"]),
            },
            "armor_options": armor_options,
            "helmet_options": helmet_options,
            "preset_source": "official-firefight-ranking" if preset else "derived-from-max-durability",
        }
        levels[str(level)] = _apply_field_overrides(records, overrides["armor"], str(level), applied)

    return {"levels": levels, "source_presets": presets}


# --------------------------------------------------------------------------- #
# 归一化：配件与机制曲线
# --------------------------------------------------------------------------- #
def _slot_for_item(item_id: str, display_objects: Dict[str, Any]) -> str:
    entry = display_objects.get(item_id)
    if isinstance(entry, dict) and entry.get("categoryId"):
        return str(entry["categoryId"])
    return SLOT_BY_PREFIX.get(item_id[:4], "unknown")


def _normalize_tune(tune_id: str, tune_raw: Dict[str, Any], curves: Dict[str, Any]) -> Dict[str, Any]:
    """归一化单个精校滑块，内联其效果曲线点。"""
    rng = tune_raw.get("range") or {}
    labels = tune_raw.get("labels") or {}
    functions: List[Dict[str, Any]] = []
    for func in tune_raw.get("functions", []):
        curve = curves.get(func.get("curveId"))
        points: List[List[float]] = []
        if isinstance(curve, dict):
            for point in curve.get("points", []):
                points.append(
                    [
                        float(point.get("inputValue", 0.0)),
                        float(point.get("outputValue", 0.0)),
                        str(point.get("interpolationMode", "RCIM_Linear")),
                        float(point.get("arriveTangent", 0.0)),
                        float(point.get("leaveTangent", 0.0)),
                    ]
                )
        functions.append(
            {
                "target": func.get("target"),
                "modifier": func.get("modifier"),
                "curve": points,
            }
        )

    return {
        "tune_id": tune_id,
        "dimension": _strip_authoring_prefix(labels.get("mainLocId")),
        "unit": _strip_authoring_prefix(labels.get("unitLocId")),
        "min_value": float(rng.get("minValue", 0.0)),
        "max_value": float(rng.get("maxValue", 0.0)),
        "step": float(rng.get("step", 1.0) or 1.0),
        "default_value": float(rng.get("defaultValue", 0.0)),
        "functions": functions,
    }


def _strip_authoring_prefix(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"^authoring:", "", str(value))


def _normalize_effect(effect: Dict[str, Any]) -> Dict[str, Any]:
    """归一化单条配件效果。

    上游 ``value`` 既可能是数值（``Addend`` / ``Mult_A`` / ``Mult_C``），
    也可能是引用字符串（``Initial`` + profile id，例如 ``WaistShootSpreadId``）。
    数值进 ``value``，引用进 ``value_ref``，二者互斥。
    """
    raw_value = effect.get("value")
    record: Dict[str, Any] = {
        "target": effect.get("target"),
        "operation": effect.get("operation"),
        "modifier": effect.get("modifier"),
        "scope": effect.get("scope"),
    }
    if isinstance(raw_value, bool):
        record["value"] = float(raw_value)
        record["value_ref"] = None
    elif isinstance(raw_value, (int, float)):
        record["value"] = float(raw_value)
        record["value_ref"] = None
    else:
        record["value"] = None
        record["value_ref"] = None if raw_value is None else str(raw_value)
    return record


def normalize_parts(
    build_packs: Dict[str, Dict[str, Any]],
    item_names: Dict[str, str],
    mechanism_tune_ids: Optional[set] = None,
) -> Dict[str, Dict[str, Any]]:
    """把多把枪的 build pack 合并去重为全局配件表。

    只保留对战斗建模有意义的字段：槽位、名称、效果集（sol）、精校滑块（含曲线）。
    """
    parts: Dict[str, Dict[str, Any]] = {}

    for weapon_id in sorted(build_packs.keys()):
        pack = build_packs[weapon_id]
        display_objects = (pack.get("display") or {}).get("objects") or {}
        all_tunes = pack.get("tunes") or {}
        all_curves = pack.get("curves") or {}
        effects_by_item = pack.get("effectsByItemId") or {}
        part_meta = pack.get("parts") or {}
        if mechanism_tune_ids is None:
            mechanism_tune_ids = set()

        for item_id in sorted(effects_by_item.keys()):
            if item_id in parts:
                continue
            effects_raw = (effects_by_item.get(item_id) or {}).get("sol") or []
            effects = [_normalize_effect(effect) for effect in effects_raw]

            tune_ids = (part_meta.get(item_id) or {}).get("tuneIds") or []
            tunes: List[Dict[str, Any]] = []
            for tune_id in tune_ids:
                tune_raw = all_tunes.get(tune_id)
                if not tune_raw:
                    continue
                tunes.append(_normalize_tune(tune_id, tune_raw, all_curves))

            parts[item_id] = {
                "item_id": item_id,
                "name": item_names.get(item_id) or f"未命名部件 {item_id}",
                "slot": _slot_for_item(item_id, display_objects),
                "selectable": bool((display_objects.get(item_id) or {}).get("playerSelectable", True)),
                "effects": effects,
                "tunes": tunes,
            }

    return parts


def _normalize_spread_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "base_degrees": raw.get("baseSpreadDegrees") or {},
        "max_degrees": raw.get("maximumSpreadDegrees") or {},
        "runtime_scale": raw.get("runtimeScaleFactor"),
    }


def _normalize_recoil_profile(raw: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for phase in ("continuousFire", "loop"):
        phase_raw = raw.get(phase) or {}
        if not phase_raw:
            continue
        out[phase] = {
            "horizontal_values": [float(x) for x in phase_raw.get("horizontalValues", [])],
            "vertical_values": [float(x) for x in phase_raw.get("verticalValues", [])],
            "horizontal_scale": float(phase_raw.get("horizontalScale", 1.0)),
            "vertical_scale": float(phase_raw.get("verticalScale", 1.0)),
        }
    return out


def normalize_profiles(
    build_packs: Dict[str, Dict[str, Any]],
    combat_packs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """合并所有枪械的 profile 库（散布/后坐/机动/瞄具/弹道/伤害），按 id 去重。

    配件自带的 profile（id 形如 ``authoring:part:<item>:<mode>:hipSpread``）与武器自带的
    profile 同处一库；``Initial`` 修饰符引用哪个 id，求值时就取哪个。因此这里必须全量保留，
    否则「换消音枪管 → 散布/后坐/伤害/弹道剖面切换」这条链路会缺数据。

    伤害档案（``AuthoringValueId.DefaultDamageId`` 指向）只存在于 combat 包，故一并收录。

    冲突处理：同一 id 出现在多把枪上时，若内容不一致则记入 ``conflicts``（不静默择一），
    由人工覆盖层或后续实测裁决。
    """
    library: Dict[str, Dict[str, Any]] = {}
    seen_payload: Dict[str, str] = {}
    conflicts: List[Dict[str, Any]] = []

    def _record(uid: str, kind: str, payload: Dict[str, Any], origin: str) -> None:
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if uid in seen_payload and seen_payload[uid] != serialized:
            conflicts.append({"profile_id": uid, "kind": kind, "origin": origin})
            return
        seen_payload.setdefault(uid, serialized)
        library.setdefault(uid, {"profile_id": uid, "kind": kind, **payload})

    for weapon_id in sorted(build_packs.keys()):
        pack = build_packs[weapon_id]
        for kind, key, container in ((kind, key, "handling") for kind, key in PROFILE_LIBRARIES):
            block = ((pack.get(container) or {}).get(key)) or {}
            for uid, raw in block.items():
                if not isinstance(raw, dict):
                    continue
                if kind == "spread":
                    payload = _normalize_spread_profile(raw)
                elif kind == "recoil":
                    payload = _normalize_recoil_profile(raw)
                elif kind == "movement":
                    payload = {
                        "walk_speed_cm_s": float(raw.get("walkSpeedCmPerSecond") or 0.0),
                        "sprint_speed_cm_s": float(raw.get("sprintSpeedCmPerSecond") or 0.0),
                        "silent_move_speed_cm_s": float(raw.get("silentMoveSpeedCmPerSecond") or 0.0),
                        "ads_movement_modifier": float(raw.get("adsMovementModifier") or 0.0),
                    }
                else:  # aiming
                    payload = {
                        "ads_on_s": float(raw.get("adsOnTimeSeconds") or 0.0),
                        "ads_off_s": float(raw.get("adsOffTimeSeconds") or 0.0),
                        "zoom_rate": float(raw.get("zoomRate") or 1.0),
                        "ads_spread_profile_id": raw.get("adsSpreadProfileId"),
                        "ads_recoil_profile_id": raw.get("adsRecoilProfileId"),
                    }
                _record(str(uid), kind, payload, weapon_id)

        for uid, raw in (pack.get("combat", {}).get("bulletProfiles") or {}).items():
            if not isinstance(raw, dict):
                continue
            _record(
                str(uid),
                "bullet",
                {
                    "initial_speed_cm_s": float(raw.get("initialSpeedCmPerSecond") or 0.0),
                    "max_distance_cm": float(raw.get("maxDistanceCm") or 0.0),
                    "valid_distance_cm": float(raw.get("validDistanceCm") or 0.0),
                    "attenuation_distances_cm": [float(x) for x in raw.get("attenuationDistancesCm", [])],
                    "attenuation_rates": [float(x) for x in raw.get("attenuationRates", [])],
                },
                weapon_id,
            )

    for weapon_id in sorted((combat_packs or {}).keys()):
        pack = (combat_packs or {})[weapon_id]
        for uid, raw in (pack.get("combat", {}).get("damageProfiles") or {}).items():
            if not isinstance(raw, dict):
                continue
            _record(
                str(uid),
                "damage",
                {
                    "base_damage": float(raw.get("baseDamage") or 0.0),
                    "base_armor_damage": float(raw.get("baseArmorDamage") or 0.0),
                    "base_penetration_level": int(raw.get("basePenetrationLevel") or 0),
                    "hitbox_multipliers": {
                        str(k): float(v) for k, v in (raw.get("hitboxMultipliers") or {}).items()
                    },
                },
                weapon_id,
            )

    return {
        "profiles": library,
        "counts_by_kind": {
            kind: sum(1 for p in library.values() if p["kind"] == kind)
            for kind in ("spread", "recoil", "movement", "aiming", "bullet", "damage")
        },
        "conflicts": conflicts,
    }


def normalize_mechanism_curves(
    build_packs: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """提取面板属性 → 实机规则量的官方机制曲线，并汇总逐枪 attributeRules 契约。

    机制曲线（``authoring:mechanism:*``）为全局共享，去重后取出现次数最多者以抗噪。
    但 ``attributeRules.defaults`` **逐枪可能不同**（例如 ``recoilControlVariant5``
    按枪选用变体曲线），因此按武器分别保留，不做全局合并。
    """
    curve_votes: Dict[str, Dict[str, int]] = {}
    curve_payload: Dict[str, Any] = {}
    disagreements: List[Dict[str, Any]] = []
    per_weapon_rules: Dict[str, Any] = {}

    for weapon_id in sorted(build_packs.keys()):
        pack = build_packs[weapon_id]
        per_weapon_rules[weapon_id] = (pack.get("attributeRules") or {}).get("defaults") or {}

        curves = pack.get("curves") or {}
        for curve_id in sorted(curves.keys()):
            if not curve_id.startswith("authoring:mechanism:"):
                continue
            serialized = json.dumps(curves[curve_id], sort_keys=True, ensure_ascii=False)
            bucket = curve_votes.setdefault(curve_id, {})
            bucket[serialized] = bucket.get(serialized, 0) + 1
            curve_payload.setdefault(curve_id, curves[curve_id])

    normalized_curves: Dict[str, Any] = {}
    for curve_id, variants in sorted(curve_votes.items()):
        if len(variants) > 1:
            disagreements.append(
                {"kind": "mechanism_curve", "curve_id": curve_id, "distinct_variants": len(variants)}
            )
        payload = curve_payload[curve_id]
        points = payload.get("points", []) if isinstance(payload, dict) else payload
        normalized_curves[curve_id] = {
            "points": [
                [
                    float(point.get("inputValue", 0.0)),
                    float(point.get("outputValue", 0.0)),
                    str(point.get("interpolationMode", "RCIM_Linear")),
                    float(point.get("arriveTangent", 0.0)),
                    float(point.get("leaveTangent", 0.0)),
                ]
                for point in points
            ]
        }

    return {
        "curves": normalized_curves,
        "per_weapon_attribute_rules": per_weapon_rules,
        "disagreements": disagreements,
    }


# --------------------------------------------------------------------------- #
# 归一化：枪械
# --------------------------------------------------------------------------- #
def _sol_damage_profile(combat_pack: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """定位 combat 包中该武器的 sol 伤害档案。"""
    combat = combat_pack.get("combat") or {}
    damage_profiles = combat.get("damageProfiles") or {}
    attacker_profiles = (combat.get("attackerProfiles") or {}).get(DEFAULT_MODE) or {}
    references = ((combat_pack.get("weapon") or {}).get("references") or {})
    mode_refs = (references.get("modes") or {}).get(DEFAULT_MODE) or {}
    attacker_id = mode_refs.get("attackerProfileId")
    damage_id = (attacker_profiles.get(attacker_id) or {}).get("damageProfileId")

    if damage_id and damage_id in damage_profiles:
        return str(damage_id), damage_profiles[damage_id]
    sol_keys = sorted(k for k in damage_profiles if f":{DEFAULT_MODE}:" in k or k.endswith(f":{DEFAULT_MODE}:damage"))
    if sol_keys:
        return str(sol_keys[0]), damage_profiles[sol_keys[0]]
    return None, None


def normalize_damage_profile(
    weapon_id: str,
    combat_pack: Dict[str, Any],
    sol_summary: Dict[str, Any],
    cross_checks: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """提取 sol 伤害档案，并与 catalog 摘要交叉校验。

    伤害建模以 combat 包为准（``damageProfiles`` 是实机注入的伤害表）；
    ``catalog/*`` 的 ``combatSummaryByMode.sol`` 作为第二来源用于交叉校验，
    任何不一致都会记入 ``cross_checks``，不允许静默择一。
    """
    profile_id, profile = _sol_damage_profile(combat_pack)
    if profile is None:
        return None

    hitbox = {str(k): float(v) for k, v in (profile.get("hitboxMultipliers") or {}).items()}
    base_damage = float(profile.get("baseDamage") or 0.0)
    base_armor_damage = float(profile.get("baseArmorDamage") or 0.0)

    def _cmp(field: str, a: float, b: float) -> None:
        if abs(a - b) > 1e-9:
            cross_checks.append(
                {"kind": "damage_profile", "weapon_id": weapon_id, "field": field,
                 "combat_pack": a, "catalog": b}
            )

    _cmp("base_damage", base_damage, float(sol_summary.get("baseFleshDamage") or 0.0))
    _cmp("base_armor_damage", base_armor_damage, float(sol_summary.get("baseArmorDamage") or 0.0))
    catalog_hitbox = {str(k): float(v) for k, v in (sol_summary.get("hitboxMultipliers") or {}).items()}
    for key in sorted(set(hitbox) | set(catalog_hitbox)):
        _cmp(f"hitbox.{key}", hitbox.get(key, 0.0), catalog_hitbox.get(key, 0.0))

    bullet_profiles = (combat_pack.get("combat") or {}).get("bulletProfiles") or {}
    references = ((combat_pack.get("weapon") or {}).get("references") or {})
    bullet_id = ((references.get("modes") or {}).get(DEFAULT_MODE) or {}).get("bulletProfileId")
    bullet = bullet_profiles.get(bullet_id) or {}
    if bullet:
        _cmp("muzzle_velocity_mps", float(bullet.get("initialSpeedCmPerSecond") or 0.0) / 100.0,
             float(sol_summary.get("muzzleVelocityMps") or 0.0))
        _cmp("valid_range_m", float(bullet.get("validDistanceCm") or 0.0) / 100.0,
             float(sol_summary.get("validDamageRangeMeters") or 0.0))

    return {
        "profile_id": profile_id,
        "base_damage": base_damage,
        "base_armor_damage": base_armor_damage,
        "base_penetration_level": int(profile.get("basePenetrationLevel") or 0),
        "hitbox_multipliers": hitbox,
        "hitbox_multiplier_overrides": {},  # 由配件的 DamagePointId.* 在求值期填充
    }


def _slugify(name: str, weapon_id: str) -> str:
    slug = name.strip().lower()
    slug = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "-", slug).strip("-")
    return slug or weapon_id


def normalize_weapon(
    weapon_id: str,
    pack: Dict[str, Any],
    catalog_object: Dict[str, Any],
    weapon_name: str,
    ammo_by_type: Dict[str, List[str]],
    overrides: Dict[str, Any],
    applied: List[Dict[str, Any]],
    combat_pack: Optional[Dict[str, Any]] = None,
    cross_checks: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """归一化单把枪的完整战斗建模数据。"""
    weapon = pack.get("weapon") or {}
    sol = (catalog_object.get("combatSummaryByMode") or {}).get("sol") or {}
    if not sol:
        return None
    checks = cross_checks if cross_checks is not None else []
    damage_profile = (
        normalize_damage_profile(weapon_id, combat_pack, sol, checks) if combat_pack else None
    )

    ammunition = weapon.get("ammunition") or {}
    ammo_type_id = str(weapon.get("ammoTypeId") or catalog_object.get("ammoTypeId") or "")
    sdk_timing = (weapon.get("fireControl") or {}).get("sdkTiming") or {}

    falloff_segments = [
        {"from_m": float(seg.get("fromM", 0.0)), "to_m": float(seg.get("toM", 0.0)), "rate": float(seg.get("rate", 1.0))}
        for seg in sol.get("damageFalloffSegments", [])
    ]

    panel_attrs = {
        PANEL_ATTR_KEYS[int(index)]: float(value)
        for index, value in (weapon.get("attributes") or {}).get("mainAttrValues", {}).items()
        if int(index) in PANEL_ATTR_KEYS
    }

    handling = pack.get("handling") or {}
    references = weapon.get("references") or {}
    mode_references = (references.get("modes") or {}).get(DEFAULT_MODE) or {}
    aiming_profile_id = references.get("aimingProfileId")
    aiming_raw = (handling.get("aimingProfiles") or {}).get(aiming_profile_id or "", {})

    def _spread(profile_id: Optional[str]) -> Dict[str, Any]:
        raw = (handling.get("spreadProfiles") or {}).get(profile_id or "", {})
        return {
            "base_degrees": raw.get("baseSpreadDegrees") or {},
            "max_degrees": raw.get("maximumSpreadDegrees") or {},
            "runtime_scale": raw.get("runtimeScaleFactor"),
        }

    def _recoil(profile_id: Optional[str]) -> Dict[str, Any]:
        raw = (handling.get("recoilProfiles") or {}).get(profile_id or "", {})
        out: Dict[str, Any] = {}
        for phase in ("continuousFire", "loop"):
            phase_raw = raw.get(phase) or {}
            if not phase_raw:
                continue
            out[phase] = {
                "horizontal_values": [float(x) for x in phase_raw.get("horizontalValues", [])],
                "vertical_values": [float(x) for x in phase_raw.get("verticalValues", [])],
                "horizontal_scale": float(phase_raw.get("horizontalScale", 1.0)),
                "vertical_scale": float(phase_raw.get("verticalScale", 1.0)),
            }
        return out

    assembly = pack.get("assembly") or {}
    sockets_raw = ((assembly.get("socketProviders") or {}).get(weapon_id) or {}).get("sockets") or []
    sockets = [
        {
            "socket_id": int(socket["socketId"]),
            "options": [str(x) for x in socket.get("optionItemIds", [])],
        }
        for socket in sockets_raw
    ]

    provider_sockets: Dict[str, List[Dict[str, Any]]] = {}
    for provider_id, provider in (assembly.get("socketProviders") or {}).items():
        if str(provider_id) == str(weapon_id):
            continue
        entries = []
        for socket in provider.get("sockets", []):
            options = [str(x) for x in socket.get("optionItemIds", [])]
            if options:
                entries.append({"socket_id": int(socket["socketId"]), "options": options})
        if entries:
            provider_sockets[str(provider_id)] = entries

    coupling_raw = ((assembly.get("coupling") or {}).get(weapon_id) or {}).get("rules") or []
    coupling = [
        {
            "condition_type": (rule.get("condition") or {}).get("type"),
            "condition_item_ids": [str(x) for x in (rule.get("condition") or {}).get("itemIds", [])],
            "target_socket_id": int(rule.get("targetSocketId", 0)),
            "mounted_item_id": str(rule.get("mountedItemId") or ""),
            "mount_policy": rule.get("mountPolicy"),
        }
        for rule in coupling_raw
    ]

    default_items: Dict[str, str] = {}
    for rule in coupling:
        if rule["mount_policy"] == "default":
            default_items[str(rule["target_socket_id"])] = rule["mounted_item_id"]

    record: Dict[str, Any] = {
        "weapon_id": weapon_id,
        "slug": _slugify(weapon_name, weapon_id),
        "name": weapon_name,
        "category": CATEGORY_ZH.get(str(catalog_object.get("categoryId") or ""), str(catalog_object.get("categoryId") or "")),
        "category_id": catalog_object.get("categoryId"),
        "ammo_type_id": ammo_type_id,
        "caliber": (ammo_by_type.get(ammo_type_id) or [""])[0],
        "ammo_item_ids": ammo_by_type.get(ammo_type_id, []),
        "rpm": float(sol.get("fireRateRpm") or 0.0),
        "fire_interval_s": float(sol.get("shotIntervalSeconds") or 0.0),
        "sdk_timing": {
            "fire_interval_s": float(sdk_timing.get("fireInterval") or 0.0),
            "fire_cd_s": float(sdk_timing.get("fireCd") or 0.0),
            "fire_delay_s": float(sdk_timing.get("fireDelayTime") or 0.0),
            "chamber_time_s": float(sdk_timing.get("chamberTime") or 0.0),
            "fire_rate_mode": sdk_timing.get("fireRateMode"),
            "burst_count": sdk_timing.get("burstCount"),
            "burst_fire_cd_s": float(sdk_timing.get("burstFireCd") or 0.0),
            "burst_fire_interval_s": float(sdk_timing.get("burstFireInterval") or 0.0),
            "burst_interval_s": float(sdk_timing.get("burstInterval") or 0.0),
            "auto_fire_single_interval_s": float(sdk_timing.get("autoFireSingleInterval") or 0.0),
            "auto_fire_burst_interval_s": float(sdk_timing.get("autoFireBurstInterval") or 0.0),
            "single_fire_tolerant_s": float(sdk_timing.get("singleFireTolerant") or 0.0),
        },
        "fire_modes": list(sol.get("supportedFireModes") or []),
        "selected_fire_mode": sol.get("selectedFireMode"),
        "burst_count": (weapon.get("fireControl") or {}).get("sdkTiming", {}).get("burstCount"),
        "muzzle_velocity_mps": float(sol.get("muzzleVelocityMps") or 0.0),
        "projectile_count": int(sol.get("projectileCount") or 1),
        "flesh_damage": float(
            (damage_profile or {}).get("base_damage") or sol.get("baseFleshDamage") or 0.0
        ),
        "armor_damage": float(
            (damage_profile or {}).get("base_armor_damage") or sol.get("baseArmorDamage") or 0.0
        ),
        "hitbox_multipliers": (
            (damage_profile or {}).get("hitbox_multipliers")
            or {k: float(v) for k, v in (sol.get("hitboxMultipliers") or {}).items()}
        ),
        "damage_profile": damage_profile,
        "damage_profile_source": "combat-pack" if damage_profile else "catalog-summary",
        "acoustics": {
            "shot_distance_m": float(
                ((combat_pack or {}).get("weapon") or {}).get("acoustics", {}).get("shotDistanceMeters")
                if combat_pack
                else 0.0
            ),
        },
        "falloff_segments": falloff_segments,
        "valid_range_m": float(sol.get("validDamageRangeMeters") or 0.0),
        "max_distance_m": float(sol.get("maximumDamageDistanceMeters") or 0.0),
        "clip_capacity": int(ammunition.get("clipCapacity") or 0),
        "max_carried_ammo": int(ammunition.get("maxCarriedAmmo") or 0),
        "timings": {
            "reload_s": float((weapon.get("timings") or {}).get("reloadSeconds") or 0.0),
            "empty_reload_s": float((weapon.get("timings") or {}).get("emptyReloadSeconds") or 0.0),
            "equip_s": float((weapon.get("timings") or {}).get("equipSeconds") or 0.0),
            "holster_s": float((weapon.get("timings") or {}).get("holsterSeconds") or 0.0),
            "sprint_to_fire_s": float((weapon.get("timings") or {}).get("sprintToFireSeconds") or 0.0),
        },
        "panel_attributes": panel_attrs,
        "aiming": {
            "ads_on_s": float(aiming_raw.get("adsOnTimeSeconds") or 0.0),
            "ads_off_s": float(aiming_raw.get("adsOffTimeSeconds") or 0.0),
            "zoom_rate": float(aiming_raw.get("zoomRate") or 1.0),
        },
        "references": {
            "waist_spread_profile_id": references.get("waistSpreadProfileId"),
            "waist_recoil_profile_id": references.get("waistRecoilProfileId"),
            "aiming_profile_id": aiming_profile_id,
            "bullet_profile_id": mode_references.get("bulletProfileId"),
            "movement_profile_id": mode_references.get("movementProfileId"),
            "attacker_profile_id": mode_references.get("attackerProfileId"),
        },
        "sway": {
            "base_breath_range_degrees": float((weapon.get("sway") or {}).get("baseBreathRangeDegrees") or 0.0),
            "gun_sway_be_hit_scale": float((weapon.get("sway") or {}).get("gunSwayBeHitScale") or 0.0),
            "camera_sway_be_hit_scale": float((weapon.get("sway") or {}).get("cameraSwayBeHitScale") or 0.0),
        },
        "spread": {
            "hip": _spread(references.get("waistSpreadProfileId")),
            "ads": _spread((handling.get("aimingProfiles") or {}).get(aiming_profile_id or "", {}).get("adsSpreadProfileId")),
        },
        "recoil": {
            "hip": _recoil(references.get("waistRecoilProfileId")),
            "ads": _recoil((handling.get("aimingProfiles") or {}).get(aiming_profile_id or "", {}).get("adsRecoilProfileId")),
        },
        "sockets": sockets,
        "provider_sockets": provider_sockets,
        "coupling": coupling,
        "default_items": default_items,
        "extra_occupancy": {
            str(item_id): [int(x) for x in (value or {}).get("occupiedSocketIds", [])]
            for item_id, value in (assembly.get("extraOccupancy") or {}).items()
        },
        "combat_variant_item_ids": [str(x) for x in (pack.get("combatVariantItemIds") or {}).get("sol", [])],
        "attribute_rules": (pack.get("attributeRules") or {}).get("defaults") or {},
        "attribute_rule_overrides": (pack.get("attributeRules") or {}).get("weaponOverrides") or {},
    }

    return _apply_field_overrides(record, overrides["weapons"], weapon_id, applied)


# --------------------------------------------------------------------------- #
# 排行索引（武器池 / 情景 / 验证样本）
# --------------------------------------------------------------------------- #
def normalize_ranking_index(index: Dict[str, Any]) -> Dict[str, Any]:
    """归一化官方 firefight 排行索引中的武器池、情景与距离口径。"""
    catalog = index.get("catalog") or {}
    profiles = catalog.get("profiles") or []
    distance_range = catalog.get("distanceRange") or {}

    weapons: List[Dict[str, Any]] = []
    for profile in profiles:
        if profile.get("weaponType") not in RANKED_WEAPON_TYPES:
            continue
        weapons.append(
            {
                "weapon_id": str(profile.get("weaponId")),
                "variant_item_id": profile.get("variantItemId"),
                "profile_key": f"{profile.get('weaponId')}:{profile.get('variantItemId') or 'base'}",
                "name": profile.get("name"),
                "source_name": profile.get("sourceName"),
                "base_weapon_name": profile.get("baseWeaponName"),
                "weapon_type": profile.get("weaponType"),
                "is_variant": bool(profile.get("isVariant")),
                "variant_item_name": profile.get("variantItemName"),
                "configuration_count": int(profile.get("configurationCount") or 0),
                "candidates": [
                    {
                        "candidate_id": candidate.get("candidateId"),
                        "loadout_config": candidate.get("loadoutConfig") or [],
                        "tunes": candidate.get("tunes") or {},
                        "loadout_item_ids": [str(x) for x in candidate.get("loadoutItemIds") or []],
                        "loadout_item_names": candidate.get("loadoutItemNames") or [],
                        "fire_rate": candidate.get("fireRate"),
                        "muzzle_velocity": candidate.get("muzzleVelocity"),
                        "ammo_item_id": candidate.get("ammoItemId"),
                        "ammo_level": candidate.get("ammoLevel"),
                    }
                    for candidate in profile.get("candidates") or []
                ],
            }
        )

    scenarios: List[Dict[str, Any]] = []
    for scenario in index.get("scenarios", []):
        defense = scenario.get("defense") or {}
        probability = scenario.get("probability") or {}
        scenarios.append(
            {
                "scenario_id": scenario.get("id"),
                "armor_level": scenario.get("defensePresetKey"),
                "ammo_level": scenario.get("ammoLevel"),
                "probability_preset": scenario.get("probabilityPresetKey"),
                "helmet_durability": defense.get("helmetDurability"),
                "armor_durability": defense.get("armorDurability"),
                "hit_probabilities": {k: float(v) for k, v in (probability.get("values") or {}).items()},
                "file": scenario.get("file"),
            }
        )

    return {
        "weapons": weapons,
        "scenarios": scenarios,
        "distance_range": {
            "min": int(distance_range.get("min", 0)),
            "max": int(distance_range.get("max", 80)),
            "step": int(distance_range.get("step", 1) or 1),
            "default_min": int(distance_range.get("defaultMin", 15)),
            "default_max": int(distance_range.get("defaultMax", 40)),
        },
        "default_scenario_id": index.get("defaultScenarioId"),
        "dynamic_inputs": index.get("dynamicInputs") or [],
    }


def normalize_validation_samples(
    scenario_files: Dict[str, Dict[str, Any]],
    distance_range: Dict[str, int],
) -> Dict[str, Any]:
    """抽取官方情景文件的 ``candidateMetrics`` 作为引擎交叉验证样本。

    ``candidateMetrics`` 形如 ``candidateId -> [[distance, expected_shots], ...]``，
    是无精校条件下的期望击杀发数基准，用于校验本系统的弹道链路。
    """
    samples: Dict[str, Any] = {}
    for scenario_id in sorted(scenario_files.keys()):
        payload = scenario_files[scenario_id]
        metrics = payload.get("candidateMetrics") or {}
        if not metrics:
            continue
        samples[scenario_id] = {
            "scenario": {
                "scenario_id": scenario_id,
                "armor_level": (payload.get("scenario") or {}).get("defensePresetKey"),
                "ammo_level": (payload.get("scenario") or {}).get("ammoLevel"),
                "probability_preset": (payload.get("scenario") or {}).get("probabilityPresetKey"),
                "defense": (payload.get("ranking") or {}).get("defense"),
                "hit_probabilities": (payload.get("ranking") or {}).get("hitProbabilities"),
                "distance_range": (payload.get("ranking") or {}).get("distanceRange") or distance_range,
            },
            "candidate_metrics": metrics,
        }
    return samples


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _write_json(path: str, payload: Any) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.write("\n")
    return _sha256_bytes(text.encode("utf-8"))


VALIDATION_SCENARIO_IDS = (
    "armor-4-ammo-4-default",
    "armor-4-ammo-5-default",
    "armor-5-ammo-5-default",
)


def sync_all(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    cache_dir: str = DEFAULT_CACHE_DIR,
    overrides_path: str = DEFAULT_OVERRIDES_PATH,
    refresh: bool = False,
    weapon_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """执行完整同步：下载上游数据 → 归一化 → 落盘 → 记录溯源。

    Args:
        output_dir: 归一化数据输出目录（默认 ``data/game``）。
        cache_dir: 上游原始数据缓存目录。
        overrides_path: 人工校正层路径。
        refresh: 强制忽略缓存重新下载。
        weapon_limit: 仅处理前 N 把枪，用于快速自检。

    Returns:
        同步摘要，包含产出文件、条目计数、覆盖记录与交叉校验提示。
    """
    os.makedirs(cache_dir, exist_ok=True)

    manifest, manifest_hash = _download_json("manifest.json", cache_dir, refresh=refresh)
    catalog_weapons, _ = _download_json("catalog/weapons.json", cache_dir, refresh=refresh)
    catalog_ammo, ammo_hash = _download_json("catalog/ammo.json", cache_dir, refresh=refresh)
    armors, armors_hash = _download_json("combat/defense/armors.json", cache_dir, refresh=refresh)
    helmets, helmets_hash = _download_json("combat/defense/helmets.json", cache_dir, refresh=refresh)
    interactions, interactions_hash = _download_json("combat/defense/ammo-interactions.json", cache_dir, refresh=refresh)
    locale_items, _ = _download_json("locales/zh-CN/items.json", cache_dir, refresh=refresh)
    locale_common, _ = _download_json("locales/zh-CN/common.json", cache_dir, refresh=refresh)
    ranking_index, ranking_hash = _download_json("rankings/firefight/index.json", cache_dir, refresh=refresh)

    validation_scenarios: Dict[str, Dict[str, Any]] = {}
    for scenario_id in VALIDATION_SCENARIO_IDS:
        try:
            payload, _ = _download_json(f"rankings/firefight/{scenario_id}.json", cache_dir, refresh=refresh)
            validation_scenarios[scenario_id] = payload
        except SourceUnavailable as exc:  # pragma: no cover - 网络分支
            logger.warning("验证情景 %s 获取失败：%s", scenario_id, exc)

    overrides = load_overrides(overrides_path)
    applied_overrides: List[Dict[str, Any]] = []

    item_names: Dict[str, str] = {str(k): str(v) for k, v in (locale_items.get("items") or {}).items()}

    # 弹药类型 → 口径字符串 与 弹药清单
    ammo_by_type: Dict[str, List[str]] = {}
    for ammo_id in sorted(catalog_ammo.get("ammo", {}).keys()):
        raw = catalog_ammo["ammo"][ammo_id]
        type_id = str(raw.get("ammoTypeId") or "")
        ammo_by_type.setdefault(type_id, []).append(ammo_id)

    ranking = normalize_ranking_index(ranking_index)

    # 需要处理的武器 ID（去重，保持排序保证确定性）
    weapon_ids: List[str] = sorted({entry["weapon_id"] for entry in ranking["weapons"]})
    if weapon_limit is not None:
        weapon_ids = weapon_ids[:weapon_limit]

    # build 包：装配/属性/曲线；combat 包：伤害/弹药/弹道档案。
    # 伤害建模必须同时具备两者，否则只能退化为 catalog 摘要值。
    build_packs: Dict[str, Dict[str, Any]] = {}
    combat_packs: Dict[str, Dict[str, Any]] = {}
    for weapon_id in weapon_ids:
        payload, _ = _download_json(f"packs/build/weapons/{weapon_id}.json", cache_dir, refresh=refresh)
        build_packs[weapon_id] = payload
        combat_payload, _ = _download_json(f"packs/combat/weapons/{weapon_id}.json", cache_dir, refresh=refresh)
        combat_packs[weapon_id] = combat_payload

    # 多把枪会重复携带同一弹药的档案；内容一致时去重，不一致则记入交叉校验。
    ammo_profiles: Dict[str, Dict[str, Any]] = {}
    ammo_profile_conflicts: List[Dict[str, Any]] = []
    for weapon_id in sorted(combat_packs.keys()):
        for ammo_id, prof in (((combat_packs[weapon_id].get("combat") or {}).get("ammoProfiles")) or {}).items():
            ammo_id = str(ammo_id)
            existing = ammo_profiles.get(ammo_id)
            if existing is not None and json.dumps(existing, sort_keys=True) != json.dumps(prof, sort_keys=True):
                ammo_profile_conflicts.append({"ammo_item_id": ammo_id, "weapon_id": weapon_id})
                continue
            ammo_profiles.setdefault(ammo_id, prof)

    cross_checks: List[Dict[str, Any]] = []
    ammo_records = normalize_ammo(
        catalog_ammo,
        interactions,
        overrides,
        applied_overrides,
        ammo_profiles=ammo_profiles,
        cross_checks=cross_checks,
    )
    ammo_type_to_caliber: Dict[str, str] = {}
    for record in ammo_records:
        ammo_type_to_caliber.setdefault(record["ammo_type_id"], record["caliber"])

    # 枪械：以官方排行武器池为准（含变体）
    weapons: List[Dict[str, Any]] = []
    seen_profiles: set = set()
    for entry in ranking["weapons"]:
        weapon_id = entry["weapon_id"]
        if weapon_id not in build_packs:
            continue
        catalog_object = (catalog_weapons.get("objects") or {}).get(weapon_id) or {}
        base_record = normalize_weapon(
            weapon_id,
            build_packs[weapon_id],
            catalog_object,
            entry["base_weapon_name"] or item_names.get(weapon_id, weapon_id),
            ammo_by_type,
            overrides,
            applied_overrides,
            combat_pack=combat_packs.get(weapon_id),
            cross_checks=cross_checks,
        )
        if base_record is None:
            continue
        base_record["caliber"] = ammo_type_to_caliber.get(base_record["ammo_type_id"], base_record["caliber"])
        profile_record = dict(base_record)
        profile_record.update(
            {
                "profile_key": entry["profile_key"],
                "is_variant": entry["is_variant"],
                "variant_item_id": entry["variant_item_id"],
                "variant_item_name": entry["variant_item_name"],
                "display_name": entry["name"],
                "reference_candidates": entry["candidates"],
                "configuration_count": entry["configuration_count"],
                "weapon_type": entry["weapon_type"],
            }
        )
        if entry["profile_key"] in seen_profiles:
            continue
        seen_profiles.add(entry["profile_key"])
        weapons.append(profile_record)

    parts = normalize_parts(build_packs, item_names)
    profiles = normalize_profiles(build_packs, combat_packs)
    mechanism = normalize_mechanism_curves(build_packs)
    armor = normalize_armor(armors, helmets, ranking_index, overrides, applied_overrides)

    samples = normalize_validation_samples(validation_scenarios, ranking["distance_range"])

    written: Dict[str, str] = {}
    written["weapons.json"] = _write_json(os.path.join(output_dir, "weapons.json"), {"weapons": weapons})
    written["ammo.json"] = _write_json(os.path.join(output_dir, "ammo.json"), {"ammo": ammo_records})
    written["armor.json"] = _write_json(os.path.join(output_dir, "armor.json"), armor)
    written["parts.json"] = _write_json(os.path.join(output_dir, "parts.json"), {"parts": parts})
    written["profiles.json"] = _write_json(
        os.path.join(output_dir, "profiles.json"),
        {"profiles": profiles["profiles"], "counts_by_kind": profiles["counts_by_kind"]},
    )
    written["mechanism.json"] = _write_json(os.path.join(output_dir, "mechanism.json"), mechanism)
    written["scenarios.json"] = _write_json(
        os.path.join(output_dir, "scenarios.json"),
        {
            "scenarios": ranking["scenarios"],
            "distance_range": ranking["distance_range"],
            "default_scenario_id": ranking["default_scenario_id"],
            "weapon_pool": [
                {"profile_key": w["profile_key"], "name": w["display_name"], "weapon_type": w["weapon_type"]}
                for w in weapons
            ],
        },
    )
    written["validation_samples.json"] = _write_json(
        os.path.join(output_dir, "validation_samples.json"),
        {"samples": samples},
    )
    written["stat_labels.json"] = _write_json(
        os.path.join(output_dir, "stat_labels.json"),
        {"stats": locale_common.get("stats") or {}}, 
    )

    provenance = {
        "source": {
            "name": SOURCE_NAME,
            "base_url": SOURCE_BASE,
            "note": (
                "该数据集为公开数据同步副本（部分文件自述权威性 "
                "DeltaForceDataEditorPublishedDataSynchronizedCopy），非腾讯官方 API。"
                "所有数值在使用前须经覆盖层或实测核验，详见 overrides 与核验状态字段。"
            ),
            "dataset_version": manifest.get("dataVersion"),
            "dataset_version_hash": manifest.get("version"),
            "schema_version": manifest.get("schemaVersion"),
            "calculator_contracts": manifest.get("calculatorContracts"),
            "manifest_sha256": manifest_hash,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        },
        "upstream_hashes": {
            "catalog/ammo.json": ammo_hash,
            "combat/defense/armors.json": armors_hash,
            "combat/defense/helmets.json": helmets_hash,
            "combat/defense/ammo-interactions.json": interactions_hash,
            "rankings/firefight/index.json": ranking_hash,
        },
        "outputs": written,
        "counts": {
            "weapons": len(weapons),
            "ammo": len(ammo_records),
            "ammo_with_combat_profile": sum(1 for r in ammo_records if r["profile_source"] == "combat-pack"),
            "parts": len(parts),
            "profiles": len(profiles["profiles"]),
            "armor_levels": len(armor["levels"]),
            "mechanism_curves": len(mechanism.get("curves", {})),
            "validation_scenarios": len(samples),
        },
        "integrity": {
            "mechanism_disagreements": mechanism.get("disagreements", []),
            "profile_conflicts": profiles["conflicts"],
            "ammo_profile_conflicts": ammo_profile_conflicts,
            "source_cross_checks": cross_checks,
            "weapons_with_rule_overrides": [
                w["profile_key"] for w in weapons if w.get("attribute_rule_overrides")
            ],
            "weapons_without_damage_profile": [
                w["profile_key"] for w in weapons if not w.get("damage_profile")
            ],
            "applied_overrides": applied_overrides,
            "verify_status": {
                "weapons.json": "cross-checked-against-combat-pack" if not applied_overrides else "partially-verified",
                "ammo.json": "cross-checked-against-combat-pack",
                "armor.json": "cross-checked-against-official-preset",
                "parts.json": "derived",
                "profiles.json": "derived",
                "mechanism.json": "derived",
            },
        },
    }
    written["provenance.json"] = _write_json(os.path.join(output_dir, "provenance.json"), provenance)

    return {
        "output_dir": output_dir,
        "files": written,
        "counts": provenance["counts"],
        "applied_overrides": applied_overrides,
        "disagreements": mechanism.get("disagreements", []),
        "dataset_version": manifest.get("dataVersion"),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="官方游戏数据同步与归一化")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR)
    parser.add_argument("--overrides", default=DEFAULT_OVERRIDES_PATH)
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新下载")
    parser.add_argument("--weapon-limit", type=int, default=None, help="仅处理前 N 把枪（自检用）")
    args = parser.parse_args()

    summary = sync_all(
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        overrides_path=args.overrides,
        refresh=args.refresh,
        weapon_limit=args.weapon_limit,
    )
    print(f"数据同步完成（数据集版本 {summary['dataset_version']}）：")
    for key, value in summary["counts"].items():
        print(f"  {key}: {value}")
    if summary["applied_overrides"]:
        print(f"  生效的人工覆盖：{len(summary['applied_overrides'])} 条")
    if summary["disagreements"]:
        print(f"  ⚠ 上游数据存在分歧项：{len(summary['disagreements'])} 条（详见 provenance.json）")


if __name__ == "__main__":
    main()
