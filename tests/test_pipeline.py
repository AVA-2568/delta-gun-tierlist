"""管线端到端测试（小规模、不写盘）。"""

import os

import pytest

from src.pipeline import DEFAULT_SCENARIOS, MAIN_SCENARIO, run_pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def result():
    return run_pipeline(
        output_dir=ROOT,
        scenarios=DEFAULT_SCENARIOS[:1],
        limit=2,
        beam_width=2,
        top_k=1,
        write=False,
    )


def test_default_scenarios_match_confirmed_scope():
    """默认榜单口径：不含 3 级弹组合，只用实战命中分布 default。"""
    assert len(DEFAULT_SCENARIOS) == 5
    for sid in DEFAULT_SCENARIOS:
        assert sid.endswith("-default")
        level = int(sid.split("-")[1])
        assert level >= 4, f"{sid} 不应包含 3 级甲弹组合"
    assert MAIN_SCENARIO in DEFAULT_SCENARIOS


def test_pipeline_returns_payload_for_requested_scenario(result):
    assert result["scenarios"] == [DEFAULT_SCENARIOS[0]]
    assert DEFAULT_SCENARIOS[0] in result["payloads"]
    assert result["weapon_count"] == 2
    # write=False 时不应产出文件
    assert result["files_written"] == []


def test_pipeline_payload_is_self_contained(result):
    payload = result["payloads"][DEFAULT_SCENARIOS[0]]
    assert payload["scenario_id"] == DEFAULT_SCENARIOS[0]
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
        run_pipeline(output_dir=ROOT, scenarios=["no-such-scenario"], limit=1, write=False)


def test_pipeline_payload_includes_ammo_price_meta(result):
    payload = result["payloads"][DEFAULT_SCENARIOS[0]]
    assert "ammo_price_meta" in payload
    assert set(payload["ammo_price_meta"]) == {"currency", "window", "updated_at", "available"}
    for weapon in payload["weapons"]:
        assert "ammo" in weapon
        assert set(weapon["ammo"]) == {"ammo_item_id", "name", "caliber", "price_avg_30d"}
        for band, data in weapon["bands"].items():
            assert "mean_expected_shots" in data
            assert "kill_cost" in data


def test_pipeline_injects_price_table(result):
    """守护本任务的核心改动：管线必须真的加载并透传了价格表。

    没有这条断言时，即使 `run_pipeline` 完全不加载 `price_table` 也能通过
    ——因为 payload 里的价格字段由 `to_export` 无条件输出。
    """
    assert "ammo_price_table" in result
    assert result["ammo_price_table"].currency == "哈夫币"


def test_pipeline_combat_fields_present_and_sane(result):
    """战斗字段齐备且自洽。

    本测试**不**声称「零漂移」——那由重新生成后的 diff 核验；
    这里只保证字段存在且内部自洽，故按实际能力命名。
    """
    payload = result["payloads"][DEFAULT_SCENARIOS[0]]
    for weapon in payload["weapons"]:
        assert weapon["overall_mean_ms"] > 0
        for data in weapon["bands"].values():
            assert data["mean_ms"] > 0
            assert data["worst_ms"] >= data["mean_ms"] - 1e-9
