"""数据真源的结构与来源契约（ADR-0004：``data/tables/`` 是唯一运行期真源）。

本套件是**常驻**门槛，只钉两件事：

1. **来源**：表域（weapons/parts/ammo/armor/scenarios）确实读 ``tables_dir``
   （默认 :data:`src.engine.game_data.TABLES_DIR`），参考层
   （profiles/mechanism/validation_samples/provenance）确实读 ``data_dir``；
2. **结构**：条目规模、展开规则、槽位文件覆盖、情景集合。

``data/game/`` 已降为只读审计快照：与它的逐键逐值相等**不再**由常驻测试承担
（那是 ``python tools/migrate_tables.py --check`` 的职责），这里只比
``profile_key`` / ``item_id`` 集合以捕获集合级漂移。字段值正确性的硬门槛是
3774 点官方复现测试（``tools/verify_official_reproduction.py``）。

计数断言取**精确值**而非下限式：数据侧任何规模变化都必须升级为一次有意的
测试更新（``migrate --check`` 会先报出具体差异），下限式断言会让意外缩水
静默通过。
"""

import json
import os

import pytest

from src.engine import game_data as game_data_module
from src.engine.game_data import TABLES_DIR, load_game_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_DIR = os.path.join(ROOT, "data", "game")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def gd():
    return load_game_data()


# ------------------------------------------------- 第 2 节：weapons 结构与集合 ----

def test_weapons_expansion_profile_keys_match_snapshot(gd):
    """展开后 86 条目（68 本体 + 18 变体），profile_key 集合与审计快照一致。"""
    snapshot_keys = {
        e["profile_key"] for e in _load(os.path.join(GAME_DIR, "weapons.json"))["weapons"]
    }
    table_keys = {e["profile_key"] for e in gd.weapons}

    assert len(gd.weapons) == 86, f"展开后应为 86 条目，实际 {len(gd.weapons)}"
    assert len(table_keys) == 86, "profile_key 重复"
    assert table_keys == snapshot_keys, "profile_key 集合与审计快照不一致"


def test_weapons_base_and_variant_counts(gd):
    """68 本体（manifest.weaponPacks 全量收录）+ 18 官方榜变体（仅榜内 43 把有变体）。"""
    bases = [e for e in gd.weapons if not e["is_variant"]]
    variants = [e for e in gd.weapons if e["is_variant"]]
    assert len(bases) == 68 and len(variants) == 18


def test_weapons_order_base_before_variant(gd):
    """契约第 4 节：weapon_id 升序、base 先于其变体。"""
    weapon_ids = [e["weapon_id"] for e in gd.weapons]
    assert weapon_ids == sorted(weapon_ids)

    position = {e["profile_key"]: i for i, e in enumerate(gd.weapons)}
    for entry in gd.weapons:
        if entry["is_variant"]:
            assert position[f"{entry['weapon_id']}:base"] < position[entry["profile_key"]]


def test_weapons_expansion_rule_keys(gd):
    """展开规则显式补齐的键：base 为 false/null 三键，变体 is_variant=true 且差异块覆盖生效。"""
    base = gd.get_weapon("18010000001:base")
    assert base["is_variant"] is False
    assert base["variant_item_id"] is None and base["variant_item_name"] is None

    variant = gd.get_weapon("18010000001:13020000173")
    assert variant["is_variant"] is True
    assert variant["variant_item_id"] == "13020000173"
    # 变体块 display_name 必须覆盖 base 块（而非继承本体名）
    table = _load(os.path.join(TABLES_DIR, "weapons", "18010000001.json"))
    assert variant["display_name"] == table["variants"][0]["display_name"]
    assert variant["display_name"] != table["base"]["display_name"]


def test_unranked_weapons_are_independent_base_entries(gd):
    """榜外枪（收录全量中官方 TTK 榜不覆盖的 25 把）为独立 base 条目：
    无变体、无 candidates（无 candidateMetrics 官方锚点）、weapon_type 按 catalog
    类别推导。抽 SVD（榜外精确射手）与复合弓（特殊武器）钉形态。"""
    svd = gd.get_weapon("18050000004:base")
    assert svd["is_variant"] is False and svd["variant_item_id"] is None
    assert svd["reference_candidates"] == [] and svd["configuration_count"] == 0
    assert svd["weapon_type"] == "marksman" and svd["display_name"] == "SVD"
    assert gd.get_weapon("18150000001:base")["weapon_type"] == "special"


# --------------------------------------------------- 第 3 节：parts 结构与集合 ----

def test_parts_merge_item_ids_match_snapshot(gd):
    snapshot_ids = set(_load(os.path.join(GAME_DIR, "parts.json"))["parts"])
    assert len(gd.parts) == 1141, f"合并后应为 1141 条，实际 {len(gd.parts)}"
    assert set(gd.parts) == snapshot_ids, "item_id 集合与审计快照不一致"


