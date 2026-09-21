"""距离带聚合（band_summary）测试。"""

import pytest

from src.engine.engagement import TtkResult, band_summary


def _result(distance_m: float, ttk_ms: float, expected_shots: float) -> TtkResult:
    return TtkResult(
        distance_m=distance_m,
        ttk_seconds=ttk_ms / 1000.0,
        expected_shots=expected_shots,
        ads_seconds=0.0,
        flight_seconds=0.0,
        fire_interval_seconds=0.05,
        rpm=1200.0,
        falloff=1.0,
        effective_range_m=40.0,
        muzzle_velocity_mps=500.0,
    )


def test_mean_expected_shots_is_arithmetic_mean():
    # 贴脸带（0–15m）含 0/5/10 三个点
    curve = [
        _result(0.0, 200.0, 5.0),
        _result(5.0, 200.0, 5.0),
        _result(10.0, 250.0, 6.0),
        _result(20.0, 300.0, 7.0),
    ]
    bands = band_summary(curve)
    assert bands["贴脸"]["mean_expected_shots"] == pytest.approx(16.0 / 3.0)
    assert bands["近距"]["mean_expected_shots"] == pytest.approx(7.0)


def test_mean_expected_shots_is_not_rounded():
    """供成本计算消费，必须保留精度（若被 round 到 2 位会引入成本误差）。"""
    curve = [_result(0.0, 100.0, 5.5431), _result(1.0, 100.0, 6.1001)]
    bands = band_summary(curve)
    expected = (5.5431 + 6.1001) / 2.0
    assert bands["贴脸"]["mean_expected_shots"] == pytest.approx(expected, abs=1e-12)


def test_existing_fields_unchanged():
    curve = [_result(0.0, 200.0, 5.0), _result(10.0, 300.0, 6.0)]
    bands = band_summary(curve)
    assert set(bands["贴脸"]) == {"min_ms", "max_ms", "mean_ms", "mean_expected_shots"}
    assert bands["贴脸"]["min_ms"] == pytest.approx(200.0)
    assert bands["贴脸"]["max_ms"] == pytest.approx(300.0)
    assert bands["贴脸"]["mean_ms"] == pytest.approx(250.0)


def test_empty_band_is_skipped():
    assert band_summary([_result(60.0, 200.0, 5.0)]).get("贴脸") is None
