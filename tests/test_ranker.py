"""Unit tests for loadout cost calculation, multi-dimensional scoring, and weapon ranking engine."""

import json
import pytest
from src.models import (
    GunMeta,
    DamageDropoff,
    AmmoPrice,
    WeaponBuild,
    TierEntry,
)
from src.engine.cost_model import calc_loadout_cost
from src.engine.ranker import rank_weapons, calc_handling_score, resolve_ammo


@pytest.fixture
def sample_m4a1() -> GunMeta:
    return GunMeta(
        id="m4a1",
        name="M4A1",
        category="突击步枪",
        caliber="5.56x45mm",
        rpm=800,
        bullet_velocity=750.0,
        base_price=35000,
        default_mag_size=30,
        ads_time_ms=220,
        recoil_control=75.0,
        stability=70.0,
        dropoffs=[
            DamageDropoff(max_distance=25.0, chest_damage=34.0, armor_damage=30.0),
            DamageDropoff(max_distance=50.0, chest_damage=28.0, armor_damage=25.0),
        ],
    )


@pytest.fixture
def sample_m4a1_build() -> WeaponBuild:
    return WeaponBuild(
        gun_id="m4a1",
        build_name="实用改",
        mod_cost=45000,
        ads_modifier_ms=-20,
        recoil_bonus=15.0,
        attachments=["消音器", "直角握把"],
        tuning_instructions=["枪托: 配重向右拉满(+50g，后坐-6%)"],
    )


@pytest.fixture
def sample_556_ammo_lv4() -> AmmoPrice:
    return AmmoPrice(
        caliber="5.56x45mm",
        level=4,
        name="5.56 M855A1",
        penetration=42,
        price_per_round=1000,
        source="test",
        updated_at="2026-09-17",
    )


def test_cost_calculation_60_rounds(sample_m4a1, sample_m4a1_build, sample_556_ammo_lv4):
    """Test standard 60-round loadout cost calculation matching plan specifications."""
    total_cost, ammo_60_cost, single_kill_cost = calc_loadout_cost(
        sample_m4a1, sample_m4a1_build, sample_556_ammo_lv4, stk=4, reserve_rounds=60
    )
    assert ammo_60_cost == 60 * 1000  # 60000
    assert total_cost == 35000 + 45000 + 60000  # 140000
    assert single_kill_cost == 4 * 1000  # 4000


def test_cost_calculation_custom_reserves(sample_m4a1, sample_m4a1_build, sample_556_ammo_lv4):
    """Test cost calculation with non-standard reserve rounds and default stk."""
    total_cost, ammo_cost, kill_cost = calc_loadout_cost(
        sample_m4a1, sample_m4a1_build, sample_556_ammo_lv4, stk=5, reserve_rounds=90
    )
    assert ammo_cost == 90 * 1000
    assert total_cost == 35000 + 45000 + 90000
    assert kill_cost == 5 * 1000


def test_handling_score_formula():
    """Verify handling score formula: 0.4*recoil + 0.3*stability + 0.3*min(100, rpm/10)."""
    # Recoil 75, Stability 70, RPM 800 -> 0.4*75 + 0.3*70 + 0.3*80 = 30 + 21 + 24 = 75.0
    score = calc_handling_score(recoil=75.0, stability=70.0, rpm=800)
    assert score == pytest.approx(75.0, 0.01)

    # RPM 1100 (should cap at 100 for RPM/10 component)
    score_high_rpm = calc_handling_score(recoil=80.0, stability=70.0, rpm=1100)
    # 0.4*80 + 0.3*70 + 0.3*100 = 32 + 21 + 30 = 83.0
    assert score_high_rpm == pytest.approx(83.0, 0.01)


