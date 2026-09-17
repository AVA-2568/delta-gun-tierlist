import json
import os
import pytest
from pydantic import ValidationError
from src.models import (
    GunMeta,
    DamageDropoff,
    AmmoPrice,
    WeaponBuild,
    SimulationResult,
    TierEntry,
    DataSourceStatus,
)


def test_gun_meta_validation():
    dropoff = DamageDropoff(max_distance=20.0, chest_damage=32.0, armor_damage=28.0)
    gun = GunMeta(
        id="m4a1",
        name="M4A1",
        category="突击步枪",
        caliber="5.56x45mm",
        rpm=800,
        bullet_velocity=750.0,
        base_price=35000,
        default_mag_size=30,
        ads_time_ms=220,
        recoil_control=72.0,
        stability=68.0,
        dropoffs=[dropoff],
    )
    assert gun.id == "m4a1"
    assert gun.rpm == 800
    assert len(gun.dropoffs) == 1
    assert gun.dropoffs[0].chest_damage == 32.0


def test_ammo_price_validation():
    ammo = AmmoPrice(
        caliber="5.56x45mm",
        level=4,
        name="5.56mm A1",
        penetration=42,
        price_per_round=1200,
        source="baseline",
        updated_at="2026-09-17T00:00:00Z",
    )
    assert ammo.price_per_round == 1200
    assert ammo.level == 4


def test_invalid_gun_rpm():
    with pytest.raises(ValidationError):
        GunMeta(
            id="bad_gun",
            name="Bad",
            category="突击步枪",
            caliber="5.56x45mm",
            rpm=-100,  # Invalid
            bullet_velocity=700.0,
            base_price=30000,
            default_mag_size=30,
            ads_time_ms=200,
            recoil_control=50.0,
            stability=50.0,
            dropoffs=[
                DamageDropoff(
                    max_distance=25.0, chest_damage=30.0, armor_damage=25.0
                )
            ],
        )


def test_invalid_gun_empty_dropoffs():
    with pytest.raises(ValidationError):
        GunMeta(
            id="no_dropoff_gun",
            name="NoDropoff",
            category="突击步枪",
            caliber="5.56x45mm",
            rpm=800,
            bullet_velocity=700.0,
            base_price=30000,
            default_mag_size=30,
            ads_time_ms=200,
            recoil_control=50.0,
            stability=50.0,
            dropoffs=[],  # Invalid: must have at least 1 dropoff
        )


def test_invalid_recoil_control_range():
    with pytest.raises(ValidationError):
        GunMeta(
            id="over_recoil_gun",
            name="OverRecoil",
            category="突击步枪",
            caliber="5.56x45mm",
            rpm=800,
            bullet_velocity=700.0,
            base_price=30000,
            default_mag_size=30,
            ads_time_ms=200,
            recoil_control=150.0,  # Invalid: max is 100
            stability=50.0,
            dropoffs=[
                DamageDropoff(
                    max_distance=25.0, chest_damage=30.0, armor_damage=25.0
                )
            ],
        )


def test_invalid_ammo_price():
    with pytest.raises(ValidationError):
        AmmoPrice(
            caliber="5.56x45mm",
            level=4,
            name="5.56mm A1",
            penetration=42,
            price_per_round=-500,  # Invalid
            source="baseline",
            updated_at="2026-09-17T00:00:00Z",
        )


def test_weapon_build_validation():
    build = WeaponBuild(
        gun_id="m4a1",
        build_name="烽火高性价比实用改",
        build_code="M4A1-6H3R-PRACTICAL",
        mod_cost=42000,
        ads_modifier_ms=-15,
        recoil_bonus=16.0,
        attachments=["长枪管", "战术消音器"],
    )
    assert build.gun_id == "m4a1"
    assert build.mod_cost == 42000
    assert len(build.attachments) == 2


def test_weapon_build_invalid_mod_cost():
    with pytest.raises(ValidationError):
        WeaponBuild(
            gun_id="m4a1",
            build_name="非法方案",
            build_code="TEST-CODE",
            mod_cost=-1000,  # Invalid
            ads_modifier_ms=0,
            recoil_bonus=0.0,
        )


def test_simulation_result_validation():
    sim = SimulationResult(
        stk=4,
        theoretical_ttk_ms=225.0,
        practical_ttk_ms=247.5,
        ehr=0.91,
    )
    assert sim.stk == 4
    assert sim.ehr == 0.91

    with pytest.raises(ValidationError):
        SimulationResult(
            stk=0,  # Invalid: stk must be > 0
            theoretical_ttk_ms=0.0,
            practical_ttk_ms=0.0,
            ehr=0.9,
        )

    with pytest.raises(ValidationError):
        SimulationResult(
            stk=4,
            theoretical_ttk_ms=200.0,
            practical_ttk_ms=220.0,
            ehr=1.5,  # Invalid: ehr must be <= 1.0
        )


def test_tier_entry_validation():
    entry = TierEntry(
        gun_id="m4a1",
        gun_name="M4A1",
        category="突击步枪",
        distance_m=15,
        armor_level=4,
        ammo_level=4,
        stk=4,
        practical_ttk_ms=247.5,
        ammo_60_cost=69000,
        total_loadout_cost=146000,
        single_kill_cost=4600,
        combat_score=85.5,
        handling_score=80.0,
        cost_score=78.0,
        composite_score=82.5,
        tier="T1",
        build_code="M4A1-6H3R-PRACTICAL",
        tags=["近战撕裂", "高性价比"],
    )
    assert entry.tier == "T1"
    assert entry.composite_score == 82.5
    assert len(entry.tags) == 2


def test_data_source_status_validation():
    status_live = DataSourceStatus(
        source="zxfps_live",
        is_fallback=False,
        fallback_tier=0,
        updated_at="2026-09-17T12:00:00Z",
    )
    assert status_live.source == "zxfps_live"
    assert not status_live.is_fallback
    assert status_live.fallback_tier == 0

    status_fallback = DataSourceStatus(
        source="baseline",
        is_fallback=True,
        fallback_tier=2,
        updated_at="2026-09-17T00:00:00Z",
    )
    assert status_fallback.is_fallback
    assert status_fallback.fallback_tier == 2


def test_validate_existing_json_datasets():
    with open("data/base_guns.json", "r", encoding="utf-8") as f:
        guns_data = json.load(f)
    guns = [GunMeta.model_validate(item) for item in guns_data]
    assert len(guns) >= 6

    with open("data/baseline_ammo_prices.json", "r", encoding="utf-8") as f:
        ammo_data = json.load(f)
    ammos = [AmmoPrice.model_validate(item) for item in ammo_data]
    assert len(ammos) >= 6

    with open("data/default_builds.json", "r", encoding="utf-8") as f:
        builds_data = json.load(f)
    builds = [WeaponBuild.model_validate(item) for item in builds_data]
    assert len(builds) >= 6
