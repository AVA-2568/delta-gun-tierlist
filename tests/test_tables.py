"""数据表化引擎切换的对账与来源断言（契约：docs/superpowers/specs/2026-10-04-data-tables-design.md 第 2/3/4 节）。

对账口径（TTK 零变化铁律的加载侧钉子）：

- weapons：data/tables/weapons/ 按第 2 节展开规则还原后，86 条目（68 本体 + 18 官方
  变体；收录 = 上游 manifest.weaponPacks 全量 68 把，官方 TTK 榜仅覆盖其中 43 把）
  与 data/game/weapons.json 按 profile_key 配对**逐键逐值相等**（含嵌套结构与浮点，
  标量类型严格一致——复用 tools/migrate_tables.deep_equal 同一口径）；
- parts：data/tables/parts/ 合并回 {item_id: 条目} 后与 data/game/parts.json
  的 1141 条逐键逐值相等；
- ammo/armor/scenarios：与 data/game 同名文件值级相等（字节级由
  ``python tools/migrate_tables.py --check`` 兜底）；
- profiles/mechanism/validation_samples/provenance：仍读 data/game，逐值相等；
- 来源断言：用迷你表 fixture + monkeypatch TABLES_DIR 证明表域确实读
  data/tables/，参考层确实读 data_dir。

计数断言取**精确值**而非下限式：本套件是对账钉子，数据侧任何规模变化都必须
升级为一次有意的测试更新（migrate --check 的 profile_key/条目集合断言会先
报出具体差异），下限式断言会让意外缩水静默通过。
"""

import json
import os

import pytest

from src.engine import game_data as game_data_module
from src.engine.game_data import TABLES_DIR, load_game_data
from tools.migrate_tables import deep_equal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME_DIR = os.path.join(ROOT, "data", "game")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def gd():
    return load_game_data()


# ----------------------------------------------------- 第 2 节：weapons 对账 ----

def test_weapons_expansion_matches_game(gd):
    game_weapons = {e["profile_key"]: e for e in _load(os.path.join(GAME_DIR, "weapons.json"))["weapons"]}
    table_weapons = {e["profile_key"]: e for e in gd.weapons}

    assert len(gd.weapons) == 86, f"展开后应为 86 条目，实际 {len(gd.weapons)}"
    assert len(game_weapons) == 86 and len(table_weapons) == 86
    assert set(game_weapons) == set(table_weapons), "profile_key 集合不一致"

    errors = []
    deep_equal(game_weapons, table_weapons, "weapons", errors)
    assert not errors, f"逐键逐值对账失败（前 10 处）：\n" + "\n".join(errors[:10])


def test_weapons_order_matches_game(gd):
    """契约第 4 节：顺序 weapon_id 升序、base 先于变体（与原文件一致）。"""
    game_keys = [e["profile_key"] for e in _load(os.path.join(GAME_DIR, "weapons.json"))["weapons"]]
    assert [e["profile_key"] for e in gd.weapons] == game_keys


def test_weapons_base_and_variant_counts(gd):
    """68 本体（manifest.weaponPacks 全量收录）+ 18 官方榜变体（仅榜内 43 把有变体）。"""
    bases = [e for e in gd.weapons if not e["is_variant"]]
    variants = [e for e in gd.weapons if e["is_variant"]]
    assert len(bases) == 68 and len(variants) == 18


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


# ----------------------------------------------------- 第 3 节：parts 对账 ----

def test_parts_merge_matches_game(gd):
    game_parts = _load(os.path.join(GAME_DIR, "parts.json"))["parts"]

    assert len(gd.parts) == 1141, f"合并后应为 1141 条，实际 {len(gd.parts)}"
    assert set(gd.parts) == set(game_parts), "item_id 集合不一致"

    errors = []
    deep_equal(game_parts, gd.parts, "parts", errors)
    assert not errors, f"逐键逐值对账失败（前 10 处）：\n" + "\n".join(errors[:10])


def test_parts_slot_files_cover_all_slots(gd):
    slots = {e["slot"] for e in gd.parts.values()}
    files = {f[:-5] for f in os.listdir(os.path.join(TABLES_DIR, "parts")) if f.endswith(".json")}
    assert slots == files, f"槽位集合与 parts/ 文件名集合不一致：仅数据 {sorted(slots - files)}，仅文件 {sorted(files - slots)}"


# --------------------------------------------- 第 4 节：其余各域来源与对账 ----

def test_ammo_from_tables_matches_game(gd):
    game_ammo = _load(os.path.join(GAME_DIR, "ammo.json"))["ammo"]
    table_ammo = _load(os.path.join(TABLES_DIR, "ammo.json"))["ammo"]
    assert len(gd.ammo) == 113 == len(game_ammo)
    assert gd.ammo == game_ammo == table_ammo


def test_armor_from_tables_matches_game(gd):
    assert gd.armor == _load(os.path.join(TABLES_DIR, "armor.json")) == _load(os.path.join(GAME_DIR, "armor.json"))


def test_scenarios_from_tables_matches_game(gd):
    assert gd.scenarios_raw == _load(os.path.join(TABLES_DIR, "scenarios.json")) == _load(os.path.join(GAME_DIR, "scenarios.json"))
    assert len(gd.scenarios_raw["scenarios"]) == 21


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
