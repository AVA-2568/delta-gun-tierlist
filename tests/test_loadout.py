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


def test_build_loadout_is_pure_and_deterministic(gd):
    """build_loadout 是模块级纯函数：同输入必得同输出，且不依赖 resolver 实例。"""
    from src.engine.weapon_state import build_loadout

    weapon = gd.get_weapon("18010000001:base")
    first = build_loadout(weapon, {})
    second = build_loadout(weapon, {})
    assert first == second, "同一输入两次调用结果不一致，说明函数不纯"


def test_build_loadout_only_returns_legal_items(gd):
    """返回的每个配件都必须落在该槽位的合法选项内（含官方默认件）。"""
    from src.engine.loadout import build_socket_specs
    from src.engine.weapon_state import build_loadout

    weapon = gd.get_weapon("18010000001:base")
    mounted, _ = build_loadout(weapon, {})
    assert mounted, "默认配装不应为空"

    legal = {}
    # 官方根插槽（build_socket_specs 只保留影响 TTK 的插槽，弹匣等会被剪掉，
    # 故必须直接取原始 sockets 才能覆盖 coupling 强制件的槽位）
    for socket in weapon.get("sockets") or []:
        legal.setdefault(str(socket["socket_id"]), set()).update(
            str(o) for o in (socket.get("options") or [])
        )
    for spec in build_socket_specs(gd, weapon):
        legal.setdefault(str(spec.socket_id), set()).update(str(o) for o in spec.options)
    for sockets in (weapon.get("provider_sockets") or {}).values():
        for spec in sockets:
            legal.setdefault(str(spec["socket_id"]), set()).update(
                str(o) for o in (spec.get("options") or [])
            )
    defaults = {str(v) for v in (weapon.get("default_items") or {}).values()}

    for socket_id, item in mounted.items():
        assert item in legal.get(str(socket_id), set()) | defaults, f"槽{socket_id} 配件 {item} 非法"


def test_build_loadout_agrees_with_resolver(gd):
    """build_loadout 的结果必须与 resolver.resolve 内部合成的一致。

    这是 Task 11「结果透传」正确性的核心护栏：若两者不一致，
    复用预计算结果就会改变 TTK。
    """
    from src.engine.weapon_state import WeaponStateResolver, build_loadout

    weapon = gd.get_weapon("18010000001:base")
    mounted, _ = build_loadout(weapon, {})
    resolver = WeaponStateResolver(gd)
    state = resolver.resolve("18010000001:base", loadout={}, tuning=None, _precomputed_mounted=mounted)
    assert state is not None
    # 透传路径必须与 resolver 内部自行合成的结果逐位一致，否则 TTK 会静默改变
    internal = WeaponStateResolver(gd).resolve("18010000001:base", loadout={}, tuning=None)
    assert mounted == internal.loadout
