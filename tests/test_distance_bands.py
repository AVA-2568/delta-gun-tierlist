"""距离带单一来源守护。

历史上 ("贴脸","近距","中距","远距") 在 engagement / tiering / renderers 三处
独立声明, 任一处改名会让 band_summary 的 .get / in 判定静默 fail-soft,
整条距离带从榜单消失且无任何报错。本测试钉死三方一致。
"""

import os

import pytest

from src.engine import engagement as eg
from src.engine.game_data import load_game_data
from src.engine.tiering import BAND_NAMES
from src.renderers.ttk_report import BAND_ORDER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def test_band_name_sources_agree():
    """三处带名声明必须完全一致（顺序也一致）。"""
    assert tuple(eg.DISTANCE_BANDS) == tuple(BAND_NAMES) == tuple(BAND_ORDER)


def test_band_summary_keys_cover_all_bands(gd):
    """band_summary 的输出键必须覆盖全部距离带（防止静默丢带）。"""
    from src.engine.loadout import LoadoutSolver

    solver = LoadoutSolver(gd, "armor-5-ammo-5-default")
    state = solver.resolver.resolve("18010000001:base", loadout={}, tuning=None)
    ammo = solver.ammo_for("18010000001:base")
    curve = eg.ttk_curve(state, ammo, solver.armor, solver.probabilities, None)
    summary = eg.band_summary(curve)
    assert set(summary) == set(eg.DISTANCE_BANDS)
    assert len(summary) == len(eg.DISTANCE_BANDS)


def test_band_boundaries_are_contiguous():
    """距离带必须首尾相接、无空隙无重叠。"""
    edges = [(lo, hi) for lo, hi in eg.DISTANCE_BANDS.values()]
    assert edges[0][0] == 0
    assert edges[-1][1] == 80
    for (_, hi), (lo, _) in zip(edges, edges[1:]):
        assert hi == lo
