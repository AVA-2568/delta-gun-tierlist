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
    assert {"min_ms", "max_ms", "mean_ms", "mean_expected_shots"} <= set(bands["贴脸"])
    assert bands["贴脸"]["min_ms"] == pytest.approx(200.0)
    assert bands["贴脸"]["max_ms"] == pytest.approx(300.0)
    assert bands["贴脸"]["mean_ms"] == pytest.approx(250.0)


def test_empty_band_is_skipped():
    assert band_summary([_result(60.0, 200.0, 5.0)]).get("贴脸") is None


def test_band_endpoints_belong_to_single_band():
    """带互斥：端点 15/30/50 m 只归属一个带（首带含 0 m），与衰减段同口径。"""
    curve = [_result(float(d), 100.0 + d, 1.0) for d in (0, 15, 16, 30, 31, 50, 51, 80)]
    bands = band_summary(curve)
    assert bands["贴脸"]["min_ms"] == pytest.approx(100.0)  # 0 m 归贴脸
    assert bands["贴脸"]["max_ms"] == pytest.approx(115.0)  # 15 m 归贴脸
    assert bands["近距"]["min_ms"] == pytest.approx(116.0)  # 15 m 不在近距
    assert bands["近距"]["max_ms"] == pytest.approx(130.0)  # 30 m 归近距
    assert bands["中距"]["min_ms"] == pytest.approx(131.0)  # 30 m 不在中距
    assert bands["中距"]["max_ms"] == pytest.approx(150.0)  # 50 m 归中距
    assert bands["远距"]["min_ms"] == pytest.approx(151.0)  # 50 m 不在远距
    assert bands["远距"]["max_ms"] == pytest.approx(180.0)  # 80 m 归远距
