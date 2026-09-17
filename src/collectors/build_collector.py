"""Weapon modification builds collector and overprice normalizer."""

import json
import os
from typing import Dict, List, Optional
from src.models import WeaponBuild

DEFAULT_BUILDS_PATH = "data/default_builds.json"
DEFAULT_MAX_PRACTICAL_MOD_COST = 80000

# Practical budget attachment replacement dictionary for luxury/overpriced components
DEFAULT_OVERPRICED_REPLACEMENTS: Dict[str, str] = {
    "天价碳纤维枪托": "CTR战术枪托",
    "昂贵战术枪托": "CTR战术枪托",
    "奢华直角握把": "RK-0垂直前握把",
    "天价前握把": "RK-0垂直前握把",
    "奢华全息瞄具": "全息瞄准镜",
    "天价热成像瞄准镜": "全息瞄准镜",
    "黄金消音器": "战术消音器",
    "稀有消音器": "战术消音器",
}


def normalize_weapon_build(
    build: WeaponBuild,
    max_mod_cost: Optional[int] = DEFAULT_MAX_PRACTICAL_MOD_COST,
    replacements: Optional[Dict[str, str]] = None,
) -> WeaponBuild:
    """Normalize weapon build to eliminate excessive luxury mod costs and replace overpriced parts.

    Args:
        build: Raw WeaponBuild model instance.
        max_mod_cost: Ceiling cost for practical weapon build (default: 80,000).
        replacements: Mapping of overpriced attachment names to practical budget alternatives.

    Returns:
        A new normalized WeaponBuild instance.
    """
    rule_map = replacements if replacements is not None else DEFAULT_OVERPRICED_REPLACEMENTS
    normalized_attachments: List[str] = []
    replaced_count = 0

    for att in build.attachments:
        if att in rule_map:
            normalized_attachments.append(rule_map[att])
            replaced_count += 1
        else:
            normalized_attachments.append(att)

    # Calculate normalized cost
    new_cost = build.mod_cost
    if max_mod_cost is not None and new_cost > max_mod_cost:
        new_cost = max_mod_cost

    # If attachments were modified/replaced, the original in-game share code is invalidated
    effective_code = None if replaced_count > 0 else build.build_code
    effective_status = "manual_only" if replaced_count > 0 else build.code_status

    return WeaponBuild(
        gun_id=build.gun_id,
        build_name=build.build_name,
        build_code=effective_code,
        code_status=effective_status,
        mod_cost=new_cost,
        ads_modifier_ms=build.ads_modifier_ms,
        recoil_bonus=build.recoil_bonus,
        attachments=normalized_attachments,
    )


def fetch_weapon_builds(
    data_path: str = DEFAULT_BUILDS_PATH,
    max_mod_cost: Optional[int] = DEFAULT_MAX_PRACTICAL_MOD_COST,
    replacement_rules: Optional[Dict[str, str]] = None,
) -> Dict[str, WeaponBuild]:
    """Fetch and normalize practical weapon builds, returning a mapping of gun_id to WeaponBuild.

    Args:
        data_path: Path to the default builds JSON file.
        max_mod_cost: Optional upper bound threshold for practical modification costs.
        replacement_rules: Optional custom replacement dictionary for luxury parts.

    Returns:
        Dict mapping gun_id to its normalized WeaponBuild.

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
        normalized = normalize_weapon_build(
            raw_build, max_mod_cost=max_mod_cost, replacements=replacement_rules
        )
        builds_dict[normalized.gun_id] = normalized

    return builds_dict
