"""配装枚举与精校求解测试（Task #3）。"""

import json
import os

import pytest

from src.engine.game_data import load_game_data
from src.engine.loadout import (
    LoadoutSolver,
    build_socket_specs,
    effect_affects_ttk,
    part_affects_ttk,
    target_affects_ttk,
    tuning_breakpoints,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = "armor-4-ammo-4-default"


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def test_ttk_targets_only_rate_damage_range():
    """当前口径：TTK 只由 E[N] 与射击间隔构成 → 只认射速/弹道档案/有效射程。"""
    assert target_affects_ttk("GRateOfFire")
    assert target_affects_ttk("BulletFlyingId")
    assert target_affects_ttk("DisplayAttrValues.2")  # 优势射程 → 改变 E[N]
    assert target_affects_ttk("WeaponMainAttribute.MainAttrValues.2")
    assert not target_affects_ttk("GAiming_ADSTime")  # 开镜不进 TTK
    assert not target_affects_ttk("GBullet_Velocity")  # 初速不进 TTK
    assert not target_affects_ttk("ChangeClipTime")
    assert not target_affects_ttk("GReload_Time")


def test_zero_effects_are_ignored():
    """占位式零效果必须过滤，否则枚举空间虚高。"""
    assert not effect_affects_ttk({"target": "DisplayAttrValues.2", "modifier": "Mult_A", "value": 0.0})
    assert not effect_affects_ttk({"target": "DisplayAttrValues.2", "modifier": "Mult_A", "value": None})
    assert effect_affects_ttk({"target": "DisplayAttrValues.2", "modifier": "Mult_A", "value": 0.18})
    assert effect_affects_ttk({"target": "BulletFlyingId", "modifier": "Initial", "value": None})


def test_socket_pruning_keeps_only_ttk_relevant(gd):
    """瞄准镜 / 弹匣 / 纯开镜类配件不进枚举；改射程或射速的要进。"""
    weapon = gd.get_weapon("18010000001:base")
    specs = {s.socket_id for s in build_socket_specs(gd, weapon)}
    assert "11" not in specs  # 瞄准镜
    assert "4" not in specs  # 弹匣
    assert "38" not in specs  # 枪托：只改开镜时间 → 不影响 TTK
    assert "1" not in specs  # 后握把：只改开镜/后坐 → 不影响 TTK
    assert "2" in specs  # 枪管（改有效射程 → 改变 E[N]）


def test_pruning_shrinks_space_dramatically(gd):
    weapon = gd.get_weapon("18010000001:base")
    specs = build_socket_specs(gd, weapon)
    naive = 1
    for spec in specs:
        naive *= len(spec.options) + 1
    assert naive < 500_000  # 未剪枝时约 6.1e21


def test_tuning_breakpoints_are_curve_nodes(gd):
    """断点必须覆盖曲线控制点与取值域端点（分段线性 ⇒ 最优在断点）。"""
    part = gd.get_part("13020000173")  # AR特勤一体消音组合，长度 -10~10
    tune = next(t for t in part["tunes"] if "length" in t["tune_id"])
    pts = tuning_breakpoints(part, tune)
    assert min(pts) == pytest.approx(-10.0)
    assert max(pts) == pytest.approx(10.0)
    assert 0.0 in [round(p, 6) for p in pts]  # default 且为曲线中间控制点


def test_solved_loadout_is_legal(gd):
    """求解产出的配装必须全部落在官方插槽的合法选项内。"""
    solver = LoadoutSolver(gd, SCENARIO)
    solution = solver.solve("18050000003:base", beam_width=4, top_k=2)  # VSS，搜索空间小
    weapon = gd.get_weapon("18050000003:base")
    legal = {}
    for spec in build_socket_specs(gd, weapon, include_non_ttk=True):
        legal.setdefault(spec.socket_id, set()).update(spec.options)
    for sockets in (weapon.get("provider_sockets") or {}).values():
        for spec in sockets:
            legal.setdefault(str(spec["socket_id"]), set()).update(str(o) for o in (spec.get("options") or []))
    defaults = {str(v) for v in (weapon.get("default_items") or {}).values()}
    for socket_id, item in solution.loadout.items():
        assert item in legal.get(str(socket_id), set()) | defaults, f"槽{socket_id} 配件 {item} 非法"


def test_solved_tuning_within_official_range(gd):
    solver = LoadoutSolver(gd, SCENARIO)
    solution = solver.solve("18050000003:base", beam_width=4, top_k=2)
    for item_id, tunes in solution.tuning.items():
        part = gd.get_part(item_id)
        assert part is not None
        spec = {t["tune_id"]: t for t in part["tunes"]}
        for tune_id, value in tunes.items():
            tune = spec[tune_id]
            assert float(tune["min_value"]) - 1e-9 <= value <= float(tune["max_value"]) + 1e-9


def test_solving_improves_on_default_loadout(gd):
    """最优解不应差于默认配装。"""
    from src.engine import engagement as eg
    from src.engine.weapon_state import WeaponStateResolver

    solver = LoadoutSolver(gd, SCENARIO)
    solution = solver.solve("18050000003:base", beam_width=4, top_k=2)
    resolver = WeaponStateResolver(gd)
    default_state = resolver.resolve("18050000003:base")
    ammo = solver.ammo_for("18050000003:base")
    base_ttk = eg.ttk_at(default_state, ammo, solver.armor, solver.probabilities, 0.0).ttk_milliseconds
    assert solution.ttk_at_0m_ms <= base_ttk + 1e-6


def test_curve_is_complete_over_official_range(gd):
    """TTK 曲线覆盖官方距离场 0–80m。"""
    solver = LoadoutSolver(gd, SCENARIO)
    solution = solver.solve("18050000003:base", beam_width=4, top_k=2)
    assert len(solution.curve) == 81
    assert solution.curve[0].distance_m == 0.0
    assert solution.curve[-1].distance_m == 80.0


def test_ttk_is_shots_times_interval_only(gd):
    """当前口径：TTK = (E[N] − 1) × 射击间隔；开镜与飞行时间仅作参考、不参与。"""
    from src.engine import engagement as eg
    from src.engine.weapon_state import WeaponStateResolver

    solver = LoadoutSolver(gd, SCENARIO)
    state = WeaponStateResolver(gd).resolve("18010000001:base")
    ammo = solver.ammo_for("18010000001:base")
    kwargs = (state, ammo, solver.armor, solver.probabilities)

    at0 = eg.ttk_at(*kwargs, 0.0)
    at80 = eg.ttk_at(*kwargs, 80.0)

    for result in (at0, at80):
        expected = max(0.0, result.expected_shots - 1.0) * result.fire_interval_seconds
        assert result.ttk_seconds == pytest.approx(expected, rel=1e-9)

    # 开镜与飞行时间作为参考量给出，但不叠加进 TTK
    assert at0.ads_seconds > 0
    assert at80.flight_seconds > 0
    assert at0.ttk_seconds < at0.ttk_seconds + at0.ads_seconds
