"""Weapon modification builds collector and normalizer."""

import json
import os
from typing import Dict, Union
from src.models import WeaponBuild

DEFAULT_BUILDS_PATH = "data/default_builds.json"


def normalize_weapon_build(build: Union[WeaponBuild, Dict]) -> WeaponBuild:
    """Validate and return normalized weapon build preserving authentic market cost and tuning.

    Args:
        build: WeaponBuild instance or raw dictionary.

    Returns:
        Validated WeaponBuild model instance.
    """
    if isinstance(build, dict):
        return WeaponBuild.model_validate(build)
    return build


def fetch_weapon_builds(
    data_path: str = DEFAULT_BUILDS_PATH,
) -> Dict[str, WeaponBuild]:
    """Fetch practical weapon builds from JSON dataset, returning a mapping of gun_id to WeaponBuild.

    Args:
        data_path: Path to the default builds JSON file.

    Returns:
        Dict mapping gun_id to its validated WeaponBuild.

    Raises:
        FileNotFoundError: If data_path does not exist.
        ValueError: If JSON file format is invalid.
    """
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Weapon build data file not found at '{data_path}'")

    with open(data_path, "r", encoding="utf-8") as f:
        raw_list = json.load(f)

    if not isinstance(raw_list, list):
        raise ValueError(f"Expected a JSON list in '{data_path}', got {type(raw_list).__name__}")

    builds_dict: Dict[str, WeaponBuild] = {}
    for item in raw_list:
        raw_build = WeaponBuild.model_validate(item)
        normalized = normalize_weapon_build(raw_build)
        builds_dict[normalized.gun_id] = normalized

    return builds_dict
