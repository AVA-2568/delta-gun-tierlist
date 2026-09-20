"""归一化数据层完整性测试。

校验 ``data/game/*.json`` 的结构、关联与溯源完整性（不联网）。
"""

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = os.path.join(ROOT, "data", "game")

REQUIRED_FILES = (
    "weapons.json",
    "ammo.json",
    "armor.json",
    "parts.json",
    "profiles.json",
    "mechanism.json",
    "scenarios.json",
    "validation_samples.json",
    "stat_labels.json",
    "provenance.json",
)


def _load(name):
    with open(os.path.join(G, name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("name", REQUIRED_FILES)
def test_required_data_files_exist(name):
    path = os.path.join(G, name)
    assert os.path.exists(path), f"缺少数据文件 {name}"
    assert os.path.getsize(path) > 0


def test_weapons_have_required_fields():
    weapons = _load("weapons.json")["weapons"]
    assert len(weapons) >= 60
    required = {
        "weapon_id", "profile_key", "name", "category", "panel_attributes",
        "damage_profile", "falloff_segments", "attribute_rules", "sdk_timing",
        "reference_candidates",
    }
    for weapon in weapons:
        assert required <= set(weapon), f"{weapon.get('profile_key')} 缺字段：{required - set(weapon)}"
        assert set(weapon["panel_attributes"]) == {
            "effective_range", "recoil_control", "waist_accuracy", "handling", "stability"
        }
        assert weapon["fire_interval_s"] > 0


def test_variants_are_marked_and_carry_item():
    weapons = _load("weapons.json")["weapons"]
    for weapon in weapons:
        if weapon.get("is_variant"):
            assert weapon.get("variant_item_id"), f"{weapon['profile_key']} 变体缺 variant_item_id"


def test_ammo_penetration_matrix_is_complete():
    ammo = _load("ammo.json")["ammo"]
    assert len(ammo) >= 100
    for record in ammo:
        matrix = record.get("penetration_matrix")
        assert isinstance(matrix, dict) and matrix, f"{record['ammo_item_id']} 缺穿透矩阵"
        for level in ("0", "1", "2", "3", "4", "5", "6"):
            assert level in matrix, f"{record['ammo_item_id']} 缺护甲等级 {level}"
            entry = matrix[level]
            for key in ("body_health_rate", "helmet_health_rate",
                        "body_durability_rate", "helmet_durability_rate", "penetrates"):
                assert key in entry, f"{record['ammo_item_id']} 矩阵缺 {key}"
        assert record["flesh_damage_multiplier"] > 0


def test_low_pen_against_high_armor_yields_zero_health_damage():
    """低穿高时官方标记 penetrates=false 且肉伤穿透率为 0（钝伤为 0）。"""
    ammo = {a["ammo_item_id"]: a for a in _load("ammo.json")["ammo"]}
    record = ammo["37100300001"]  # M855 (3 级)
    assert record["penetration_matrix"]["4"]["penetrates"] is False
    assert record["penetration_matrix"]["4"]["body_health_rate"] == 0.0


def test_armor_levels_expose_covered_hit_areas():
    levels = _load("armor.json")["levels"]
    assert set(levels) >= {"3", "4", "5", "6"}
    for level, payload in levels.items():
        for slot in ("helmet", "armor"):
            assert payload[slot]["covered_hit_areas"], f"L{level} {slot} 缺覆盖部位"
            assert payload[slot]["max_durability"] > 0
    # L5/L6 背心额外覆盖上臂（不得硬编码，须由数据驱动）
    assert "upperArm" in levels["5"]["armor"]["covered_hit_areas"]
    assert "upperArm" not in levels["4"]["armor"]["covered_hit_areas"]


def test_profiles_cover_all_kinds():
    profiles = _load("profiles.json")["profiles"]
    kinds = {p.get("kind") for p in profiles.values()}
    assert {"spread", "recoil", "movement", "aiming", "bullet", "damage"} <= kinds


def test_scenarios_match_official_index():
    scenarios = _load("scenarios.json")
    ids = [s["scenario_id"] for s in scenarios["scenarios"]]
    assert len(ids) == 21, f"官方情景应为 21 个，实际 {len(ids)}"
    assert len(set(ids)) == 21
    distance = scenarios["distance_range"]
    assert distance == {"min": 0, "max": 80, "step": 1, "default_min": 15, "default_max": 40}
    assert len(scenarios["weapon_pool"]) == 61
    for scenario in scenarios["scenarios"]:
        probs = scenario["hit_probabilities"]
        assert abs(sum(probs.values()) - 1.0) < 1e-6, f"{scenario['scenario_id']} 命中分布和不为 1"


def test_validation_samples_reference_known_scenarios():
    samples = _load("validation_samples.json")["samples"]
    scenario_ids = {s["scenario_id"] for s in _load("scenarios.json")["scenarios"]}
    assert samples, "至少应入库一个官方验证情景"
    for sid, payload in samples.items():
        assert sid in scenario_ids
        assert payload["candidate_metrics"], f"{sid} 缺 candidate_metrics"
        for _cid, points in payload["candidate_metrics"]:
            for distance, shots in points:
                assert distance >= 0
                assert shots > 0


def test_provenance_has_no_integrity_conflicts():
    provenance = _load("provenance.json")
    source = provenance["source"]
    assert source["name"] == "dfttk-v3"
    assert "非腾讯官方 API" in source["note"] or "非官方" in source["note"]
    integrity = provenance["integrity"]
    for key in ("mechanism_disagreements", "profile_conflicts",
                "ammo_profile_conflicts", "source_cross_checks"):
        assert integrity[key] == [], f"provenance.{key} 非空：{integrity[key]}"
    counts = provenance["counts"]
    assert counts["weapons"] == 61
    assert counts["validation_scenarios"] >= 1
