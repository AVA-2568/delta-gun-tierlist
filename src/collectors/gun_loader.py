"""Weapon baseline metadata loader and validator."""

import json
import os
from typing import List
from src.models import GunMeta

DEFAULT_GUNS_PATH = "data/base_guns.json"


def load_all_guns(data_path: str = DEFAULT_GUNS_PATH) -> List[GunMeta]:
    """Load and validate all weapon baseline metadata records from a JSON file.

    Args:
        data_path: Path to the base guns JSON dataset.

    Returns:
        List of validated GunMeta instances.

    Raises:
        FileNotFoundError: If data_path does not exist.
        ValueError: If JSON content format is invalid.
        pydantic.ValidationError: If any gun data violates GunMeta schema.
    """
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"Gun metadata file not found at '{data_path}'")

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in '{data_path}', got {type(data).__name__}")

    return [GunMeta.model_validate(item) for item in data]
