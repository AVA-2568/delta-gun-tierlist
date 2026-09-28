"""人工覆盖层：读取 ``data/overrides/manual_corrections.json`` 并把字段覆盖登记到记录上。

从 :mod:`src.collectors.game_data_sync` 抽出。依赖方向：overrides → 标准库（无同仓库依赖）。
normalize 与 game_data_sync 单向 import 本模块；本模块**不** import 它们。

``DEFAULT_OVERRIDES_PATH`` 定义在此（覆盖层的自有默认路径）；``load_overrides`` 的默认参数
与 ``sync_all`` 的默认参数都引用它，方向统一为「上层 import 本模块」，无环。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

DEFAULT_OVERRIDES_PATH = os.path.join("data", "overrides", "manual_corrections.json")


def load_overrides(path: str = DEFAULT_OVERRIDES_PATH) -> Dict[str, Any]:
    """读取人工校正层。文件缺失视为无覆盖。"""
    if not os.path.exists(path):
        return {"weapons": {}, "ammo": {}, "armor": {}, "notes": []}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("weapons", "ammo", "armor"):
        data.setdefault(key, {})
    data.setdefault("notes", [])
    return data


def _apply_field_overrides(
    record: Dict[str, Any],
    overrides: Dict[str, Any],
    key: str,
    applied: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """把某条记录的字段覆盖应用到记录上，并登记覆盖痕迹。"""
    entry = overrides.get(key)
    if not entry:
        return record
    fields = entry.get("fields", entry)
    for field, spec in fields.items():
        if field in ("basis", "verified_at", "note"):
            continue
        if isinstance(spec, dict) and "value" in spec:
            value = spec["value"]
            basis = spec.get("basis", entry.get("basis", "manual"))
            verified_at = spec.get("verified_at", entry.get("verified_at"))
            note = spec.get("note", entry.get("note", ""))
        else:
            value = spec
            basis = entry.get("basis", "manual")
            verified_at = entry.get("verified_at")
            note = entry.get("note", "")
        record[field] = value
        applied.append(
            {
                "key": key,
                "field": field,
                "value": value,
                "basis": basis,
                "verified_at": verified_at,
                "note": note,
            }
        )
    return record
