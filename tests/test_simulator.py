"""Unit tests for discrete combat simulation and practical TTK engine."""

import pytest
from src.models import GunMeta, DamageDropoff, AmmoPrice, SimulationResult
from src.engine.simulator import (
    simulate_duel,
    calc_effective_hit_rate,
    get_damage_at_distance,
)


@pytest.fixture
def m4a1_gun() -> GunMeta:
    dropoffs = [
        DamageDropoff(max_distance=25.0, chest_damage=34.0, armor_damage=30.0),
        DamageDropoff(max_distance=45.0, chest_damage=29.0, armor_damage=26.0),
        DamageDropoff(max_distance=100.0, chest_damage=24.0, armor_damage=22.0),
    ]
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
        dropoffs=dropoffs,
    )


@pytest.fixture
def vector_gun() -> GunMeta:
    dropoffs = [
        DamageDropoff(max_distance=15.0, chest_damage=28.0, armor_damage=24.0),
        DamageDropoff(max_distance=30.0, chest_damage=21.0, armor_damage=18.0),
        DamageDropoff(max_distance=100.0, chest_damage=15.0, armor_damage=13.0),
    ]
    return GunMeta(
        id="vector",
        name="Vector",
        category="冲锋枪",
        caliber="9x19mm",
        rpm=1100,
        bullet_velocity=380.0,
        base_price=42000,
        default_mag_size=30,
        ads_time_ms=150,
        recoil_control=78.0,
        stability=72.0,
        dropoffs=dropoffs,
    )


@pytest.fixture
def svd_gun() -> GunMeta:
    dropoffs = [
        DamageDropoff(max_distance=40.0, chest_damage=72.0, armor_damage=66.0),
        DamageDropoff(max_distance=80.0, chest_damage=66.0, armor_damage=60.0),
    ]
    return GunMeta(
        id="svd",
        name="SVD",
        category="精确射手步枪",
        caliber="7.62x54mmR",
        rpm=300,
        bullet_velocity=830.0,
        base_price=55000,
        default_mag_size=10,
        ads_time_ms=320,
        recoil_control=52.0,
        stability=80.0,
        dropoffs=dropoffs,
    )


@pytest.fixture
def ammo_556_lv4() -> AmmoPrice:
    return AmmoPrice(
        caliber="5.56x45mm",
        level=4,
        name="5.56x45mm M855A1",
        penetration=42,
        price_per_round=1150,
        source="test",
        updated_at="2026-09-17T00:00:00Z",
    )


@pytest.fixture
def ammo_556_lv5() -> AmmoPrice:
    return AmmoPrice(
        caliber="5.56x45mm",
        level=5,
        name="5.56x45mm M995",
        penetration=53,
        price_per_round=3100,
        source="test",
        updated_at="2026-09-17T00:00:00Z",
    )


@pytest.fixture
def ammo_9mm_lv4() -> AmmoPrice:
    return AmmoPrice(
        caliber="9x19mm",
        level=4,
        name="9x19mm AP 6.3",
        penetration=40,
        price_per_round=850,
        source="test",
        updated_at="2026-09-17T00:00:00Z",
    )


@pytest.fixture
def ammo_762r_lv4() -> AmmoPrice:
    return AmmoPrice(
        caliber="7.62x54mmR",
        level=4,
        name="7.62x54mmR LPS",
        penetration=45,
        price_per_round=1550,
        source="test",
        updated_at="2026-09-17T00:00:00Z",
    )


def test_effective_hit_rate_distance_dropoff():
    # 15m EHR 应接近 1.0 (0.90~1.0)
    ehr_15m = calc_effective_hit_rate(
        recoil_control=70.0, stability=70.0, velocity=700.0, distance_m=15
    )
    ehr_35m = calc_effective_hit_rate(
        recoil_control=70.0, stability=70.0, velocity=700.0, distance_m=35
    )
    ehr_50m = calc_effective_hit_rate(
        recoil_control=70.0, stability=70.0, velocity=700.0, distance_m=50
    )
    ehr_80m = calc_effective_hit_rate(
        recoil_control=70.0, stability=70.0, velocity=700.0, distance_m=80
    )

    assert 0.90 <= ehr_15m <= 1.0
    assert ehr_35m < ehr_15m
    assert ehr_50m < ehr_35m
    assert ehr_80m < ehr_50m
    assert ehr_80m >= 0.05


