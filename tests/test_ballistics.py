"""弹道伤害模型测试。

期望值取自官方 ``rankings/firefight/*.json`` 的 ``candidateMetrics``（M4A1 + M855A1 等），
全部由本引擎复现。官方为确定性输出，容差取 1e-4 发（已实测最大偏差 2.5e-2 仅出现在
个别段边界样本，用于排名无实质影响，见 design spec 5.5 已知限制）。
"""

import json
import os

import pytest

from src.engine.ballistics import DamageContext, PLAYER_HEALTH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G = os.path.join(ROOT, "data", "game")

TOL = 1e-4


def _load():
    ammo = {a["ammo_item_id"]: a for a in json.load(open(os.path.join(G, "ammo.json"), encoding="utf-8"))["ammo"]}
    armor = json.load(open(os.path.join(G, "armor.json"), encoding="utf-8"))["levels"]
    weapons = json.load(open(os.path.join(G, "weapons.json"), encoding="utf-8"))["weapons"]
    scen = json.load(open(os.path.join(G, "scenarios.json"), encoding="utf-8"))
    return ammo, armor, weapons, scen


def _m4a1(weapons):
    return next(w for w in weapons if w["weapon_id"] == "18010000001" and not w.get("is_variant"))


def _scenario(scen_raw, sid):
    return next(s for s in scen_raw["scenarios"] if s["scenario_id"] == sid)


def _ctx(ammo, armor_level, probs, falloff, helmet_cov=None, armor_cov=None):
    ammo_r, armor, weapons, scen_raw = _load()
    w = _m4a1(weapons)
    dm = w["damage_profile"]
    lv = armor[str(armor_level)]
    return DamageContext(
        base_flesh=dm["base_damage"],
        base_armor=dm["base_armor_damage"],
        hitbox_multipliers=dm["hitbox_multipliers"],
        ammo=ammo_r[ammo],
        armor_level=armor_level,
        helmet_durability=lv["helmet"]["max_durability"],
        armor_durability=lv["armor"]["max_durability"],
        helmet_covered=helmet_cov or lv["helmet"]["covered_hit_areas"],
        armor_covered=armor_cov or lv["armor"]["covered_hit_areas"],
        hit_probabilities=probs,
        falloff=falloff,
    )


def _probs(sid):
    _, _, _, scen_raw = _load()
    return _scenario(scen_raw, sid)["hit_probabilities"]


# 官方期望值（armor-4-ammo-4-default，M4A1 长枪管候选）
OFFICIAL = {
    ("armor-4-ammo-4-default", 1.0): 6.194219251567757,
    ("armor-4-ammo-4-default", 0.85): 7.243458669543391,
    ("armor-4-ammo-4-center", 1.0): 6.117328896,
    ("armor-4-ammo-4-chest-only", 1.0): 5.0,
    ("armor-4-ammo-5-default", 1.0): 4.884628979928122,
    ("armor-5-ammo-4-default", 1.0): 9.580785991753558,
    ("armor-5-ammo-5-default", 1.0): 6.178525575219766,
    ("armor-6-ammo-5-default", 1.0): 9.693558147248188,
    ("armor-3-ammo-3-default", 1.0): 6.001364264416253,
}


@pytest.mark.parametrize("sid,falloff,expected", [(k[0], k[1], v) for k, v in OFFICIAL.items()])
def test_expected_kill_shots_matches_official(sid, falloff, expected):
    armor_level = int(sid.split("-")[1])
    if "ammo-4" in sid:
        ammo_id = "37100400001"
    elif "ammo-5" in sid:
        ammo_id = "37100500001"
    else:
        ammo_id = "37100300001"
    ctx = _ctx(ammo_id, armor_level, _probs(sid), falloff)
    got = ctx.expected_kill_shots()
    assert abs(got - expected) < TOL, f"{sid} falloff={falloff}: {got} vs {expected}"


def test_chest_only_yields_integer_shots():
    """仅胸部命中时无随机性，必为整数。"""
    for sid, exp in (("armor-4-ammo-4-chest-only", 5.0), ("armor-4-ammo-5-chest-only", 4.0),
                     ("armor-5-ammo-4-chest-only", 8.0), ("armor-6-ammo-5-chest-only", 8.0)):
        ammo_id = "37100400001" if "ammo-4" in sid else "37100500001"
        ctx = _ctx(ammo_id, int(sid.split("-")[1]), _probs(sid), 1.0)
        assert ctx.expected_kill_shots() == pytest.approx(exp, abs=1e-9)


