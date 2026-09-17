"""Unit and integration tests for pipeline orchestration and semantic change detection."""

import json
import os
import sys
import pytest
from src.pipeline import has_semantic_changes, run_pipeline, main
from src.models import TierEntry


def test_has_semantic_changes_detects_tier_switch():
    """Verify tier upgrade or downgrade triggers semantic change."""
    old = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0}]
    new = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T0", "composite_score": 88.5}]
    assert has_semantic_changes(old, new, delta_threshold=3.0) is True


def test_has_semantic_changes_ignores_tiny_fluctuations():
    """Verify minor score delta (< 3.0) without tier switch does not trigger change."""
    old = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0}]
    new = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.5}]
    assert has_semantic_changes(old, new, delta_threshold=3.0) is False


def test_has_semantic_changes_detects_score_jump():
    """Verify score change >= delta_threshold triggers change even if tier remains same."""
    old = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 80.0}]
    new = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 83.2}]
    assert has_semantic_changes(old, new, delta_threshold=3.0) is True


def test_has_semantic_changes_boundary_threshold():
    """Verify delta_threshold boundary behavior: 2.99 is ignored, 3.0 triggers change."""
    old = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 80.0}]
    sub_threshold = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 82.99}]
    at_threshold = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 83.0}]

    assert has_semantic_changes(old, sub_threshold, delta_threshold=3.0) is False
    assert has_semantic_changes(old, at_threshold, delta_threshold=3.0) is True


def test_has_semantic_changes_weapon_added_or_removed():
    """Verify weapon additions or removals trigger change."""
    base = [
        {"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0},
    ]
    added = [
        {"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0},
        {"gun_id": "vector", "scenario": "4-4-15m", "tier": "T0", "composite_score": 89.0},
    ]
    # Addition
    assert has_semantic_changes(base, added) is True
    # Removal
    assert has_semantic_changes(added, base) is True


def test_has_semantic_changes_empty_or_missing_old_data():
    """Verify empty or nonexistent old rankings return True when new data exists."""
    new_data = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0}]

    assert has_semantic_changes(None, new_data) is True
    assert has_semantic_changes([], new_data) is True
    assert has_semantic_changes({}, new_data) is True
    assert has_semantic_changes("nonexistent_file.json", new_data) is True
    assert has_semantic_changes(None, None) is False
    assert has_semantic_changes([], []) is False


def test_has_semantic_changes_from_file_path(tmp_path):
    """Verify comparing directly against a stored JSON file on disk."""
    json_path = tmp_path / "latest_rankings.json"
    data = {
        "metadata": {"total_guns": 1},
        "rankings": {
            "4-4-15m": [
                {"gun_id": "m4a1", "tier": "T1", "composite_score": 85.0}
            ]
        }
    }
    json_path.write_text(json.dumps(data), encoding="utf-8")

    # Same data -> no change
    new_same = {
        "4-4-15m": [
            {"gun_id": "m4a1", "tier": "T1", "composite_score": 86.0}  # delta 1.0 < 3.0
        ]
    }
    assert has_semantic_changes(str(json_path), new_same) is False

    # Shifted tier -> change
    new_diff = {
        "4-4-15m": [
            {"gun_id": "m4a1", "tier": "T0", "composite_score": 89.0}
        ]
    }
    assert has_semantic_changes(str(json_path), new_diff) is True


def test_has_semantic_changes_dict_and_tier_entry_support():
    """Verify support for TierEntry model objects in rankings."""
    t1 = TierEntry(
        gun_id="m4a1",
        gun_name="M4A1",
        category="突击步枪",
        distance_m=15,
        armor_level=4,
        ammo_level=4,
        stk=4,
        practical_ttk_ms=275.5,
        ammo_60_cost=30000,
        total_loadout_cost=110000,
        single_kill_cost=2000,
        combat_score=85.0,
        handling_score=80.0,
        cost_score=80.0,
        composite_score=82.5,
        tier="T1",
        build_code="CODE1",
        tags=["标签"],
    )
    t2 = t1.model_copy(update={"composite_score": 83.0})  # diff 0.5
    t3 = t1.model_copy(update={"composite_score": 88.0, "tier": "T0"})

    assert has_semantic_changes({"4-4-15m": [t1]}, {"4-4-15m": [t2]}) is False
    assert has_semantic_changes({"4-4-15m": [t1]}, {"4-4-15m": [t3]}) is True


def test_has_semantic_changes_list_with_armor_ammo_dist_fields():
    """Verify list format extracting scenario from armor/ammo/distance fields."""
    old = [
        {"gun_id": "m4a1", "armor_level": 4, "ammo_level": 4, "distance_m": 15, "tier": "T1", "composite_score": 85.0}
    ]
    new = [
        {"gun_id": "m4a1", "armor_level": 4, "ammo_level": 4, "distance_m": 15, "tier": "T0", "composite_score": 88.5}
    ]
    assert has_semantic_changes(old, new) is True