def test_rank_weapons_tier_distribution_with_baseline_datasets():
    """Verify that ranking all baseline guns produces valid sorted TierEntries spanning tiers."""
    with open("data/base_guns.json", "r", encoding="utf-8") as f:
        guns = [GunMeta.model_validate(x) for x in json.load(f)]
    with open("data/default_builds.json", "r", encoding="utf-8") as f:
        builds = {
            x["gun_id"]: WeaponBuild.model_validate(
                {k: v for k, v in x.items() if k in WeaponBuild.model_fields}
            )
            for x in json.load(f)
        }
    with open("data/baseline_ammo_prices.json", "r", encoding="utf-8") as f:
        ammo_list = [AmmoPrice.model_validate(x) for x in json.load(f)]
    ammo_dict = {(a.caliber, a.level): a for a in ammo_list}

    # Test scenario: 4 armor, 4 ammo, 15m
    results_44_15 = rank_weapons(
        guns=guns,
        builds=builds,
        ammo_prices=ammo_dict,
        armor_level=4,
        ammo_level=4,
        distance_m=15,
    )

    assert len(results_44_15) == len(guns)
    # Check strict descending order by composite_score
    for i in range(len(results_44_15) - 1):
        assert results_44_15[i].composite_score >= results_44_15[i + 1].composite_score

    # Check score bounds and tier rules
    for entry in results_44_15:
        assert isinstance(entry, TierEntry)
        assert 0.0 <= entry.combat_score <= 100.0
        assert 0.0 <= entry.handling_score <= 100.0
        assert 0.0 <= entry.cost_score <= 100.0
        assert 0.0 <= entry.composite_score <= 100.0
        assert entry.caliber != ""
        assert len(entry.tags) > 0

        # Tier threshold checks
        if entry.composite_score >= 88.0:
            assert entry.tier == "T0"
        elif entry.composite_score >= 78.0:
            assert entry.tier == "T1"
        elif entry.composite_score >= 65.0:
            assert entry.tier == "T2"
        else:
            assert entry.tier == "T3"

    # Test scenario: 4 armor, 5 ammo, 15m (should have T0/T1 guns, 9x19mm weapons gated out)
    results_45_15 = rank_weapons(
        guns=guns,
        builds=builds,
        ammo_prices=ammo_dict,
        armor_level=4,
        ammo_level=5,
        distance_m=15,
    )
    guns_with_9mm = [g for g in guns if g.caliber == "9x19mm"]
    assert len(guns_with_9mm) > 0
    # Caliber gating: 9x19mm weapons have no level 5 ammo and must be excluded
    assert len(results_45_15) == len(guns) - len(guns_with_9mm)
    assert all(e.caliber != "9x19mm" for e in results_45_15)
    tiers_45 = {e.tier for e in results_45_15}
    assert "T0" in tiers_45 or "T1" in tiers_45


def test_rank_weapons_single_gun(sample_m4a1, sample_m4a1_build, sample_556_ammo_lv4):
    """Verify that a scenario with a single gun does not cause ZeroDivisionError."""
    ammo_dict = {("5.56x45mm", 4): sample_556_ammo_lv4}
    builds_dict = {"m4a1": sample_m4a1_build}

    results = rank_weapons(
        guns=[sample_m4a1],
        builds=builds_dict,
        ammo_prices=ammo_dict,
        armor_level=4,
        ammo_level=4,
        distance_m=15,
    )

    assert len(results) == 1
    entry = results[0]
    assert entry.combat_score == 100.0
    assert entry.cost_score == 100.0
    assert entry.gun_id == "m4a1"


def test_rank_weapons_missing_ammo_gating(sample_m4a1, sample_m4a1_build):
    """Verify that weapon with missing ammo is skipped via caliber gating."""
    results = rank_weapons(
        guns=[sample_m4a1],
        builds={"m4a1": sample_m4a1_build},
        ammo_prices={},
        armor_level=4,
        ammo_level=4,
        distance_m=15,
    )
    assert results == []


def test_rank_weapons_missing_build_fallback(sample_m4a1, sample_556_ammo_lv4):
    """Verify that a gun without an explicit build gracefully falls back to stock."""
    ammo_dict = {("5.56x45mm", 4): sample_556_ammo_lv4}

    results = rank_weapons(
        guns=[sample_m4a1],
        builds={},  # Empty builds
        ammo_prices=ammo_dict,
        armor_level=4,
        ammo_level=4,
        distance_m=15,
    )

    assert len(results) == 1
    entry = results[0]
    assert entry.total_loadout_cost == sample_m4a1.base_price + 60 * sample_556_ammo_lv4.price_per_round
    assert entry.attachments == []
    assert entry.tuning_instructions == []


def test_tag_generation_meaningful(sample_m4a1, sample_m4a1_build, sample_556_ammo_lv4):
    """Verify that appropriate tactical tags are assigned to weapons."""
    ammo_dict = {("5.56x45mm", 4): sample_556_ammo_lv4}
    results = rank_weapons(
        guns=[sample_m4a1],
        builds={"m4a1": sample_m4a1_build},
        ammo_prices=ammo_dict,
        armor_level=4,
        ammo_level=4,
        distance_m=15,
    )
    entry = results[0]
    assert len(entry.tags) >= 1
    for tag in entry.tags:
        assert isinstance(tag, str)
        assert len(tag) > 0


