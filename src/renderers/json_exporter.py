"""JSON serialization and exporter for Delta Force weapon tier list data."""

from datetime import datetime, timezone
import json
import os
from typing import Any, Dict, List
from src.models import DataSourceStatus, TierEntry


def export_rankings_json(
    all_rankings: Dict[str, List[TierEntry]],
    status: DataSourceStatus,
    output_path: str = "data/latest_rankings.json",
) -> str:
    """Export complete ranking results and metadata to a standardized JSON file.

    Args:
        all_rankings: Mapping of scenario identifier strings to lists of TierEntry models.
        status: DataSourceStatus containing price health and fallback metadata.
        output_path: Target filesystem path for the output JSON file.

    Returns:
        str: The normalized path to the exported JSON file.
    """
    # Ensure target parent directory exists
    dir_name = os.path.dirname(output_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    # Calculate unique tracked weapons
    unique_guns = set()
    serializable_rankings: Dict[str, List[Dict[str, Any]]] = {}

    for sc_key, entries in all_rankings.items():
        key_str = str(sc_key)
        entry_list = []
        for e in entries:
            gid = e["gun_id"] if isinstance(e, dict) else getattr(e, "gun_id", str(e))
            unique_guns.add(gid)
            if hasattr(e, "model_dump"):
                entry_list.append(e.model_dump())
            elif isinstance(e, dict):
                entry_list.append(e)
            else:
                entry_list.append(dict(e))
        serializable_rankings[key_str] = entry_list

    status_data = (
        status.model_dump()
        if hasattr(status, "model_dump")
        else dict(status)
    )

    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": status_data,
            "total_scenarios": len(all_rankings),
            "total_guns": len(unique_guns),
        },
        "rankings": serializable_rankings,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return output_path