def test_falloff_scales_armor_damage_too():
    """距离衰减必须同时作用于肉伤与护甲扣除（53m 官方样本反解确认）。"""
    probs = _probs("armor-4-ammo-4-default")
    no_fall = _ctx("37100400001", 4, probs, 1.0).expected_kill_shots()
    with_fall = _ctx("37100400001", 4, probs, 0.85).expected_kill_shots()
    assert with_fall > no_fall  # 伤害降低 → 发数增加
    assert with_fall == pytest.approx(7.243458669543391, abs=TOL)


def test_armor_coverage_includes_upper_arm_at_high_tiers():
    """L5/L6 背心覆盖 upperArm，覆盖不得硬编码。"""
    _, armor, _, _ = _load()
    assert "upperArm" in armor["5"]["armor"]["covered_hit_areas"]
    assert "upperArm" in armor["6"]["armor"]["covered_hit_areas"]
    assert "upperArm" not in armor["4"]["armor"]["covered_hit_areas"]
    # 覆盖上臂后更难击杀（上臂伤害被压制）
    probs = _probs("armor-5-ammo-4-default")
    ctx = _ctx("37100400001", 5, probs, 1.0)
    assert ctx.expected_kill_shots() == pytest.approx(9.580785991753558, abs=TOL)


def test_per_part_ammo_multiplier_applies():
    """弹药 perPart 倍率按部位生效（低穿透部位减伤）。"""
    _, armor, weapons, scen_raw = _load()
    w = _m4a1(weapons)
    dm = w["damage_profile"]
    ammo_rec = {a["ammo_item_id"]: a for a in json.load(open(os.path.join(G, "ammo.json"), encoding="utf-8"))["ammo"]}["37100400001"]
    lv = armor["4"]
    base_kwargs = dict(
        base_flesh=dm["base_damage"], base_armor=dm["base_armor_damage"],
        hitbox_multipliers=dm["hitbox_multipliers"], armor_level=4,
        helmet_durability=lv["helmet"]["max_durability"], armor_durability=lv["armor"]["max_durability"],
        helmet_covered=lv["helmet"]["covered_hit_areas"], armor_covered=lv["armor"]["covered_hit_areas"],
        hit_probabilities={"chest": 1.0}, falloff=1.0,
    )
    plain = DamageContext(ammo={**ammo_rec, "per_part": {}}, **base_kwargs)
    reduced = DamageContext(ammo={**ammo_rec, "per_part": {"upperChest": 0.5}}, **base_kwargs)
    assert reduced.expected_kill_shots() > plain.expected_kill_shots()


def test_player_health_is_100():
    assert PLAYER_HEALTH == 100.0


def test_falloff_segments_scale_with_effective_range():
    """距离衰减分段随优势射程等比缩放（官方：M4A1 长枪管 40/70/1000 → 52/91/1300）。"""
    from src.engine.game_data import load_game_data
    from src.engine.weapon_state import WeaponStateResolver

    gd = load_game_data(os.path.join(ROOT, "data", "game"))
    resolver = WeaponStateResolver(gd)
    state = resolver.resolve("18010000001:base", loadout={"2": "13020000349"})
    assert state.attr2_ratio == pytest.approx(1.3, abs=1e-9)
    assert state.effective_range_m == pytest.approx(52.0, abs=1e-6)
    assert state.falloff_segments[0]["to_m"] == pytest.approx(52.0, abs=1e-6)
    assert state.falloff_segments[1]["to_m"] == pytest.approx(91.0, abs=1e-6)
    assert state.falloff_segments[2]["to_m"] == pytest.approx(1300.0, abs=1e-6)
    assert state.muzzle_velocity_mps == pytest.approx(747.5, abs=1e-6)


def test_end_to_end_official_candidate_reproduction():
    """端到端：WeaponState（含配件/衰减缩放）+ 弹道模型复现官方候选期望击杀发数。"""
    from src.engine.ballistics import build_context_from_state
    from src.engine.game_data import load_game_data
    from src.engine.weapon_state import WeaponStateResolver

    gd = load_game_data(os.path.join(ROOT, "data", "game"))
    resolver = WeaponStateResolver(gd)
    state = resolver.resolve("18010000001:base", loadout={"2": "13020000349"})
    _, armor, _, _ = _load()
    probs = _probs("armor-4-ammo-4-default")
    for distance, expected in ((0.0, 6.194219251567757), (53.0, 7.243458669543391)):
        ctx = build_context_from_state(
            state, gd.get_ammo("37100400001"), armor["4"], probs, distance, armor_level=4
        )
        assert ctx.expected_kill_shots() == pytest.approx(expected, abs=TOL)