def test_parts_slot_files_cover_all_slots(gd):
    slots = {e["slot"] for e in gd.parts.values()}
    files = {f[:-5] for f in os.listdir(os.path.join(TABLES_DIR, "parts")) if f.endswith(".json")}
    assert slots == files, f"槽位集合与 parts/ 文件名集合不一致：仅数据 {sorted(slots - files)}，仅文件 {sorted(files - slots)}"


# --------------------------------------------- 第 4 节：其余各域来源与集合 ----

def test_ammo_from_tables(gd):
    table_ammo = _load(os.path.join(TABLES_DIR, "ammo.json"))["ammo"]
    snapshot_ids = {a["ammo_item_id"] for a in _load(os.path.join(GAME_DIR, "ammo.json"))["ammo"]}
    assert len(gd.ammo) == 113
    assert {a["ammo_item_id"] for a in gd.ammo} == snapshot_ids
    assert {a["ammo_item_id"] for a in gd.ammo} == {a["ammo_item_id"] for a in table_ammo}


def test_armor_from_tables(gd):
    table_armor = _load(os.path.join(TABLES_DIR, "armor.json"))
    assert gd.armor == table_armor
    assert sorted(table_armor["levels"]) == sorted(str(level) for level in range(1, 7))


def test_scenarios_official_set_and_custom_entry(gd):
    """scenarios：官方 21 情景均在表侧；表侧自定义情景为修脚 ``legs-only`` 与 5 个体积预瞄情景。"""
    table = _load(os.path.join(TABLES_DIR, "scenarios.json"))
    snapshot = _load(os.path.join(GAME_DIR, "scenarios.json"))
    assert gd.scenarios_raw == table

    # scenarios 之外的顶层字段与审计快照一致
    for key in snapshot:
        if key != "scenarios":
            assert table[key] == snapshot[key], f"scenarios.json 顶层字段 {key} 与快照不一致"

    snapshot_ids = {s["scenario_id"] for s in snapshot["scenarios"]}
    table_ids = {s["scenario_id"] for s in table["scenarios"]}
    assert len(snapshot_ids) == 21
    assert snapshot_ids <= table_ids, f"官方情景在表侧缺失：{sorted(snapshot_ids - table_ids)}"

    custom = sorted(table_ids - snapshot_ids)
    assert custom == [
        "armor-4-ammo-4-volume",
        "armor-4-ammo-5-volume",
        "armor-5-ammo-4-volume",
        "armor-5-ammo-5-volume",
        "armor-6-ammo-5-volume",
        "legs-only",
    ], f"表侧自定义情景不符：{custom}"
    legs = next(s for s in table["scenarios"] if s["scenario_id"] == "legs-only")
    assert legs["probability_preset"] == "legs-only"
    assert legs["ammo_levels"] == [3, 4, 5]
    assert legs["hit_probabilities"]["thigh"] == 0.5
    assert legs["hit_probabilities"]["calf"] == 0.5
    assert sum(legs["hit_probabilities"].values()) == pytest.approx(1.0)

    # 体积预瞄情景：分布与推导脚本一致，胸:腹 = 1:2
    from tools.derive_hit_probabilities import compute, rounded

    expected = rounded(compute())
    for sid in custom:
        if sid == "legs-only":
            continue
        scenario = next(s for s in table["scenarios"] if s["scenario_id"] == sid)
        assert scenario["probability_preset"] == "volume-aim"
        assert scenario["hit_probabilities"] == expected, f"{sid} 分布与推导脚本不一致"
        probs = scenario["hit_probabilities"]
        assert sum(probs.values()) == pytest.approx(1.0)
        # 几何按胸:腹 = 1:2 分界，经预瞄权重后概率比约 0.48（胸部离预瞄点更远）
        assert probs["chest"] / probs["abdomen"] == pytest.approx(0.48, abs=0.02)


def test_reference_domains_still_from_game(gd):
    """profiles/mechanism/validation_samples/provenance 冻结在 data/game 参考层。"""
    assert gd.profiles == _load(os.path.join(GAME_DIR, "profiles.json"))["profiles"]
    assert len(gd.profiles) == 1159
    assert gd.mechanism == _load(os.path.join(GAME_DIR, "mechanism.json"))
    assert gd.validation_samples == _load(os.path.join(GAME_DIR, "validation_samples.json"))["samples"]
    assert gd.provenance == _load(os.path.join(GAME_DIR, "provenance.json"))


# ------------------------------------------------------------- 来源断言 ----

