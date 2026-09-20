"""管线端到端测试（小规模、不写盘）。"""

import os

import pytest

from src.pipeline import DEFAULT_SCENARIO, run_pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def result():
    return run_pipeline(
        output_dir=ROOT,
        scenario_id=DEFAULT_SCENARIO,
        limit=2,
        beam_width=2,
        top_k=1,
        write=False,
    )


def test_pipeline_returns_payload_for_requested_scenario(result):
    assert result["scenarios"] == [DEFAULT_SCENARIO]
    assert DEFAULT_SCENARIO in result["payloads"]
    assert result["weapon_count"] == 2
    # write=False 时不应产出文件
    assert result["files_written"] == []


def test_pipeline_payload_is_self_contained(result):
    payload = result["payloads"][DEFAULT_SCENARIO]
    assert payload["scenario_id"] == DEFAULT_SCENARIO
    assert payload["eligible_weapon_count"] == len(payload["weapons"]) + payload["folded_variant_count"]
    assert payload["weapon_pool_count"] == payload["eligible_weapon_count"] + payload["excluded_weapon_count"]
    assert payload["weapon_pool_count"] == result["weapon_count"]  # 与本次处理的池一致
    assert set(payload["band_definitions"]) == {"贴脸", "近距", "中距", "远距"}
    for weapon in payload["weapons"]:
        assert weapon["profile_key"]
        assert weapon["overall_mean_ms"] > 0
        for band, data in weapon["bands"].items():
            assert band in payload["band_definitions"]
            assert data["rank"] >= 1
            assert data["tier"] in {"T0", "T1", "T2", "T3"}
            assert data["mean_ms"] > 0
            assert data["worst_ms"] >= data["mean_ms"] - 1e-9


def test_unknown_scenario_raises():
    with pytest.raises(KeyError):
        run_pipeline(output_dir=ROOT, scenario_id="no-such-scenario", limit=1, write=False)
