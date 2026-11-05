"""对外榜单发布口径回归：只发布 T0/T1，且只含当前赛季可达成内容。

锁两件事（都来自 YH 的口径确认）：

1. **只发 T0 / T1**（ADR-0010）：`data/榜单/*.json` 每行至少在某个距离带是 T0/T1；
   T2/T3 行不落盘。文档侧同口径（`tests/test_renderers.py`）。
2. **赛季可达成**：榜上每一行的弹药都必须是当前赛季有效的（过期赛季限定弹不得出现），
   配装里不得出现已绝版的限时件（``EXCLUDED_PART_IDS``）。

注意：行情缺失（`price_daily` 为 null）**不是**不可达的判据——数据源可能只是还没维护，
所以这里只按赛季标记与绝版清单判定，不看价格。
"""

import glob
import json
import os

import pytest

from src.engine.loadout import EXCLUDED_PART_IDS
from src.season import CURRENT_SEASON

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD_GLOB = os.path.join(ROOT, "data", "榜单", "*.json")
PUBLISHED_TIERS = {"T0", "T1"}


def _boards():
    paths = sorted(glob.glob(BOARD_GLOB))
    assert paths, "data/榜单 为空，请先跑 python -m src.pipeline"
    return [(os.path.basename(p), json.load(open(p, encoding="utf-8"))) for p in paths]


def _ammo_index():
    with open(os.path.join(ROOT, "data", "tables", "ammo.json"), encoding="utf-8") as fh:
        return {r["ammo_item_id"]: r for r in json.load(fh)["ammo"]}


def test_boards_exist_for_all_default_scenarios():
    assert len(_boards()) == 6


@pytest.mark.parametrize("name,payload", _boards())
def test_published_rows_are_t0_or_t1_in_some_band(name, payload):
    assert payload["published_tiers"] == ["T0", "T1"]
    assert payload["published_entry_count"] == len(payload["weapons"])
    for weapon in payload["weapons"]:
        tiers = {band["tier"] for band in weapon["bands"].values()}
        assert tiers, f"{name} / {weapon['name']} 没有任何带数据"
        assert tiers <= PUBLISHED_TIERS, (
            f"{name} / {weapon['name']} 发布了非 T0/T1 的带：{sorted(tiers - PUBLISHED_TIERS)}"
        )


@pytest.mark.parametrize("name,payload", _boards())
def test_published_rows_use_current_season_ammo_only(name, payload):
    ammo = _ammo_index()
    for weapon in payload["weapons"]:
        record = ammo[weapon["ammo"]["ammo_item_id"]]
        note = record.get("season_note") or ""
        if record["is_season_limited"]:
            assert CURRENT_SEASON in note, (
                f"{name} / {weapon['name']} 用了过期赛季限定弹 "
                f"{record['name']}（{note}），当前赛季 {CURRENT_SEASON}"
            )


@pytest.mark.parametrize("name,payload", _boards())
def test_published_rows_have_no_exclusive_parts(name, payload):
    for weapon in payload["weapons"]:
        for part_id in (weapon.get("loadout") or {}).values():
            assert str(part_id) not in EXCLUDED_PART_IDS, (
                f"{name} / {weapon['name']} 配装含已绝版限时件 {part_id}"
            )


def test_s12_new_ammo_present_in_tables():
    """S12 官方公布的 5 款新弹必须在表内（口径/等级不得丢）。"""
    ammo = _ammo_index()
    expected = {
        "37280400003": ("TIV", 4),
        "37280500003": ("TTV", 5),
        "37100400003": ("CINDER", 4),
        "37200500002": ("7N30", 5),
        "37120400004": ("SPALL", 4),
    }
    for item_id, (label, level) in expected.items():
        record = ammo[item_id]
        assert record["name"] == label
        assert record["penetration_level"] == level
        assert record["caliber"], f"{label} 口径为空"
