"""价格表骨架生成：幂等性测试。"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module():
    path = os.path.join(ROOT, "tools", "build_ammo_price_skeleton.py")
    spec = importlib.util.spec_from_file_location("build_ammo_price_skeleton", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AMMO = [
    {"ammo_item_id": "a", "caliber": "5.56x45mm", "name": "M995", "penetration_level": 5},
    {"ammo_item_id": "b", "caliber": "5.56x45mm", "name": "M855A1", "penetration_level": 4},
    {"ammo_item_id": "c", "caliber": "", "name": "碳纤维穿甲箭矢", "penetration_level": 5},
]


def test_new_skeleton_has_null_prices():
    mod = _load_module()
    out = mod.build_skeleton(AMMO, None)
    assert out["schema"] == "ammo-price-avg-30d"
    assert len(out["ammo"]) == 3
    assert all(row["price_avg_30d"] is None for row in out["ammo"])


def test_existing_prices_are_preserved():
    mod = _load_module()
    existing = {"ammo": [{"ammo_item_id": "a", "price_avg_30d": 4579}]}
    out = mod.build_skeleton(AMMO, existing)
    rows = {r["ammo_item_id"]: r for r in out["ammo"]}
    assert rows["a"]["price_avg_30d"] == 4579
    assert rows["b"]["price_avg_30d"] is None
    assert rows["c"]["price_avg_30d"] is None


def test_redundant_fields_are_refreshed_from_catalogue():
    mod = _load_module()
    existing = {"ammo": [{"ammo_item_id": "a", "name": "OLD", "caliber": "OLD",
                          "penetration_level": 1, "price_avg_30d": 4579}]}
    out = mod.build_skeleton(AMMO, existing)
    row = {r["ammo_item_id"]: r for r in out["ammo"]}["a"]
    assert row["name"] == "M995"
    assert row["caliber"] == "5.56x45mm"
    assert row["penetration_level"] == 5
    assert row["price_avg_30d"] == 4579  # 价格受保护


def test_existing_header_is_kept():
    mod = _load_module()
    existing = {"window": {"from": "2026-08-23", "to": "2026-09-21", "days": 30},
                "updated_at": "2026-09-21", "ammo": []}
    out = mod.build_skeleton(AMMO, existing)
    assert out["window"]["days"] == 30
    assert out["updated_at"] == "2026-09-21"


def test_ammo_missing_from_catalogue_is_dropped():
    """目录里已删除的弹药不应残留在价格表（避免死数据）。"""
    mod = _load_module()
    existing = {"ammo": [{"ammo_item_id": "zzz", "price_avg_30d": 1}]}
    out = mod.build_skeleton(AMMO, existing)
    assert {r["ammo_item_id"] for r in out["ammo"]} == {"a", "b", "c"}