def test_has_semantic_changes_old_exists_new_empty():
    """Verify old data exists but new rankings are empty triggers change."""
    old = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0}]
    assert has_semantic_changes(old, []) is True


def test_has_semantic_changes_corrupted_json_file(tmp_path):
    """Verify corrupted JSON file is treated as empty."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not_valid_json...", encoding="utf-8")
    new_data = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0}]
    assert has_semantic_changes(str(bad_file), new_data) is True


def test_has_semantic_changes_unhandled_type():
    """Verify unexpected data types return False when comparing with empty."""
    assert has_semantic_changes(12345, 12345) is False


def test_run_pipeline_first_run_creates_files(tmp_path):
    """Verify first pipeline run creates README, scenario docs, and JSON."""
    result = run_pipeline(force=False, live=False, output_dir=str(tmp_path))

    assert result["has_changes"] is True
    assert result["updated"] is True
    assert result["total_scenarios"] == 9
    assert result["total_guns"] >= 10
    assert len(result["files_written"]) == 5

    # Check that all expected files were actually created
    readme_path = tmp_path / "README.md"
    assert readme_path.exists()
    assert "三角洲行动" in readme_path.read_text(encoding="utf-8")

    json_path = tmp_path / "data" / "latest_rankings.json"
    assert json_path.exists()
    rankings_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert "rankings" in rankings_json
    assert len(rankings_json["rankings"]) == 9

    doc1 = tmp_path / "docs" / "tierlist" / "4armor_4ammo.md"
    doc2 = tmp_path / "docs" / "tierlist" / "4armor_5ammo.md"
    doc3 = tmp_path / "docs" / "tierlist" / "5armor_5ammo.md"
    assert doc1.exists()
    assert doc2.exists()
    assert doc3.exists()


def test_run_pipeline_no_changes_skips_writing(tmp_path):
    """Verify second run without semantic changes skips updating files."""
    # First run creates files
    run_pipeline(force=False, live=False, output_dir=str(tmp_path))

    readme_path = tmp_path / "README.md"
    mtime_before = readme_path.stat().st_mtime_ns

    # Second run without force
    result2 = run_pipeline(force=False, live=False, output_dir=str(tmp_path))

    assert result2["has_changes"] is False
    assert result2["updated"] is False
    assert len(result2["files_written"]) == 0

    mtime_after = readme_path.stat().st_mtime_ns
    assert mtime_before == mtime_after


def test_run_pipeline_force_flag_forces_update(tmp_path):
    """Verify --force overrides semantic check and rewrites files."""
    # First run
    run_pipeline(force=False, live=False, output_dir=str(tmp_path))

    # Second run with force=True
    result = run_pipeline(force=True, live=False, output_dir=str(tmp_path))

    assert result["has_changes"] is False
    assert result["updated"] is True
    assert len(result["files_written"]) == 5


def test_run_pipeline_github_env_output(tmp_path, monkeypatch):
    """Verify GITHUB_ENV receives HAS_SEMANTIC_CHANGES=true/false."""
    env_file = tmp_path / "github_env.txt"
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    # Run 1: First run with new data -> HAS_SEMANTIC_CHANGES=true
    run_pipeline(force=False, live=False, output_dir=str(tmp_path))
    content1 = env_file.read_text(encoding="utf-8")
    assert "HAS_SEMANTIC_CHANGES=true" in content1

    # Clear env file
    env_file.write_text("", encoding="utf-8")

    # Run 2: Second run without changes -> HAS_SEMANTIC_CHANGES=false
    run_pipeline(force=False, live=False, output_dir=str(tmp_path))
    content2 = env_file.read_text(encoding="utf-8")
    assert "HAS_SEMANTIC_CHANGES=false" in content2


def test_run_pipeline_custom_paths(tmp_path):
    """Verify run_pipeline with custom baseline and guns paths."""
    res = run_pipeline(
        force=True,
        live=False,
        output_dir=str(tmp_path),
        guns_path="data/base_guns.json",
        builds_path="data/default_builds.json",
        snapshot_path=str(tmp_path / "non_existent_snapshot.json"),
        baseline_path="data/baseline_ammo_prices.json",
    )
    assert res["updated"] is True
    assert res["status"].source == "baseline"


def test_cli_main_execution(tmp_path, monkeypatch, capsys):
    """Verify CLI entrypoint with argparse arguments."""
    test_args = [
        "pipeline",
        "--offline",
        "--output-dir",
        str(tmp_path),
        "--force",
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    main()

    captured = capsys.readouterr()
    assert "Pipeline finished" in captured.out
    assert (tmp_path / "README.md").exists()
