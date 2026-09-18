"""Unit tests for the gunsmith weapon modification system focusing on best-value attachment blueprints."""

import pytest
from src.engine.gunsmith import (
    MAINSTREAM_BUILDS,
    get_all_builds,
    get_detailed_build,
    get_all_calibrated_builds,
    DetailedWeaponBuild,
)
from src.models import WeaponBuild


def test_mainstream_builds_coverage():
    assert len(MAINSTREAM_BUILDS) >= 15
    for gun_id, build in MAINSTREAM_BUILDS.items():
        assert build.gun_id == gun_id
        assert build.total_mod_cost > 0
        assert len(build.attachments) >= 4
        # Verify slot naming in formatted attachments (integrally suppressed weapons like AS-Val/VSS have built-in suppressed barrels)
        formatted = build.formatted_attachment_list
        if gun_id not in ["asval", "vss"]:
            assert any("枪管" in item or "枪口" in item for item in formatted)
        assert any("握把" in item or "托" in item for item in formatted)
        # Ensure build_code and code_status are eliminated
        assert not hasattr(build, "build_code")
        assert not hasattr(build, "code_status")
        assert build.stability_bonus >= 0.0


def test_gunsmith_practical_builds_without_share_codes():
    builds = get_all_calibrated_builds()
    assert len(builds) == 50

    # Verify MP7 has extended magazine
    mp7_build = builds["mp7"]
    assert any("40发" in att or "弹匣" in att for att in mp7_build.attachments)
    assert len(mp7_build.tuning_instructions) > 0
    assert mp7_build.mod_cost > 0
    assert not hasattr(mp7_build, "build_code")
    assert mp7_build.stability_bonus >= 0.0

    # Verify SVD has 3x scope, not 8x
    svd_build = builds["svd"]
    assert any("3倍" in att or "1p-29" in att or "瞄准镜" in att for att in svd_build.attachments)
    assert not any("8倍" in att for att in svd_build.attachments)
    assert svd_build.velocity_bonus_pct >= 0.0


def test_get_all_builds():
    builds = get_all_builds()
    assert len(builds) >= 45
    assert all(isinstance(b, WeaponBuild) for b in builds)
    assert all(b.mod_cost > 0 for b in builds)
    assert all(len(b.attachments) >= 4 for b in builds)
    # Ensure every attachment has slot specification
    for b in builds:
        for att in b.attachments:
            assert ":" in att, f"Attachment '{att}' in gun {b.gun_id} missing slot prefix"


def test_get_detailed_build():
    m4_build = get_detailed_build("m4a1")
    assert m4_build is not None
    assert isinstance(m4_build, DetailedWeaponBuild)
    assert m4_build.gun_name == "M4A1突击步枪"
    assert m4_build.total_mod_cost == 93711
    assert len(m4_build.attachments) == 6

    # Verify attachment slots
    slots = [a.slot for a in m4_build.attachments]
    assert "枪管" in slots
    assert "枪口" in slots
    assert "前握把" in slots
    assert "瞄具" in slots
    assert "弹匣" in slots
    assert "枪托" in slots

    # Non-existent gun returns None
    assert get_detailed_build("unknown_gun_xyz") is None


def test_create_dynamic_build_and_helpers(tmp_path):
    from src.engine.gunsmith import (
        create_dynamic_build,
        get_official_price,
        get_all_builds_for_guns,
        CURATED_BUILDS,
    )
    import json

    # get_official_price
    assert get_official_price("不存在的神秘配件", fallback=8888) == 8888

    # create_dynamic_build for curated gun
    b_m4 = create_dynamic_build("m4a1", "M4A1", "突击步枪")
    assert b_m4.gun_id == "m4a1"

    # dynamic builds for different categories
    b_smg = create_dynamic_build("custom_smg", "自定义冲锋枪", "冲锋枪")
    assert "机动近战突袭改" in b_smg.build_name
    assert b_smg.ads_modifier_ms == -18

    b_lmg = create_dynamic_build("custom_lmg", "自定义轻机枪", "轻机枪")
    assert "阵地火力压制改" in b_lmg.build_name
    assert b_lmg.ads_modifier_ms == 15

    b_dmr = create_dynamic_build("custom_dmr", "自定义连狙", "精确射手步枪")
    assert "高精点射压制改" in b_dmr.build_name
    assert b_dmr.velocity_bonus_pct == 0.09

    b_ar = create_dynamic_build("custom_ar", "自定义步枪", "突击步枪")
    assert "中距全能稳健改" in b_ar.build_name

    # get_all_builds_for_guns with custom file
    guns_file = tmp_path / "test_guns.json"
    guns_file.write_text(
        json.dumps([
            {"id": "m4a1", "name": "M4A1突击步枪", "category": "突击步枪"},
            {"id": "custom_smg", "name": "自定义冲锋枪", "category": "冲锋枪"},
        ]),
        encoding="utf-8",
    )
    builds = get_all_builds_for_guns(guns_file=str(guns_file))
    # Returns the guns from the file plus any remaining curated builds
    assert any(b.gun_id == "custom_smg" for b in builds)
    assert any(b.gun_id == "m4a1" for b in builds)

    # get_all_builds_for_guns fallback on missing file
    missing_builds = get_all_builds_for_guns(guns_file=str(tmp_path / "missing.json"))
    assert len(missing_builds) == len(CURATED_BUILDS)

