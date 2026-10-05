"""对外数据表导出回归（python -m src.export → data/export/）。

锁三件事：
- 规模契约：86 枪械条目（68 本体 + 18 变体）/ 1141 配件 / 4548 对接记录
  （收录 = 上游 manifest.weaponPacks 全量 68 把，官方 TTK 榜仅覆盖其中 43 把）；
- 同源锚点：link 表与 TTK 榜单同一解析口径——AS-Val 刺客高级枪管
  （换弹道 profile → 满伤 40m、680 rpm）与 M4A1 长枪管（attr2 缩放 → 52m）；
- 确定性：同一份上游数据两次导出逐字节一致（无时间戳漂移）。
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT = os.path.join(ROOT, "data", "export")


def _load(name):
    with open(os.path.join(EXPORT, name), encoding="utf-8") as fh:
        return json.load(fh)


def _weapon(rows, profile_key):
    return next(w for w in rows if w["profile_key"] == profile_key)


def _link(rows, profile_key, item_id):
    return next(x for x in rows if x["profile_key"] == profile_key and x["item_id"] == item_id)


def test_tables_scale_contract():
    weapons = _load("weapons.json")
    parts = _load("parts.json")
    links = _load("links.json")
    assert len(weapons["weapons"]) == 86
    assert sum(1 for w in weapons["weapons"] if w["is_variant"]) == 18
    assert len(parts["parts"]) == 1141
    assert len(links["links"]) == 4548
    assert weapons["dataset_version_ref"], "数据集版本引用缺失"
    assert weapons["dataset_version_ref"] == links["dataset_version_ref"]


def test_weapon_state_matches_ttk_engine():
    """枪械表状态与 TTK 引擎同源：AS-Val 官方默认态 21m 满伤 / 972 rpm。"""
    weapons = _load("weapons.json")["weapons"]
    base = _weapon(weapons, "18010000037:base")
    assert base["effective_range_m"] == 21.0
    assert base["rpm"] == 972.45
    assert base["falloff_segments"][1] == {"from_m": 21.0, "to_m": 41.0, "rate": 0.9}


def test_link_as_val_assassin_barrel():
    """对接锚点：刺客枪管换弹道 profile → 满伤 40m、680 rpm、肉伤 37（官方逐位验证过的口径）。"""
    links = _load("links.json")["links"]
    link = _link(links, "18010000037:base", "13020000561")
    after = link["after"]
    assert link["state_changed"] is True
    assert after["rpm"] == 679.89
    assert after["effective_range_m"] == 40.0
    assert after["flesh_damage"] == 37.0
    assert after["falloff_segments"][0] == {"from_m": 0.0, "to_m": 40.0, "rate": 1.0}


def test_link_m4a1_long_barrel_attr2_scaling():
    """对接锚点：M4A1 长枪管面板射程 ×1.3 → 满伤与衰减段等比缩放（52/91/1300）。"""
    links = _load("links.json")["links"]
    link = _link(links, "18010000001:base", "13020000349")
    after = link["after"]
    assert after["effective_range_m"] == 52.0
    assert [s["to_m"] for s in after["falloff_segments"]] == [52.0, 91.0, 1300.0]


def test_parts_target_semantics():
    """配件表语义化键：面板加成、profile 换挡、UI 镜像三类路由正确。"""
    parts = _load("parts.json")["parts"]
    barrel = next(p for p in parts if p["item_id"] == "13020000561")
    semantics = {e["target_semantic"] for e in barrel["effects"]}
    assert "panel.recoil_control" in semantics
    assert "profile.bullet" in semantics
    assert "profile.damage" in semantics
    assert "panel_display.effective_range" in semantics


def test_link_covers_all_sockets_and_provider_slots():
    """对接记录覆盖全部静态槽位；开放子槽位的配件（如护木）带 opens_sockets。"""
    links = _load("links.json")["links"]
    opens = [x for x in links if x["opens_sockets"]]
    assert opens, "provider_sockets 开放子槽位未被导出"
    m4_links = [x for x in links if x["weapon_id"] == "18010000001"]
    m4 = next(w for w in _load("weapons.json")["weapons"] if w["profile_key"] == "18010000001:base")
    assert len(m4_links) == sum(len(s["options"]) for s in m4["sockets"])


def test_export_is_deterministic():
    """同一份上游数据两次导出逐字节一致（确定性契约，无时间戳）。"""
    from src.export import export_all

    first = {name: open(os.path.join(EXPORT, name), "rb").read() for name in ("weapons.json", "parts.json", "links.json")}
    export_all()
    for name, payload in first.items():
        assert open(os.path.join(EXPORT, name), "rb").read() == payload, f"{name} 导出不确定"
