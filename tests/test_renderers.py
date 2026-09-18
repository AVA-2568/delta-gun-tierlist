"""Unit and integration tests for Markdown and JSON report renderers."""

import json
import os
import pytest
from src.models import (
    DataSourceStatus,
    GunMeta,
    TierEntry,
    WeaponBuild,
    AmmoPrice,
)
from src.engine.ranker import rank_weapons
from src.renderers.markdown_renderer import render_main_readme, render_scenario_docs
from src.renderers.json_exporter import export_rankings_json


@pytest.fixture
def sample_status() -> DataSourceStatus:
    return DataSourceStatus(
        source="zxfps_live",
        is_fallback=False,
        fallback_tier=0,
        updated_at="2026-09-17 12:00:00",
        message="在线数据源连接正常",
    )


@pytest.fixture
def sample_fallback_status() -> DataSourceStatus:
    return DataSourceStatus(
        source="baseline",
        is_fallback=True,
        fallback_tier=2,
        updated_at="2026-09-17 00:00:00",
        message="网络连接超时，已降级为固化基准价格",
    )


@pytest.fixture
def sample_ranking_results() -> dict:
    """Create a mock 9-dimension ranking dataset for tests."""
    scenarios = [
        ("4-4-15m", 4, 4, 15),
        ("4-4-35m", 4, 4, 35),
        ("4-4-50m", 4, 4, 50),
        ("4-5-15m", 4, 5, 15),
        ("4-5-35m", 4, 5, 35),
        ("4-5-50m", 4, 5, 50),
        ("5-5-15m", 5, 5, 15),
        ("5-5-35m", 5, 5, 35),
        ("5-5-50m", 5, 5, 50),
    ]

    all_rankings = {}
    for sc_name, armor, ammo, dist in scenarios:
        m4 = TierEntry(
            gun_id="m4a1",
            gun_name="M4A1",
            category="突击步枪",
            caliber="5.56x45mm",
            distance_m=dist,
            armor_level=armor,
            ammo_level=ammo,
            stk=4 if ammo >= armor else 5,
            practical_ttk_ms=275.5,
            ammo_60_cost=30000 if ammo == 4 else 60000,
            total_loadout_cost=110000 if ammo == 4 else 140000,
            single_kill_cost=2000,
            combat_score=90.0 if (armor == 4 and ammo == 4) else 85.0,
            handling_score=80.0,
            cost_score=85.0,
            composite_score=88.5 if (armor == 4 and ammo == 4) else 83.5,
            tier="T0" if (armor == 4 and ammo == 4) else "T1",
            attachments=["长枪管", "实用垂直握把"],
            tuning_instructions=["枪托: 配重右拉满(+50g)", "前握把: 安装位置前拉满"],
            tags=["版本答案", "平民首选"],
        )
        vec = TierEntry(
            gun_id="vector",
            gun_name="Vector",
            category="冲锋枪",
            caliber="9x19mm",
            distance_m=dist,
            armor_level=armor,
            ammo_level=ammo,
            stk=5 if ammo >= armor else 6,
            practical_ttk_ms=230.0 if dist == 15 else 450.0,
            ammo_60_cost=24000 if ammo == 4 else 48000,
            total_loadout_cost=95000 if ammo == 4 else 119000,
            single_kill_cost=1800,
            combat_score=92.0 if dist == 15 else 60.0,
            handling_score=88.0,
            cost_score=90.0,
            composite_score=89.5 if dist == 15 else 68.0,
            tier="T0" if dist == 15 else "T2",
            attachments=["冲锋枪消音器", "实用垂直握把"],
            tuning_instructions=["后握把: 角度后拉满"],
            tags=["近战撕裂", "高容错"],
        )
        all_rankings[sc_name] = [m4, vec]

    return all_rankings


def test_markdown_rendering_structure(sample_ranking_results, sample_status, tmp_path):
    """Verify basic README.md generation and mandatory keywords from brief."""
    readme_path = tmp_path / "README.md"
    rendered = render_main_readme(sample_ranking_results, sample_status, output_path=str(readme_path))
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "三角洲行动" in content
    assert "T0" in content
    assert "60发备弹" in content
    assert rendered == content