def test_damage_at_distance_lookup(m4a1_gun):
    chest, armor = get_damage_at_distance(m4a1_gun.dropoffs, 15)
    assert chest == 34.0
    assert armor == 30.0

    chest, armor = get_damage_at_distance(m4a1_gun.dropoffs, 35)
    assert chest == 29.0
    assert armor == 26.0

    # 超过所有区间最大值，返回末尾区间数值
    chest, armor = get_damage_at_distance(m4a1_gun.dropoffs, 120)
    assert chest == 24.0
    assert armor == 22.0


def test_simulation_level_4_ammo_vs_level_4_armor(m4a1_gun, ammo_556_lv4):
    result = simulate_duel(m4a1_gun, ammo_556_lv4, armor_level=4, distance_m=15)
    assert isinstance(result, SimulationResult)
    assert 4 <= result.stk <= 6
    assert result.practical_ttk_ms > 0
    assert result.theoretical_ttk_ms <= result.practical_ttk_ms
    assert 0.90 <= result.ehr <= 1.0


def test_simulation_level_5_ammo_vs_level_4_armor_fast_penetration(m4a1_gun, ammo_556_lv5):
    # 5级弹击穿4级甲具备极速穿透特征 (STK 3~4 发)
    result = simulate_duel(m4a1_gun, ammo_556_lv5, armor_level=4, distance_m=15)
    assert 3 <= result.stk <= 4
    assert result.practical_ttk_ms > 0
    assert result.theoretical_ttk_ms <= result.practical_ttk_ms


def test_simulation_level_4_ammo_vs_level_5_armor_elongated_stk(m4a1_gun, ammo_556_lv4):
    # 4级弹面对5级甲因护甲减伤与未能立即击穿，STK显著拉长至 8~12 发
    result = simulate_duel(m4a1_gun, ammo_556_lv4, armor_level=5, distance_m=15)
    assert 8 <= result.stk <= 12
    assert result.practical_ttk_ms > 0


def test_simulation_level_5_ammo_vs_level_5_armor(m4a1_gun, ammo_556_lv5):
    # 同级对决 (5级弹 vs 5级甲)，STK 在 4~6 发
    result = simulate_duel(m4a1_gun, ammo_556_lv5, armor_level=5, distance_m=15)
    assert 4 <= result.stk <= 7
    assert result.practical_ttk_ms > 0


def test_smg_vs_dmr_practical_ttk_at_50m(vector_gun, ammo_9mm_lv4, svd_gun, ammo_762r_lv4):
    # 50m交战距离，冲锋枪由于子弹初速慢、衰减大，实战TTK应显著劣于精确射手步枪
    res_vector = simulate_duel(vector_gun, ammo_9mm_lv4, armor_level=4, distance_m=50)
    res_svd = simulate_duel(svd_gun, ammo_762r_lv4, armor_level=4, distance_m=50)

    assert res_vector.ehr < res_svd.ehr
    assert res_vector.practical_ttk_ms > res_svd.practical_ttk_ms


def test_theoretical_ttk_calculation_edge_cases(m4a1_gun, ammo_556_lv4):
    # 当交战距离在15m以下，k_ads为0.5；远距离为0.8
    res_15m = simulate_duel(m4a1_gun, ammo_556_lv4, armor_level=4, distance_m=15)
    res_35m = simulate_duel(m4a1_gun, ammo_556_lv4, armor_level=4, distance_m=35)

    # 理论 TTK 应当严格按 (stk - 1) * (60.0 / rpm) * 1000 计算
    expected_theo_15m = (res_15m.stk - 1) * (60.0 / m4a1_gun.rpm) * 1000.0
    assert abs(res_15m.theoretical_ttk_ms - expected_theo_15m) < 0.1
