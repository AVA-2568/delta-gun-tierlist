"""Unified pipeline orchestrator and semantic change detection engine for tuning loadouts."""

import argparse
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from src.collectors.ammo_collector import fetch_ammo_prices
from src.collectors.build_collector import fetch_weapon_builds
from src.collectors.gun_loader import load_all_guns
from src.engine.ranker import rank_weapons
from src.models import DataSourceStatus, TierEntry
from src.renderers.json_exporter import export_rankings_json
from src.renderers.markdown_renderer import render_main_readme, render_scenario_docs

logger = logging.getLogger(__name__)

SCENARIO_CONFIGS = [
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


def _get_field_value(obj: Any, field_name: str, default: Any = None) -> Any:
    """Safely extract field value from a dict or object."""
    if isinstance(obj, dict):
        return obj.get(field_name, default)
    return getattr(obj, field_name, default)


def _extract_rankings_map(data: Any) -> Dict[Tuple[str, str], Tuple[str, float]]:
    """Normalize arbitrary ranking datasets into a standardized mapping.

    Format:
        {(gun_id, scenario_key): (tier, composite_score)}
    """
    if data is None:
        return {}

    # Support disk file paths
    if isinstance(data, (str, os.PathLike)):
        filepath = str(data)
        if not os.path.isfile(filepath):
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("Failed to parse JSON file at '%s': %s", filepath, exc)
            return {}

    result_map: Dict[Tuple[str, str], Tuple[str, float]] = {}

    # Support dictionary inputs
    if isinstance(data, dict):
        target = (
            data.get("rankings", data)
            if ("rankings" in data and isinstance(data["rankings"], dict))
            else data
        )
        for sc_key, entries in target.items():
            if not isinstance(entries, (list, tuple)):
                continue
            for item in entries:
                gid = _get_field_value(item, "gun_id")
                tier = _get_field_value(item, "tier")
                score = _get_field_value(item, "composite_score")
                if gid is not None and tier is not None and score is not None:
                    result_map[(str(gid), str(sc_key))] = (str(tier), float(score))
        return result_map

    # Support list / sequence inputs
    if isinstance(data, (list, tuple)):
        for item in data:
            gid = _get_field_value(item, "gun_id")
            tier = _get_field_value(item, "tier")
            score = _get_field_value(item, "composite_score")
            sc_key = _get_field_value(item, "scenario")
            if sc_key is None:
                armor = _get_field_value(item, "armor_level")
                ammo = _get_field_value(item, "ammo_level")
                dist = _get_field_value(item, "distance_m")
                if armor is not None and ammo is not None and dist is not None:
                    sc_key = f"{armor}-{ammo}-{dist}m"
                else:
                    sc_key = "default"

            if gid is not None and tier is not None and score is not None:
                result_map[(str(gid), str(sc_key))] = (str(tier), float(score))
        return result_map

    return result_map


def has_semantic_changes(
    old_rankings: Any,
    new_rankings: Any,
    delta_threshold: float = 3.0,
) -> bool:
    """Compare existing rankings against newly computed rankings for semantic shifts.

    Returns True if:
        - Old data doesn't exist or is empty (and new data exists).
        - Any gun switches tier (e.g., T1 -> T0).
        - Any gun's composite_score shifts by abs(new - old) >= delta_threshold.
        - Weapons or scenarios are added or removed.
    Returns False if only tiny fluctuations (< delta_threshold and no tier change).
    """
    old_map = _extract_rankings_map(old_rankings)
    new_map = _extract_rankings_map(new_rankings)

    # Empty inputs
    if not old_map and not new_map:
        return False
    if not old_map and new_map:
        return True
    if old_map and not new_map:
        return True

    # Check for added or removed weapons / scenario combinations
    if set(old_map.keys()) != set(new_map.keys()):
        return True

    # Check for tier transitions and score differences >= threshold
    for key, (new_tier, new_score) in new_map.items():
        old_tier, old_score = old_map[key]
        if new_tier != old_tier:
            return True
        if abs(new_score - old_score) >= delta_threshold:
            return True

    return False


def run_pipeline(
    force: bool = False,
    live: bool = True,
    output_dir: str = ".",
    delta_threshold: float = 3.0,
    guns_path: Optional[str] = None,
    builds_path: Optional[str] = None,
    ammo_url: Optional[str] = None,
    snapshot_path: Optional[str] = None,
    baseline_path: Optional[str] = None,
) -> dict:
    """Orchestrate data collection, combat simulation, ranking, diffing, and report generation.

    Args:
        force: Force full report regeneration regardless of semantic differences.
        live: Whether to attempt live ammo price scraping (default True).
        output_dir: Root directory for output artifacts (default ".").
        delta_threshold: Score diff threshold to trigger semantic changes (default 3.0).
        guns_path: Optional custom path to weapon baseline metadata JSON.
        builds_path: Optional custom path to weapon builds JSON.
        ammo_url: Optional custom live ammo price API endpoint.
        snapshot_path: Optional custom path to snapshot ammo prices JSON.
        baseline_path: Optional custom path to baseline ammo prices JSON.

    Returns:
        Summary dictionary containing execution statistics and generated file paths.
    """
    # Step 1: Collect guns, ammo prices, and weapon builds
    guns = load_all_guns(guns_path) if guns_path else load_all_guns()

    ammo_kwargs: Dict[str, Any] = {"live": live}
    if ammo_url is not None:
        ammo_kwargs["url"] = ammo_url
    if snapshot_path is not None:
        ammo_kwargs["snapshot_path"] = snapshot_path
    if baseline_path is not None:
        ammo_kwargs["baseline_path"] = baseline_path

    ammo_prices, status = fetch_ammo_prices(**ammo_kwargs)
    builds = fetch_weapon_builds(builds_path) if builds_path else fetch_weapon_builds()

    # Step 2: Compute rankings for all 9 scenarios
    all_rankings: Dict[str, List[TierEntry]] = {}
    for sc_key, armor, ammo, dist in SCENARIO_CONFIGS:
        ranked_entries = rank_weapons(
            guns=guns,
            builds=builds,
            ammo_prices=ammo_prices,
            armor_level=armor,
            ammo_level=ammo,
            distance_m=dist,
        )
        all_rankings[sc_key] = ranked_entries

    # Step 3: Check for semantic changes against existing rankings
    latest_json_path = os.path.join(output_dir, "data", "latest_rankings.json")
    has_changes = has_semantic_changes(
        old_rankings=latest_json_path,
        new_rankings=all_rankings,
        delta_threshold=delta_threshold,
    )

    should_update = force or has_changes
    files_written: List[str] = []

    # Step 4: Render reports and export JSON if update needed
    if should_update:
        readme_path = os.path.join(output_dir, "README.md")
        render_main_readme(all_rankings, status, output_path=readme_path)
        files_written.append(readme_path)

        docs_dir = os.path.join(output_dir, "docs", "tierlist")
        scenario_files = render_scenario_docs(all_rankings, status, docs_dir=docs_dir)
        files_written.extend(scenario_files)

        exported_json = export_rankings_json(
            all_rankings, status, output_path=latest_json_path
        )
        files_written.append(exported_json)

    # Step 5: Notify GitHub Actions environment if running in CI
    if "GITHUB_ENV" in os.environ:
        github_env_file = os.environ["GITHUB_ENV"]
        env_val = "true" if (has_changes or force) else "false"
        try:
            with open(github_env_file, "a", encoding="utf-8") as f:
                f.write(f"HAS_SEMANTIC_CHANGES={env_val}\n")
        except Exception as exc:
            logger.warning("Failed to write to GITHUB_ENV at '%s': %s", github_env_file, exc)

    return {
        "has_changes": has_changes,
        "updated": should_update,
        "status": status,
        "total_guns": len(guns),
        "total_scenarios": len(all_rankings),
        "rankings": all_rankings,
        "files_written": files_written,
    }


def main() -> None:
    """CLI entrypoint for running the tier list orchestration pipeline."""
    parser = argparse.ArgumentParser(
        description="Delta Force Weapon Tier List & Economics Pipeline Orchestrator"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force full update regardless of semantic difference",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run in offline mode without attempting live fetch",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Target output directory (default: current directory)",
    )
    parser.add_argument(
        "--delta-threshold",
        type=float,
        default=3.0,
        help="Score delta threshold for semantic change detection (default: 3.0)",
    )
    args = parser.parse_args()

    result = run_pipeline(
        force=args.force,
        live=not args.offline,
        output_dir=args.output_dir,
        delta_threshold=args.delta_threshold,
    )
    print(
        f"Pipeline finished. Updated: {result['updated']}, Has Changes: {result['has_changes']}, "
        f"Guns: {result['total_guns']}, Files: {len(result['files_written'])}"
    )


if __name__ == "__main__":
    main()