def test_json_export(sample_ranking_results, sample_status, tmp_path):
    """Verify latest_rankings.json structure from brief."""
    json_path = tmp_path / "latest_rankings.json"
    result_path = export_rankings_json(sample_ranking_results, sample_status, output_path=str(json_path))
    assert json_path.exists()
    assert result_path == str(json_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "metadata" in data
    assert "rankings" in data
    assert data["metadata"]["status"]["source"] == "zxfps_live"
    assert "4-4-15m" in data["rankings"]
    first_entry = data["rankings"]["4-4-15m"][0]
    assert "tuning_instructions" in first_entry
    assert isinstance(first_entry["tuning_instructions"], list)
    assert "build_code" not in first_entry
    assert "code_status" not in first_entry


def test_render_main_readme_badges(sample_ranking_results, sample_status, sample_fallback_status, tmp_path):
    """Verify status badges for both online and fallback states."""
    # Test online badge
    online_path = tmp_path / "README_online.md"
    render_main_readme(sample_ranking_results, sample_status, output_path=str(online_path))
    online_content = online_path.read_text(encoding="utf-8")
    assert "Live" in online_content or "实时" in online_content
    assert "2026-09-17" in online_content
    assert "2把" in online_content or "2" in online_content

    # Test fallback badge and warning note
    fallback_path = tmp_path / "README_fallback.md"
    render_main_readme(sample_ranking_results, sample_fallback_status, output_path=str(fallback_path))
    fallback_content = fallback_path.read_text(encoding="utf-8")
    assert "Baseline" in fallback_content or "基准" in fallback_content
    assert "降级为固化基准价格" in fallback_content


def test_render_main_readme_t0_quick_lookup_cards(sample_ranking_results, sample_status, tmp_path):
    """Verify T0 quick lookup cards for the 3 major battle scenarios with tuning notes and no build codes."""
    readme_path = tmp_path / "README.md"
    render_main_readme(sample_ranking_results, sample_status, output_path=str(readme_path))
    content = readme_path.read_text(encoding="utf-8")

    # Check 3 major scenarios headers
    assert "4套4弹" in content
    assert "4套5弹" in content
    assert "5套5弹" in content

    # Check T0 weapon card elements: attachments list, tuning instructions, total cost, 60 ammo cost
    assert "🛠️ 最优高性价比实战改装配件清单" in content
    assert "🎯 实战精校调校要点" in content
    assert "配重右拉满" in content
    assert "110,000" in content or "110000" in content
    assert "30,000" in content or "30000" in content
    assert "改枪码" not in content
    assert "方案码" not in content


def test_render_main_readme_nine_dimension_matrix(sample_ranking_results, sample_status, tmp_path):
    """Verify 9-dimension overview matrix table headers and content."""
    readme_path = tmp_path / "README.md"
    render_main_readme(sample_ranking_results, sample_status, output_path=str(readme_path))
    content = readme_path.read_text(encoding="utf-8")

    # Table contains weapon names and tuning instructions
    assert "M4A1" in content
    assert "Vector" in content
    assert "最优高性价比改装配件与精校要点" in content
    assert "配重右拉满" in content
    assert "改枪码" not in content


def test_render_main_readme_formulas_and_links(sample_ranking_results, sample_status, tmp_path):
    """Verify documentation links and methodology formulas."""
    readme_path = tmp_path / "README.md"
    render_main_readme(sample_ranking_results, sample_status, output_path=str(readme_path))
    content = readme_path.read_text(encoding="utf-8")

    # Sub-scenario doc links
    assert "4armor_4ammo.md" in content
    assert "4armor_5ammo.md" in content
    assert "5armor_5ammo.md" in content

    # Formulas and methodology explanations
    assert "Practical TTK" in content or "实战TTK" in content or "实战击杀时间" in content
    assert "50%" in content
    assert "20%" in content
    assert "30%" in content


def test_render_scenario_docs(sample_ranking_results, sample_status, tmp_path):
    """Verify scenario documentation generator creates 3 sub-docs with 14-column tables."""
    docs_dir = tmp_path / "tierlist"
    created_files = render_scenario_docs(sample_ranking_results, sample_status, docs_dir=str(docs_dir))

    assert len(created_files) == 3
    for fpath in created_files:
        assert os.path.exists(fpath)

    expected_files = ["4armor_4ammo.md", "4armor_5ammo.md", "5armor_5ammo.md"]
    for fname in expected_files:
        target_path = docs_dir / fname
        assert target_path.exists()
        content = target_path.read_text(encoding="utf-8")

        # 3 distance sections
        assert "15m" in content
        assert "35m" in content
        assert "50m" in content

        # Headers or data fields
        assert "排名" in content
        assert "梯队" in content
        assert "枪械" in content
        assert "口径" in content
        assert "STK" in content
        assert "实战TTK" in content
        assert "60发备弹成本" in content
        assert "起枪总成本" in content
        assert "单杀弹药成本" in content
        assert "综合评分" in content
        assert "实战推荐改装配件清单" in content
        assert "实战精校调校" in content
        assert "战术标签" in content

        # Check values
        assert "M4A1" in content
        assert "配重右拉满" in content
        assert "改枪码" not in content


def test_no_build_code_in_generated_markdown(sample_ranking_results, sample_status, tmp_path):
    """Verify that no build_code or 改枪码 appears in README or scenario docs."""
    readme_path = tmp_path / "README.md"
    render_main_readme(sample_ranking_results, sample_status, output_path=str(readme_path))
    readme_content = readme_path.read_text(encoding="utf-8")
    assert "改枪码" not in readme_content
    assert "build_code" not in readme_content
    assert "方案码" not in readme_content

    docs_dir = tmp_path / "tierlist_nocode"
    created_files = render_scenario_docs(sample_ranking_results, sample_status, docs_dir=str(docs_dir))
    for fpath in created_files:
        content = open(fpath, "r", encoding="utf-8").read()
        assert "改枪码" not in content
        assert "build_code" not in content
        assert "方案码" not in content


def test_renderers_auto_create_directories(sample_ranking_results, sample_status, tmp_path):
    """Verify parent directories are created automatically if nonexistent."""
    deep_readme = tmp_path / "deep" / "nested" / "README.md"
    render_main_readme(sample_ranking_results, sample_status, output_path=str(deep_readme))
    assert deep_readme.exists()

    deep_json = tmp_path / "nested" / "data" / "rankings.json"
    export_rankings_json(sample_ranking_results, sample_status, output_path=str(deep_json))
    assert deep_json.exists()

    deep_docs = tmp_path / "sub" / "docs" / "tierlist"
    created_docs = render_scenario_docs(sample_ranking_results, sample_status, docs_dir=str(deep_docs))
    assert len(created_docs) == 3
    for doc in created_docs:
        assert os.path.exists(doc)


def test_full_pipeline_rendering_with_real_data(tmp_path):
    """Integration test using actual data files to generate and render rankings."""
    with open("data/base_guns.json", "r", encoding="utf-8") as f:
        guns = [GunMeta.model_validate(x) for x in json.load(f)]
    with open("data/default_builds.json", "r", encoding="utf-8") as f:
        builds = {x["gun_id"]: WeaponBuild.model_validate(x) for x in json.load(f)}
    with open("data/baseline_ammo_prices.json", "r", encoding="utf-8") as f:
        ammo_list = [AmmoPrice.model_validate(x) for x in json.load(f)]
    ammo_dict = {(a.caliber, a.level): a for a in ammo_list}

    matrix = [
        (4, 4, 15), (4, 4, 35), (4, 4, 50),
        (4, 5, 15), (4, 5, 35), (4, 5, 50),
        (5, 5, 15), (5, 5, 35), (5, 5, 50),
    ]
    all_rankings = {}
    for armor_lv, ammo_lv, dist in matrix:
        key = f"{armor_lv}-{ammo_lv}-{dist}m"
        all_rankings[key] = rank_weapons(guns, builds, ammo_dict, armor_lv, ammo_lv, dist)

    status = DataSourceStatus(
        source="snapshot",
        is_fallback=True,
        fallback_tier=1,
        updated_at="2026-09-17 12:30:00",
        message="使用快照数据生成完整天梯",
    )

    readme_file = tmp_path / "README.md"
    render_main_readme(all_rankings, status, output_path=str(readme_file))
    assert readme_file.exists()

    docs_dir = tmp_path / "docs" / "tierlist"
    scenario_files = render_scenario_docs(all_rankings, status, docs_dir=str(docs_dir))
    assert len(scenario_files) == 3

    json_file = tmp_path / "data" / "latest_rankings.json"
    export_rankings_json(all_rankings, status, output_path=str(json_file))
    assert json_file.exists()

    json_data = json.loads(json_file.read_text(encoding="utf-8"))
    assert json_data["metadata"]["total_scenarios"] == 9
    assert json_data["metadata"]["total_guns"] == len(guns)


def test_scenario_lookup_fallback_arbitrary_keys(sample_ranking_results, sample_status, tmp_path):
    """Verify scenario resolver finds entries even when keys are non-standard."""
    arbitrary_keyed_rankings = {
        f"scenario_hash_{i}": entries
        for i, (k, entries) in enumerate(sample_ranking_results.items())
    }
    readme_path = tmp_path / "README_hash.md"
    content = render_main_readme(arbitrary_keyed_rankings, sample_status, output_path=str(readme_path))
    assert "M4A1" in content

    docs_dir = tmp_path / "docs_hash"
    docs = render_scenario_docs(arbitrary_keyed_rankings, sample_status, docs_dir=str(docs_dir))
    assert len(docs) == 3


def test_empty_scenario_docs(sample_status, tmp_path):
    """Verify empty scenario generates clean document with fallback empty row."""
    empty_rankings = {}
    docs_dir = tmp_path / "empty_docs"
    docs = render_scenario_docs(empty_rankings, sample_status, docs_dir=str(docs_dir))
    assert len(docs) == 3
    for d in docs:
        content = open(d, "r", encoding="utf-8").read()
        assert "暂无数据" in content


def test_json_export_dict_based_entries(sample_status, tmp_path):
    """Verify export_rankings_json works when entries are raw dicts instead of pydantic models."""
    dict_rankings = {
        "4-4-15m": [
            {
                "gun_id": "m4a1",
                "gun_name": "M4A1",
                "tier": "T0",
                "composite_score": 90.0,
            }
        ]
    }
    json_path = tmp_path / "dict_rankings.json"
    export_rankings_json(dict_rankings, sample_status, output_path=str(json_path))
    assert json_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["metadata"]["total_guns"] == 1
    assert loaded["rankings"]["4-4-15m"][0]["gun_id"] == "m4a1"