def test_rank_weapons_empty_guns():
    """Verify that empty gun list returns empty list without error."""
    assert rank_weapons([], {}, {}, 4, 4, 15) == []


def test_rank_weapons_all_nine_scenarios():
    """Verify all 9 matrix scenarios (3 armor-ammo x 3 distances) run cleanly with caliber gating."""
    with open("data/base_guns.json", "r", encoding="utf-8") as f:
        guns = [GunMeta.model_validate(x) for x in json.load(f)]
    with open("data/default_builds.json", "r", encoding="utf-8") as f:
        builds = {
            x["gun_id"]: WeaponBuild.model_validate(
                {k: v for k, v in x.items() if k in WeaponBuild.model_fields}
            )
            for x in json.load(f)
        }
    with open("data/baseline_ammo_prices.json", "r", encoding="utf-8") as f:
        ammo_list = [AmmoPrice.model_validate(x) for x in json.load(f)]
    ammo_dict = {(a.caliber, a.level): a for a in ammo_list}

    matrix = [
        (4, 4, 15), (4, 4, 35), (4, 4, 50),
        (4, 5, 15), (4, 5, 35), (4, 5, 50),
        (5, 5, 15), (5, 5, 35), (5, 5, 50),
    ]

    guns_9mm_count = len([g for g in guns if g.caliber == "9x19mm"])
    assert guns_9mm_count > 0

    for armor_lv, ammo_lv, dist in matrix:
        results = rank_weapons(
            guns=guns,
            builds=builds,
            ammo_prices=ammo_dict,
            armor_level=armor_lv,
            ammo_level=ammo_lv,
            distance_m=dist,
        )
        if ammo_lv == 4:
            # All weapons have level 4 ammo
            assert len(results) == len(guns)
        else:
            # Strict caliber gating: 9x19mm weapons lack level 5 ammo and are excluded
            assert len(results) == len(guns) - guns_9mm_count
            assert all(r.caliber != "9x19mm" for r in results)

        assert results[0].composite_score >= results[-1].composite_score
        assert all(isinstance(r, TierEntry) for r in results)


def test_resolve_ammo_formats(sample_556_ammo_lv4):
    """Test various input representations of ammo_prices."""
    from src.engine.ranker import resolve_ammo

    # Tuple key
    assert resolve_ammo({("5.56x45mm", 4): sample_556_ammo_lv4}, "5.56x45mm", 4) == sample_556_ammo_lv4
    # Compound string key _
    assert resolve_ammo({"5.56x45mm_4": sample_556_ammo_lv4}, "5.56x45mm", 4) == sample_556_ammo_lv4
    # Arbitrary dict key (searched in values)
    assert resolve_ammo({"ammo_item_01": sample_556_ammo_lv4}, "5.56x45mm", 4) == sample_556_ammo_lv4
    # Level mismatch returns None strictly (no cross-tier fallback)
    assert resolve_ammo({"5.56x45mm_4": sample_556_ammo_lv4}, "5.56x45mm", 5) is None
    # List format matching level
    assert resolve_ammo([sample_556_ammo_lv4], "5.56x45mm", 4) == sample_556_ammo_lv4
    # List format level mismatch returns None strictly
    assert resolve_ammo([sample_556_ammo_lv4], "5.56x45mm", 5) is None
    # List format missing caliber returns None
    assert resolve_ammo([sample_556_ammo_lv4], "9x19mm", 4) is None


def test_resolve_ammo_strict_and_gating():
    sample_ammo = {
        "9x19mm_4": AmmoPrice(caliber="9x19mm", level=4, name="9x19mm PBP", penetration=40, price_per_round=1545, source="test", updated_at="2026-09-18T00:00:00Z"),
        "5.56x45mm_4": AmmoPrice(caliber="5.56x45mm", level=4, name="5.56x45mm M855A1", penetration=42, price_per_round=1150, source="test", updated_at="2026-09-18T00:00:00Z"),
        "5.56x45mm_5": AmmoPrice(caliber="5.56x45mm", level=5, name="5.56x45mm M995", penetration=53, price_per_round=3100, source="test", updated_at="2026-09-18T00:00:00Z"),
    }
    # 9x19mm has level 4
    assert resolve_ammo(sample_ammo, "9x19mm", 4) is not None
    # 9x19mm has NO level 5
    assert resolve_ammo(sample_ammo, "9x19mm", 5) is None



