"""距离带单一来源守护。

历史上 ("贴脸","近距","中距","远距") 在 engagement / tiering / renderers 三处
独立声明, 任一处改名会让 band_summary 的 .get / in 判定静默 fail-soft,
整条距离带从榜单消失且无任何报错。

覆盖分工（收敛为单一真源后重新界定）：

* **取值与顺序的真正守护**由 :func:`test_band_values_frozen` 承担 —— 它用独立字面量
  :data:`EXPECTED_BANDS` 对照实测值。这使得**自洽改名**（三处同源、但语义已被悄悄改掉，
  例如把 ``"贴脸"`` 改成 ``"贴脸级"``）也会立即失败，把 G1 的「取值不得改动」从
  构建期全量零差异门禁下沉到单元测试。
* :func:`test_band_name_sources_agree` 是**接线回归探测器**：三方现已同源，若有人撤销
  收敛、在 tiering / ttk_report 里重新写回**发散**的字面量，它会失败。它不能守护取值。
"""

import os

import pytest

from src.engine import engagement as eg
from src.engine.game_data import load_game_data
from src.engine.tiering import BAND_NAMES
from src.renderers.ttk_report import BAND_ORDER

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 独立于生产代码的期望值（G1 冻结口径）。与 src/engine/engagement.py 的
#: DISTANCE_BANDS 实测值逐项一致；任一处被改名或改边界都会使测试失败。
EXPECTED_BANDS = {
    "贴脸": (0.0, 15.0),
    "近距": (15.0, 30.0),
    "中距": (30.0, 50.0),
    "远距": (50.0, 80.0),
}


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def test_band_name_sources_agree():
    """接线回归探测：三方带名必须同源一致（顺序也一致）。

    收敛后三者是同一元组对象, 本断言主要用于探测「撤销收敛后写回发散字面量」。
    取值的真正守护见 ``test_band_values_frozen``。
    """
    assert tuple(eg.DISTANCE_BANDS) == tuple(BAND_NAMES) == tuple(BAND_ORDER)


def test_band_values_frozen():
    """Pins 带名、顺序与边界取值到独立字面量（防自洽改名）。"""
    assert eg.DISTANCE_BANDS == EXPECTED_BANDS
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