def _write_table_fixture(tmp_path):
    """构造最小 data/tables/（各表域带 marker 字段），结构同契约第 1 节。"""
    tables = tmp_path / "tables"
    (tables / "weapons").mkdir(parents=True)
    (tables / "parts").mkdir()
    (tables / "weapons" / "W1.json").write_text(json.dumps({
        "base": {"weapon_id": "W1", "flesh_damage": 40, "marker": "from-table"},
        "variants": [{
            "variant_item_id": "P1", "variant_item_name": "变体件",
            "display_name": "W1-变体件", "marker": "from-table-variant",
        }],
    }, ensure_ascii=False), encoding="utf-8")
    (tables / "parts" / "muzzle.json").write_text(json.dumps({
        "slot": "muzzle", "parts": [{"item_id": "X1", "slot": "muzzle", "marker": "from-table"}],
    }, ensure_ascii=False), encoding="utf-8")
    (tables / "ammo.json").write_text(json.dumps({
        "ammo": [{"ammo_item_id": "A1", "ammo_type_id": "T1", "penetration_level": 4, "marker": "from-table"}],
    }, ensure_ascii=False), encoding="utf-8")
    (tables / "armor.json").write_text(json.dumps({"marker": "from-table", "levels": {}}), encoding="utf-8")
    (tables / "scenarios.json").write_text(json.dumps({"marker": "from-table", "scenarios": []}), encoding="utf-8")
    return tables


def test_table_domains_read_from_tables_dir(tmp_path, monkeypatch):
    """表域（weapons/parts/ammo/armor/scenarios）确实读 TABLES_DIR：迷你表 marker 透传。"""
    tables = _write_table_fixture(tmp_path)
    monkeypatch.setattr(game_data_module, "TABLES_DIR", str(tables))

    gd = load_game_data()  # 参考层仍用默认 data/game

    assert gd.tables_dir == str(tables)
    assert gd.weapons[0]["marker"] == "from-table"
    assert gd.get_weapon("W1:base")["profile_key"] == "W1:base"
    variant = gd.get_weapon("W1:P1")
    assert variant["is_variant"] is True and variant["marker"] == "from-table-variant"
    assert gd.parts["X1"]["marker"] == "from-table"
    assert gd.ammo[0]["marker"] == "from-table" and gd.ammo_by_id["A1"]["marker"] == "from-table"
    assert gd.armor["marker"] == "from-table"
    assert gd.scenarios_raw["marker"] == "from-table"
    # 参考层不受影响：仍读 data/game
    assert gd.profiles == _load(os.path.join(GAME_DIR, "profiles.json"))["profiles"]


def test_tables_dir_argument_overrides_module_default(tmp_path, monkeypatch):
    """显式 tables_dir 优先于模块级默认值（默认值在运行时读取，非定义时固化）。"""
    tables = _write_table_fixture(tmp_path)
    monkeypatch.setattr(game_data_module, "TABLES_DIR", str(tmp_path / "no-such-tables"))

    gd = load_game_data(tables_dir=str(tables))
    assert gd.tables_dir == str(tables)
    assert gd.weapons[0]["marker"] == "from-table"


def test_data_dir_controls_reference_layer(tmp_path, monkeypatch):
    """data_dir 参数语义 = 参考层目录：profiles/mechanism 等从 data_dir 读。"""
    tables = _write_table_fixture(tmp_path)
    monkeypatch.setattr(game_data_module, "TABLES_DIR", str(tables))

    ref_dir = tmp_path / "ref"
    ref_dir.mkdir()
    (ref_dir / "profiles.json").write_text(json.dumps({"profiles": {"REF": {"marker": "from-ref"}}}), encoding="utf-8")
    (ref_dir / "mechanism.json").write_text(json.dumps({"curves": {}}), encoding="utf-8")
    (ref_dir / "validation_samples.json").write_text(json.dumps({"samples": {}}), encoding="utf-8")
    (ref_dir / "provenance.json").write_text(json.dumps({"source": {"marker": "from-ref"}}), encoding="utf-8")

    gd = load_game_data(data_dir=str(ref_dir))
    assert gd.profiles == {"REF": {"marker": "from-ref"}}
    assert gd.provenance == {"source": {"marker": "from-ref"}}
    assert gd.profiles != _load(os.path.join(GAME_DIR, "profiles.json"))["profiles"]


def test_missing_tables_error_points_to_migrate(tmp_path, monkeypatch):
    """缺表报错指向 python tools/migrate_tables.py（契约第 4 节）。"""
    monkeypatch.setattr(game_data_module, "TABLES_DIR", str(tmp_path / "no-such-tables"))
    with pytest.raises(FileNotFoundError, match=r"tools/migrate_tables\.py"):
        load_game_data()
