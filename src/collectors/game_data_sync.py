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
4. 残余记录衔接：重跑同步器后再生成 ``data/game/*.json``，需重跑
   ``python tools/verify_official_reproduction.py --record-residual-conclusion "<结论>"``
   刷新 ``provenance.json`` 的 ``integrity.official_reproduction_residual``——
   ``tests/test_official_reproduction.py`` 依赖该记录对齐，缺失或过期即 fail。

模块划分为三层，本模块只保留编排与 CLI：

* :mod:`src.collectors.http` —— 上游下载（``SOURCE_BASE`` / ``SourceUnavailable``）。
* :mod:`src.collectors.overrides` —— 覆盖层（``DEFAULT_OVERRIDES_PATH`` / ``load_overrides``）。
* :mod:`src.collectors.normalize` —— 各 schema 归一化函数。

依赖方向单向：game_data_sync → {http, overrides, normalize}；三个子模块互不反向引用。
``sync_all`` 与 ``main`` 的模块路径与签名保持不变（``python -m src.collectors.game_data_sync``）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.collectors.http import SOURCE_BASE, SourceUnavailable, _download_json, _sha256_bytes
from src.collectors.normalize import (
    ammo_type_to_caliber_map,
    normalize_ammo,
    normalize_armor,
    normalize_mechanism_curves,
    normalize_parts,
    normalize_profiles,
    normalize_ranking_index,
    normalize_validation_samples,
    normalize_weapon,
)
from src.collectors.overrides import DEFAULT_OVERRIDES_PATH, load_overrides

logger = logging.getLogger(__name__)

SOURCE_NAME = "dfttk-v3"

DEFAULT_OUTPUT_DIR = os.path.join("data", "game")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _write_json(path: str, payload: Any) -> str:
    """落盘 JSON 并返回内容 SHA256。

    返回值作为 provenance.outputs 记录口径，必须与 tests/test_data_integrity.py
    及 tools/verify_official_reproduction.py --refresh-output-hashes 一致：
    对 json.dumps 结果（**不含尾换行**）计算；尾换行仅落盘时追加。
    口径漂移会使 CI 哈希回归（test_provenance_output_hashes_match）fail。
    """
    from pathlib import Path
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)
    target.write_text(body + "\n", encoding="utf-8", newline="\n")
    return _sha256_bytes(body.encode("utf-8"))



def sync_all(
    output_dir: str = DEFAULT_OUTPUT_DIR,
    overrides_path: str = DEFAULT_OVERRIDES_PATH,
    weapon_limit: Optional[int] = None,
) -> Dict[str, Any]:
    """执行完整同步：下载上游数据 → 归一化 → 落盘 → 记录溯源。

    Args:
        output_dir: 归一化数据输出目录（默认 ``data/game``）。
        overrides_path: 人工校正层路径。
        weapon_limit: 仅处理前 N 把枪，用于快速自检。

    Returns:
        同步摘要，包含产出文件、条目计数、覆盖记录与交叉校验提示。
    """
    manifest, manifest_hash = _download_json("manifest.json")
    catalog_weapons, _ = _download_json("catalog/weapons.json")
    catalog_ammo, ammo_hash = _download_json("catalog/ammo.json")
    armors, armors_hash = _download_json("combat/defense/armors.json")
    helmets, helmets_hash = _download_json("combat/defense/helmets.json")
    interactions, interactions_hash = _download_json("combat/defense/ammo-interactions.json")
    locale_items, _ = _download_json("locales/zh-CN/items.json")
    ranking_index, ranking_hash = _download_json("rankings/firefight/index.json")

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

    # 验证样本：官方 index 全量情景（不遗漏任何带 candidateMetrics 的情景）。
    # index 的 file 字段为相对 base URL 的完整路径（如 rankings/firefight/xxx.json），
    # 需剥离已知目录前缀；缺失时回退 {scenario_id}.json。
    validation_scenarios: Dict[str, Dict[str, Any]] = {}
    for scenario in ranking["scenarios"]:
        sid = scenario["scenario_id"]
        rel = scenario.get("file") or f"{sid}.json"
        prefix = "rankings/firefight/"
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
        try:
            payload, _ = _download_json(f"rankings/firefight/{rel}")
            validation_scenarios[sid] = payload
        except SourceUnavailable as exc:  # pragma: no cover - 网络分支
            logger.warning("验证情景 %s 获取失败：%s", sid, exc)

    # 需要处理的武器 ID（去重，保持排序保证确定性）
    weapon_ids: List[str] = sorted({entry["weapon_id"] for entry in ranking["weapons"]})
    if weapon_limit is not None:
        weapon_ids = weapon_ids[:weapon_limit]

    # build 包：装配/属性/曲线；combat 包：伤害/弹药/弹道档案。
    # 伤害建模必须同时具备两者，否则只能退化为 catalog 摘要值。
    build_packs: Dict[str, Dict[str, Any]] = {}
    combat_packs: Dict[str, Dict[str, Any]] = {}
    for weapon_id in weapon_ids:
        payload, _ = _download_json(f"packs/build/weapons/{weapon_id}.json")
        build_packs[weapon_id] = payload
        combat_payload, _ = _download_json(f"packs/combat/weapons/{weapon_id}.json")
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
    ammo_merges: List[Dict[str, Any]] = []
    ammo_records = normalize_ammo(
        catalog_ammo,
        interactions,
        overrides,
        applied_overrides,
        ammo_profiles=ammo_profiles,
        cross_checks=cross_checks,
        merges=ammo_merges,
    )
    # 弹药类型 → 口径：取该类型内首个非空 caliber 的弹药（逻辑见 normalize 同名函数）
    ammo_type_to_caliber = ammo_type_to_caliber_map(ammo_records)

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
            ammo_type_to_caliber=ammo_type_to_caliber,
        )
        if base_record is None:
            continue
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
    written["mechanism.json"] = _write_json(
        os.path.join(output_dir, "mechanism.json"), {"curves": mechanism["curves"]}
    )
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
        "merges": ammo_merges,
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
        "validation_scenario_count": len(samples),
        "validation_sample_points": sum(
            len(points)
            for entry in samples.values()
            for _, points in entry["candidate_metrics"]
        ),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="官方游戏数据同步与归一化")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--overrides", default=DEFAULT_OVERRIDES_PATH)
    parser.add_argument("--weapon-limit", type=int, default=None, help="仅处理前 N 把枪（自检用）")
    args = parser.parse_args()

    summary = sync_all(
        output_dir=args.output_dir,
        overrides_path=args.overrides,
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
