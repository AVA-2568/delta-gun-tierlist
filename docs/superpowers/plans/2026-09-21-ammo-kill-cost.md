# 弹药击杀成本展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 TTK 榜新增「弹药 / 单发价 / 击杀成本」三列，成本 = 带内平均期望击杀发数 × 单发 30 天均价（哈夫币）。

**Architecture:** 价格数据走**独立只读模块 + 管道注入**，与官方战斗数据物理隔离。引擎层只给 `band_summary` 增加一个返回字段（带内平均 `E[N]`）；成本在**装配层** `tiering` 计算；渲染层仅做格式化（项目铁律：渲染层禁止二次计算）。

**Tech Stack:** Python 3.13，运行期**零第三方依赖**（仅标准库 `json`/`dataclasses`），测试用 pytest。

**规范来源：** `docs/superpowers/specs/2026-09-21-ammo-kill-cost-design.md` (v1.0.0)

## Global Constraints

- **零第三方运行期依赖**：只能用标准库。`pytest` 仅用于测试。
- **渲染层禁止二次计算**：`src/renderers/ttk_report.py` 只做格式化，所有数值必须由 payload 直接提供。
- **禁用内建 `round()`**：Python 为银行家舍入（`round(2.5) == 2`），成本取整统一用 `int(x + 0.5)`。
- **缺价不猜测**：价格缺失一律渲染 `—`（`None`），不得用同口径均价兜底。
- **币种固定 `哈夫币`**，格式 `4,579 哈夫币`（千分位整数）。
- **不改排序与分层**：成本仅作展示列，`ranking_key` / `tier_quantiles` 一律不动。
- **既有 66 项测试必须全绿**（`pytest tests/ -q`）。

---

## File Structure

| 文件 | 职责 | 动作 |
| :-- | :-- | :-- |
| `src/engine/ammo_pricing.py` | 加载手工维护的均价表 + 按 `ammo_item_id` 查价。**零计算** | 新建 |
| `data/reference/ammo_prices.json` | 单价数据（人工填 `price_avg_30d`） | 新建（由脚本产出） |
| `tools/build_ammo_price_skeleton.py` | 从 `ammo.json` 生成/刷新价格表骨架，**幂等** | 新建 |
| `src/engine/engagement.py` | `band_summary` 增加 `mean_expected_shots` | 修改 |
| `src/engine/tiering.py` | `compute_kill_cost`、`BandResult`/`GunRanking` 加字段、装配与序列化 | 修改 |
| `src/renderers/ttk_report.py` | 三列渲染 + `_fmt_money` + 时效标注 | 修改 |
| `src/pipeline.py` | 加载价格表并注入 | 修改 |
| `tests/test_ammo_pricing.py` | 价格表加载/查价单测 | 新建 |
| `tests/test_band_summary.py` | 带内 `E[N]` 均值单测 | 新建 |
| `tests/test_kill_cost.py` | 成本计算 + `to_export` 单测 | 新建 |
| `tests/test_ammo_price_skeleton.py` | 骨架幂等单测 | 新建 |
| `tests/test_renderers.py` | 三列渲染单测 | 修改（追加） |
| `tests/test_pipeline.py` | 端到端新字段断言 | 修改（追加） |

---

## Task 1: 弹药均价表模块

**Files:**
- Create: `src/engine/ammo_pricing.py`
- Test: `tests/test_ammo_pricing.py`

**Interfaces:**
- Consumes: 无（独立模块）
- Produces:
  - `AmmoPriceTable`（frozen dataclass）：字段 `currency: str`、`window: Mapping[str, Any]`、`updated_at: str`、`prices: Mapping[str, int]`；方法 `price_for(ammo_item_id: str) -> Optional[int]`；属性 `is_empty -> bool`
  - `load_ammo_prices(path: str) -> AmmoPriceTable`
  - 常量 `DEFAULT_CURRENCY = "哈夫币"`、`EXPECTED_SCHEMA = "ammo-price-avg-30d"`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_ammo_pricing.py`：

```python
"""弹药均价表加载与查价测试。"""

import json

from src.engine.ammo_pricing import DEFAULT_CURRENCY, AmmoPriceTable, load_ammo_prices


def _write(tmp_path, payload):
    path = tmp_path / "ammo_prices.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _valid_payload():
    return {
        "schema": "ammo-price-avg-30d",
        "currency": "哈夫币",
        "window": {"from": "2026-08-23", "to": "2026-09-21", "days": 30},
        "updated_at": "2026-09-21",
        "ammo": [
            {"ammo_item_id": "37100500001", "caliber": "5.56x45mm", "name": "M995",
             "penetration_level": 5, "price_avg_30d": 4579},
            {"ammo_item_id": "37100400001", "caliber": "5.56x45mm", "name": "M855A1",
             "penetration_level": 4, "price_avg_30d": None},
        ],
    }


def test_loads_prices_and_meta(tmp_path):
    table = load_ammo_prices(_write(tmp_path, _valid_payload()))
    assert table.currency == "哈夫币"
    assert table.window["days"] == 30
    assert table.updated_at == "2026-09-21"
    assert table.price_for("37100500001") == 4579
    assert not table.is_empty


def test_null_price_is_treated_as_missing(tmp_path):
    table = load_ammo_prices(_write(tmp_path, _valid_payload()))
    assert table.price_for("37100400001") is None


def test_unknown_item_returns_none(tmp_path):
    table = load_ammo_prices(_write(tmp_path, _valid_payload()))
    assert table.price_for("does-not-exist") is None


def test_missing_file_yields_empty_table(tmp_path):
    table = load_ammo_prices(str(tmp_path / "nope.json"))
    assert table.is_empty
    assert table.price_for("37100500001") is None
    assert table.currency == DEFAULT_CURRENCY
    assert table.updated_at == ""
    assert table.window == {}


def test_invalid_json_yields_empty_table(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_ammo_prices(str(path)).is_empty


def test_wrong_schema_yields_empty_table(tmp_path):
    payload = _valid_payload()
    payload["schema"] = "something-else"
    assert load_ammo_prices(_write(tmp_path, payload)).is_empty


def test_invalid_prices_are_dropped(tmp_path):
    payload = _valid_payload()
    payload["ammo"] = [
        {"ammo_item_id": "a", "price_avg_30d": 0},
        {"ammo_item_id": "b", "price_avg_30d": -5},
        {"ammo_item_id": "c", "price_avg_30d": "123"},
        {"ammo_item_id": "d", "price_avg_30d": 100.5},
        {"ammo_item_id": "e", "price_avg_30d": True},
        {"ammo_item_id": "f", "price_avg_30d": 7},
    ]
    table = load_ammo_prices(_write(tmp_path, payload))
    for bad in ("a", "b", "c", "d", "e"):
        assert table.price_for(bad) is None, bad
    assert table.price_for("f") == 7


def test_frozen_table_is_immutable():
    table = AmmoPriceTable()
    assert table.currency == DEFAULT_CURRENCY
    assert table.is_empty
    try:
        table.currency = "x"  # type: ignore[misc]
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("AmmoPriceTable 应为不可变")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_ammo_pricing.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.engine.ammo_pricing'`

- [ ] **Step 3: 写最小实现**

创建 `src/engine/ammo_pricing.py`：

```python
"""弹药均价表：加载手工维护的 30 天成交均价，并按 ``ammo_item_id`` 查价。

本模块只做两件事——**加载**与**查价**，不含任何计算。

价格是手工维护的第三方市场均价（非官方数据），故与 ``data/game/*``（官方同步数据）
物理隔离：来源、更新频率、可信度三者都不同，混在一起会污染 ``provenance`` 语义。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

#: 兜底币种（表缺失时渲染层仍需要一个单位名）
DEFAULT_CURRENCY = "哈夫币"

#: 期望的表格式标识；不符则整表忽略，避免误读别种 JSON
EXPECTED_SCHEMA = "ammo-price-avg-30d"


@dataclass(frozen=True)
class AmmoPriceTable:
    """弹药单发均价表（30 天成交均价，单位见 ``currency``）。"""

    currency: str = DEFAULT_CURRENCY
    window: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    prices: Mapping[str, int] = field(default_factory=dict)

    def price_for(self, ammo_item_id: str) -> Optional[int]:
        """按弹药主键查单发均价；缺价或未知 id 返回 ``None``。"""
        return self.prices.get(str(ammo_item_id))

    @property
    def is_empty(self) -> bool:
        """是否没有任何可用价格（文件缺失 / 全未填时渲染层据此调整说明文案）。"""
        return not self.prices


def _empty() -> AmmoPriceTable:
    return AmmoPriceTable()


def _coerce_price(value: Any) -> Optional[int]:
    """只接受正整数；``bool``/``float``/字符串一律视为无效（缺价）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def load_ammo_prices(path: str) -> AmmoPriceTable:
    """加载均价表。

    文件缺失、无法解析或 schema 不符时返回**空表**（不抛异常），
    使榜单在未配置价格时保持可用——成本列显示 ``—``，战斗数值完全不变。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        logger.info("未找到弹药均价表（%s），成本列将显示 —", path)
        return _empty()
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("弹药均价表无法读取（%s）：%s", path, exc)
        return _empty()

    if not isinstance(raw, dict) or raw.get("schema") != EXPECTED_SCHEMA:
        logger.warning("弹药均价表 schema 不符（期望 %s），整表忽略", EXPECTED_SCHEMA)
        return _empty()

    prices: Dict[str, int] = {}
    for entry in raw.get("ammo") or []:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("ammo_item_id")
        price = _coerce_price(entry.get("price_avg_30d"))
        if not item_id or price is None:
            continue
        prices[str(item_id)] = price

    window = raw.get("window")
    return AmmoPriceTable(
        currency=str(raw.get("currency") or DEFAULT_CURRENCY),
        window=dict(window) if isinstance(window, dict) else {},
        updated_at=str(raw.get("updated_at") or ""),
        prices=prices,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_ammo_pricing.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
git add src/engine/ammo_pricing.py tests/test_ammo_pricing.py
git commit -m "feat(ammo): 新增弹药均价表加载模块（零计算，缺文件降级为空表）"
```

---

## Task 2: `band_summary` 增加带内平均期望发数

**Files:**
- Modify: `src/engine/engagement.py`（`band_summary`，约 181-194 行）
- Test: `tests/test_band_summary.py`（新建）

**Interfaces:**
- Consumes: `TtkResult`（既有）、`DISTANCE_BANDS`（既有）
- Produces: `band_summary(curve)` 返回的每个带字典**新增** `mean_expected_shots: float`（该带内各距离点 `expected_shots` 的算术平均，**不取整**）；既有 `min_ms` / `max_ms` / `mean_ms` 语义不变

- [ ] **Step 1: 写失败测试**

创建 `tests/test_band_summary.py`：

```python
"""距离带聚合（band_summary）测试。"""

import pytest

from src.engine.engagement import TtkResult, band_summary


def _result(distance_m: float, ttk_ms: float, expected_shots: float) -> TtkResult:
    return TtkResult(
        distance_m=distance_m,
        ttk_seconds=ttk_ms / 1000.0,
        expected_shots=expected_shots,
        ads_seconds=0.0,
        flight_seconds=0.0,
        fire_interval_seconds=0.05,
        rpm=1200.0,
        falloff=1.0,
        effective_range_m=40.0,
        muzzle_velocity_mps=500.0,
    )


def test_mean_expected_shots_is_arithmetic_mean():
    # 贴脸带（0–15m）含 0/5/10 三个点
    curve = [
        _result(0.0, 200.0, 5.0),
        _result(5.0, 200.0, 5.0),
        _result(10.0, 250.0, 6.0),
        _result(20.0, 300.0, 7.0),
    ]
    bands = band_summary(curve)
    assert bands["贴脸"]["mean_expected_shots"] == pytest.approx(16.0 / 3.0)
    assert bands["近距"]["mean_expected_shots"] == pytest.approx(7.0)


def test_mean_expected_shots_is_not_rounded():
    """供成本计算消费，必须保留精度（若被 round 到 2 位会引入成本误差）。"""
    curve = [_result(0.0, 100.0, 5.5431), _result(1.0, 100.0, 6.1001)]
    bands = band_summary(curve)
    expected = (5.5431 + 6.1001) / 2.0
    assert bands["贴脸"]["mean_expected_shots"] == pytest.approx(expected, abs=1e-12)


def test_existing_fields_unchanged():
    curve = [_result(0.0, 200.0, 5.0), _result(10.0, 300.0, 6.0)]
    bands = band_summary(curve)
    assert set(bands["贴脸"]) == {"min_ms", "max_ms", "mean_ms", "mean_expected_shots"}
    assert bands["贴脸"]["min_ms"] == pytest.approx(200.0)
    assert bands["贴脸"]["max_ms"] == pytest.approx(300.0)
    assert bands["贴脸"]["mean_ms"] == pytest.approx(250.0)


def test_empty_band_is_skipped():
    assert band_summary([_result(60.0, 200.0, 5.0)]).get("贴脸") is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_band_summary.py -q`
Expected: FAIL — `KeyError: 'mean_expected_shots'`

- [ ] **Step 3: 写最小实现**

在 `src/engine/engagement.py` 中，把 `band_summary` 整体替换为：

```python
def band_summary(curve: Sequence[TtkResult]) -> Dict[str, Dict[str, float]]:
    """按距离带聚合：带内 TTK（毫秒）与带内平均期望击杀发数。

    ``mean_expected_shots`` 供上层计算击杀成本使用，故**不做取整**——
    它乘上单价后由成本函数统一四舍五入。
    """
    out: Dict[str, Dict[str, float]] = {}
    for name, (lo, hi) in DISTANCE_BANDS.items():
        points = [r for r in curve if lo <= r.distance_m <= hi]
        if not points:
            continue
        ttks = [r.ttk_milliseconds for r in points]
        shots = [r.expected_shots for r in points]
        out[name] = {
            "min_ms": round(min(ttks), 2),
            "max_ms": round(max(ttks), 2),
            "mean_ms": round(sum(ttks) / len(ttks), 2),
            "mean_expected_shots": sum(shots) / len(shots),
        }
    return out
```

- [ ] **Step 4: 跑测试确认通过（含既有测试回归）**

Run: `python -m pytest tests/test_band_summary.py tests/test_tiering.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engine/engagement.py tests/test_band_summary.py
git commit -m "feat(engine): band_summary 增加带内平均期望击杀发数（不取整）"
```

---

## Task 3: 成本计算函数与数据结构扩展

**Files:**
- Modify: `src/engine/tiering.py`（`BandResult`、`GunRanking`、新增 `compute_kill_cost`）
- Test: `tests/test_kill_cost.py`（新建）

**Interfaces:**
- Consumes: `AmmoPriceTable.price_for`（Task 1，尚未接线，本任务只用其类型）
- Produces:
  - `compute_kill_cost(mean_expected_shots: Optional[float], price_per_round: Optional[int]) -> Optional[int]`
  - `BandResult` 新增带默认值字段：`mean_expected_shots: float = 0.0`、`kill_cost: Optional[int] = None`
  - `GunRanking` 新增带默认值字段：`ammo_item_id: str = ""`、`ammo_name: str = ""`、`ammo_caliber: str = ""`、`ammo_price_avg_30d: Optional[int] = None`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_kill_cost.py`：

```python
"""击杀成本计算测试（口径：带内平均期望发数 × 单发均价，四舍五入）。"""

from src.engine.tiering import BandResult, GunRanking, compute_kill_cost


def test_basic_cost():
    # 5.543 × 4579 = 25380.797 → int(+0.5) = 25381
    assert compute_kill_cost(5.543, 4579) == 25381


def test_rounds_half_up_not_bankers():
    """内建 round() 会把 2.5 舍成 2；成本必须向上取整到 3。"""
    assert compute_kill_cost(2.5, 1) == 3
    assert compute_kill_cost(3.5, 1) == 4
    assert round(2.5) == 2  # 佐证为何禁用 round()


def test_missing_inputs_yield_none():
    assert compute_kill_cost(None, 100) is None
    assert compute_kill_cost(5.0, None) is None
    assert compute_kill_cost(None, None) is None


def test_band_result_new_fields_have_defaults():
    band = BandResult(band="贴脸", mean_ms=286.92, worst_ms=286.92, best_ms=286.92)
    assert band.mean_expected_shots == 0.0
    assert band.kill_cost is None


def test_gun_ranking_new_fields_have_defaults():
    entry = GunRanking(
        profile_key="p", weapon_id="w", display_name="GUN", base_name="GUN",
        category="突击步枪", is_variant=False, variant_item_name=None,
        loadout={}, tuning={},
    )
    assert entry.ammo_item_id == ""
    assert entry.ammo_name == ""
    assert entry.ammo_caliber == ""
    assert entry.ammo_price_avg_30d is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_kill_cost.py -q`
Expected: FAIL — `ImportError: cannot import name 'compute_kill_cost'`

- [ ] **Step 3: 写最小实现**

在 `src/engine/tiering.py` 中：

(a) `BandResult` 末尾追加两个字段：

```python
@dataclass
class BandResult:
    """一个距离带内该枪的聚合结果。"""

    band: str
    mean_ms: float
    worst_ms: float
    best_ms: float
    rank: int = 0
    tier: str = ""
    mean_expected_shots: float = 0.0
    kill_cost: Optional[int] = None
```

(b) `GunRanking` 末尾追加四个字段：

```python
    effective_range_m: float = 0.0
    ammo_item_id: str = ""
    ammo_name: str = ""
    ammo_caliber: str = ""
    ammo_price_avg_30d: Optional[int] = None
```

(c) 在 `_quantile` 之前新增纯函数：

```python
def compute_kill_cost(
    mean_expected_shots: Optional[float],
    price_per_round: Optional[int],
) -> Optional[int]:
    """单次击杀的弹药成本（哈夫币）：带内平均期望发数 × 单发均价。

    **禁用内建 ``round()``**：Python 采用银行家舍入（``round(2.5) == 2``），
    会让成本列出现反直觉数值，故统一用 ``int(x + 0.5)``。

    任一输入为 ``None``（缺价）时返回 ``None``——不猜测、不兜底。
    """
    if mean_expected_shots is None or price_per_round is None:
        return None
    return int(mean_expected_shots * price_per_round + 0.5)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_kill_cost.py tests/test_tiering.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engine/tiering.py tests/test_kill_cost.py
git commit -m "feat(tiering): 新增击杀成本计算与弹药字段（禁用 round，四舍五入）"
```

---

## Task 4: 装配 —— 把弹药、单价、成本装进 GunRanking

**Files:**
- Modify: `src/engine/tiering.py`（`rank_weapons_for_scenario` 签名与循环体）
- Test: `tests/test_kill_cost.py`（追加集成测试）

**Interfaces:**
- Consumes: `LoadoutSolver.ammo_for(profile_key) -> Mapping`（既有，返回含 `ammo_item_id` / `name` / `caliber` 的官方弹药记录）；`AmmoPriceTable`（Task 1）；`compute_kill_cost`（Task 3）
- Produces: `rank_weapons_for_scenario(..., price_table=None)`；每个 `GunRanking` 带 `ammo_*` 字段，每个 `BandResult` 带 `mean_expected_shots` / `kill_cost`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kill_cost.py` 的**文件顶部 import 区**补充下列 import 与模块常量（**不要**把它们追加到文件末尾——那会形成模块中部的 import）；下面的测试函数则追加到文件末尾：

```python
import os

import pytest

from src.engine.ammo_pricing import AmmoPriceTable
from src.engine.game_data import load_game_data
from src.engine.tiering import BAND_NAMES, rank_weapons_for_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def test_ranking_attaches_ammo_and_cost(gd):
    """VSS 在 5-5 情景可用；给了价格表后每带都应有成本。"""
    table = AmmoPriceTable(prices={"__any__": 1000})
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"], price_table=table,
    )
    entry = rankings[0]
    assert entry.ammo_item_id, "应带出实际使用的弹药主键"
    assert entry.ammo_name
    for band in BAND_NAMES:
        assert band in entry.bands
        assert entry.bands[band].mean_expected_shots > 0
    # 价格表里没有该弹药 → 缺价 → 全 None
    assert all(entry.bands[b].kill_cost is None for b in entry.bands)


def test_cost_uses_band_mean_shots(gd):
    """成本必须等于该带 mean_expected_shots × 单价（四舍五入）。"""
    price = 2000
    table = AmmoPriceTable(prices={"__any__": price})
    rankings, _t, _e = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"], price_table=table,
    )
    entry = rankings[0]
    assert entry.ammo_price_avg_30d is None  # 该弹未配价

    # 用真实 id 再跑一次，确认成本公式
    real_id = entry.ammo_item_id
    table2 = AmmoPriceTable(prices={real_id: price})
    rankings2, _t2, _e2 = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"], price_table=table2,
    )
    entry2 = rankings2[0]
    assert entry2.ammo_price_avg_30d == price
    for band in BAND_NAMES:
        expected = compute_kill_cost(entry2.bands[band].mean_expected_shots, price)
        assert entry2.bands[band].kill_cost == expected


def test_ranking_without_price_table_still_works(gd):
    """不传价格表：TTK 与发数照常，成本为 None（榜单完全可用）。"""
    rankings, _t, _e = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"],
    )
    entry = rankings[0]
    assert entry.bands["贴脸"].mean_ms > 0
    assert entry.bands["贴脸"].mean_expected_shots > 0
    assert entry.bands["贴脸"].kill_cost is None
    assert entry.ammo_price_avg_30d is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_kill_cost.py -q`
Expected: FAIL — `TypeError: rank_weapons_for_scenario() got an unexpected keyword argument 'price_table'`

- [ ] **Step 3: 写最小实现**

在 `src/engine/tiering.py` 中：

(a) 顶部 import 增加（`AmmoPriceTable` 仅用于类型标注，用 `TYPE_CHECKING` 避免循环依赖）：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from src.engine.ammo_pricing import AmmoPriceTable
```

(b) `rank_weapons_for_scenario` 签名增加参数：

```python
def rank_weapons_for_scenario(
    game_data: Any,
    scenario_id: str,
    solver: Optional[LoadoutSolver] = None,
    beam_width: int = 8,
    top_k: int = 4,
    profile_keys: Optional[Sequence[str]] = None,
    price_table: Optional["AmmoPriceTable"] = None,
) -> tuple:
```

(c) 在 `solver = solver or LoadoutSolver(...)` 之后、循环之前，取出该情景弹药并查一次价（弹药与情景绑定，与具体配装无关）：

```python
    # 弹药由「武器口径 × 情景弹药等级」唯一确定，与配装无关，可整体缓存查价结果。
    price_cache: Dict[str, Optional[int]] = {}

    def _price_of(ammo_item_id: str) -> Optional[int]:
        if ammo_item_id not in price_cache:
            price_cache[ammo_item_id] = (
                price_table.price_for(ammo_item_id) if price_table is not None else None
            )
        return price_cache[ammo_item_id]
```

(d) 循环体内，在 `summary = eg.band_summary(solution.curve)` 之前插入弹药解析：

```python
        ammo = solver.ammo_for(profile_key)
        ammo_item_id = str(ammo.get("ammo_item_id") or "")
        ammo_price = _price_of(ammo_item_id)
```

(e) 把 `bands` 构造改为（同时填 `mean_expected_shots` 与 `kill_cost`）：

```python
        bands = {
            name: BandResult(
                band=name,
                mean_ms=stats["mean_ms"],
                worst_ms=stats["max_ms"],
                best_ms=stats["min_ms"],
                mean_expected_shots=stats["mean_expected_shots"],
                kill_cost=compute_kill_cost(stats["mean_expected_shots"], ammo_price),
            )
            for name, stats in summary.items()
        }
```

(f) `GunRanking(...)` 构造追加四个字段（放在 `effective_range_m` 之后）：

```python
                effective_range_m=curve0.effective_range_m,
                ammo_item_id=ammo_item_id,
                ammo_name=str(ammo.get("name") or ""),
                ammo_caliber=str(ammo.get("caliber") or ""),
                ammo_price_avg_30d=ammo_price,
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_kill_cost.py tests/test_tiering.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engine/tiering.py tests/test_kill_cost.py
git commit -m "feat(tiering): 装配弹药名与每带击杀成本（缺价留 None）"
```

---

## Task 5: `to_export` 序列化新字段

**Files:**
- Modify: `src/engine/tiering.py`（`to_export` 签名与输出）
- Test: `tests/test_kill_cost.py`（追加）

**Interfaces:**
- Consumes: `AmmoPriceTable`（Task 1）、`GunRanking.ammo_*` / `BandResult.kill_cost`（Task 4）
- Produces: `to_export(rankings, thresholds, scenario_id, excluded=None, price_table=None) -> Dict`；payload 顶层新增 `ammo_price_meta`，`weapons[].ammo`，`bands[].mean_expected_shots` / `bands[].kill_cost`

- [ ] **Step 1: 写失败测试**

在 `tests/test_kill_cost.py` 追加：

```python
def test_to_export_emits_ammo_and_meta(gd):
    """走真实链路：先取实际弹药主键，再用含该键的价格表跑完整装配与序列化。"""
    from src.engine.tiering import to_export

    probe, _t0, _e0 = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"],
    )
    real_id = probe[0].ammo_item_id
    assert real_id, "装配层必须带出弹药主键"

    table = AmmoPriceTable(
        currency="哈夫币",
        window={"from": "2026-08-23", "to": "2026-09-21", "days": 30},
        updated_at="2026-09-21",
        prices={real_id: 4579},
    )
    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"], price_table=table,
    )
    payload = to_export(rankings, thresholds, "armor-5-ammo-5-default", excluded, price_table=table)

    meta = payload["ammo_price_meta"]
    assert meta["currency"] == "哈夫币"
    assert meta["available"] is True
    assert meta["window"]["days"] == 30
    assert meta["updated_at"] == "2026-09-21"

    entry = rankings[0]
    weapon = payload["weapons"][0]
    assert weapon["ammo"]["ammo_item_id"] == real_id
    assert weapon["ammo"]["name"] == entry.ammo_name
    assert weapon["ammo"]["caliber"] == entry.ammo_caliber
    assert weapon["ammo"]["price_avg_30d"] == 4579
    assert entry.ammo_price_avg_30d == 4579
    band = weapon["bands"]["贴脸"]
    assert band["kill_cost"] == compute_kill_cost(entry.bands["贴脸"].mean_expected_shots, 4579)
    assert entry.bands["贴脸"].kill_cost == band["kill_cost"]
    assert band["mean_expected_shots"] == pytest.approx(entry.bands["贴脸"].mean_expected_shots, abs=1e-6)


def test_to_export_without_price_table_marks_unavailable(gd):
    from src.engine.tiering import to_export

    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=2, top_k=1,
        profile_keys=["18050000003:base"],
    )
    payload = to_export(rankings, thresholds, "armor-5-ammo-5-default", excluded)
    assert payload["ammo_price_meta"]["available"] is False
    assert payload["weapons"][0]["ammo"]["price_avg_30d"] is None
    assert payload["weapons"][0]["bands"]["贴脸"]["kill_cost"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_kill_cost.py -q -k to_export`
Expected: FAIL — `KeyError: 'ammo_price_meta'`

- [ ] **Step 3: 写最小实现**

在 `src/engine/tiering.py` 中：

(a) `to_export` 签名增加参数：

```python
def to_export(
    rankings: List[GunRanking],
    thresholds: Mapping[str, Mapping[str, float]],
    scenario_id: str,
    excluded: Optional[Sequence[Mapping[str, str]]] = None,
    price_table: Optional["AmmoPriceTable"] = None,
) -> Dict[str, Any]:
```

(b) `payload_rankings` 的每项追加 `ammo`，并在 `bands` 内追加两个字段：

```python
                "effective_range_m": round(entry.effective_range_m, 2),
                "ammo": {
                    "ammo_item_id": entry.ammo_item_id,
                    "name": entry.ammo_name,
                    "caliber": entry.ammo_caliber,
                    "price_avg_30d": entry.ammo_price_avg_30d,
                },
                "bands": {
                    name: {
                        "rank": b.rank,
                        "tier": b.tier,
                        "mean_ms": round(b.mean_ms, 2),
                        "worst_ms": round(b.worst_ms, 2),
                        "best_ms": round(b.best_ms, 2),
                        "mean_expected_shots": round(b.mean_expected_shots, 6),
                        "kill_cost": b.kill_cost,
                    }
                    for name, b in entry.bands.items()
                },
```

(c) 返回字典顶层追加 `ammo_price_meta`（放在 `"scenario_id"` 之后即可）：

```python
        "ammo_price_meta": {
            "currency": price_table.currency if price_table is not None else "哈夫币",
            "window": dict(price_table.window) if price_table is not None else {},
            "updated_at": price_table.updated_at if price_table is not None else "",
            "available": bool(price_table is not None and not price_table.is_empty),
        },
```

- [ ] **Step 4: 跑测试确认通过（含既有 test_tiering 形状断言）**

Run: `python -m pytest tests/test_kill_cost.py tests/test_tiering.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engine/tiering.py tests/test_kill_cost.py
git commit -m "feat(tiering): to_export 输出弹药、每带成本与价格表元信息"
```

---

## Task 6: 价格表骨架生成脚本

**Files:**
- Create: `tools/build_ammo_price_skeleton.py`
- Create: `data/reference/ammo_prices.json`（运行脚本产出）
- Test: `tests/test_ammo_price_skeleton.py`

**Interfaces:**
- Consumes: `data/game/ammo.json`
- Produces: `build_skeleton(ammo_records: Sequence[Mapping], existing: Optional[Mapping]) -> Dict[str, Any]`（纯函数，可测）；CLI `python tools/build_ammo_price_skeleton.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_ammo_price_skeleton.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_ammo_price_skeleton.py -q`
Expected: FAIL — 文件不存在（`FileNotFoundError` / `spec.loader is None`）

- [ ] **Step 3: 写最小实现**

创建 `tools/build_ammo_price_skeleton.py`：

```python
"""生成 / 刷新弹药均价表骨架。

用法::

    python tools/build_ammo_price_skeleton.py            # 就地刷新 data/reference/ammo_prices.json
    python tools/build_ammo_price_skeleton.py --check    # 只报告差异，不写盘

**幂等保证**：``price_avg_30d`` 是唯一受保护的用户数据——已有值原样保留；
``caliber`` / ``name`` / ``penetration_level`` 属冗余辨认字段，每次从 ``ammo.json`` 刷新。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AMMO_CATALOGUE = os.path.join(ROOT, "data", "game", "ammo.json")
PRICE_TABLE = os.path.join(ROOT, "data", "reference", "ammo_prices.json")

SCHEMA = "ammo-price-avg-30d"
CURRENCY = "哈夫币"
DEFAULT_NOTE = "手工维护：price_avg_30d = 近 30 天成交均价，非实时价"


def build_skeleton(
    ammo_records: Sequence[Mapping[str, Any]],
    existing: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """按官方弹药目录重建价格表，保留已填价格。"""
    old = existing or {}
    old_rows: Dict[str, Mapping[str, Any]] = {}
    for row in old.get("ammo") or []:
        if isinstance(row, dict) and row.get("ammo_item_id"):
            old_rows[str(row["ammo_item_id"])] = row

    rows: List[Dict[str, Any]] = []
    for record in ammo_records:
        item_id = str(record.get("ammo_item_id") or "")
        if not item_id:
            continue
        previous = old_rows.get(item_id) or {}
        rows.append(
            {
                "ammo_item_id": item_id,
                "caliber": str(record.get("caliber") or ""),
                "name": str(record.get("name") or ""),
                "penetration_level": record.get("penetration_level"),
                "price_avg_30d": previous.get("price_avg_30d"),
            }
        )

    return {
        "schema": SCHEMA,
        "currency": str(old.get("currency") or CURRENCY),
        "window": dict(old.get("window") or {}),
        "updated_at": str(old.get("updated_at") or ""),
        "note": str(old.get("note") or DEFAULT_NOTE),
        "ammo": rows,
    }


def _load_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成弹药均价表骨架")
    parser.add_argument("--check", action="store_true", help="只报告差异，不写盘")
    args = parser.parse_args(argv)

    catalogue = _load_json(AMMO_CATALOGUE) or {}
    existing = _load_json(PRICE_TABLE)
    skeleton = build_skeleton(catalogue.get("ammo") or [], existing)

    filled = sum(1 for r in skeleton["ammo"] if r["price_avg_30d"] is not None)
    total = len(skeleton["ammo"])

    if args.check:
        same = existing is not None and existing.get("ammo") == skeleton["ammo"]
        print(f"弹药 {total} 款，已填价 {filled} 款；与现有表{'一致' if same else '有差异'}")
        return 0 if same else 1

    os.makedirs(os.path.dirname(PRICE_TABLE), exist_ok=True)
    with open(PRICE_TABLE, "w", encoding="utf-8") as fh:
        json.dump(skeleton, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"已写出 {PRICE_TABLE}：弹药 {total} 款，已填价 {filled} 款")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过，并生成真实价格表**

Run: `python -m pytest tests/test_ammo_price_skeleton.py -q`
Expected: PASS（5 passed）

Run: `python tools/build_ammo_price_skeleton.py`
Expected: 输出 `已写出 .../ammo_prices.json：弹药 114 款，已填价 0 款`

Run: `python tools/build_ammo_price_skeleton.py --check`
Expected: 输出 `与现有表一致`（退出码 0，证明幂等）

- [ ] **Step 5: Commit**

```bash
git add tools/build_ammo_price_skeleton.py tests/test_ammo_price_skeleton.py data/reference/ammo_prices.json
git commit -m "feat(tools): 新增弹药均价表骨架脚本（幂等，保护已填价格）"
```

---

## Task 7: 渲染层三列

**Files:**
- Modify: `src/renderers/ttk_report.py`（`_fmt_money` 新增；`render_band_table`、`render_readme`、`render_scenario_markdown` 修改）
- Test: `tests/test_renderers.py`（追加）

**Interfaces:**
- Consumes: payload 的 `weapons[].ammo`、`bands[].kill_cost`、`ammo_price_meta`（Task 5）
- Produces: `_fmt_money(value: Any, currency: str = "哈夫币") -> str`；表头含「弹药 / 单发价 / 击杀成本」三列

- [ ] **Step 1: 写失败测试**

在 `tests/test_renderers.py` 追加：

```python
PAYLOAD_WITH_COST = {
    **PAYLOAD,
    "ammo_price_meta": {
        "currency": "哈夫币",
        "window": {"from": "2026-08-23", "to": "2026-09-21", "days": 30},
        "updated_at": "2026-09-21",
        "available": True,
    },
    "weapons": [
        {
            **PAYLOAD["weapons"][0],
            "ammo": {"ammo_item_id": "37260500001", "name": "AP SX",
                     "caliber": "4.6x30mm", "price_avg_30d": 4579},
            "bands": {
                "贴脸": {"rank": 1, "tier": "T0", "mean_ms": 286.92, "worst_ms": 286.92,
                         "best_ms": 286.92, "mean_expected_shots": 5.543, "kill_cost": 25381},
            },
        }
    ],
}


def test_band_table_has_three_new_columns():
    table = render_band_table(PAYLOAD_WITH_COST, "贴脸", PART_NAMES)
    header = table.splitlines()[0]
    assert "弹药" in header
    assert "单发价" in header
    assert "击杀成本" in header
    # 位置：紧跟在「期望击杀发数@0m」之后
    assert header.index("期望击杀发数@0m") < header.index("弹药") < header.index("单发价") < header.index("击杀成本")


def test_band_table_renders_ammo_and_money():
    table = render_band_table(PAYLOAD_WITH_COST, "贴脸", PART_NAMES)
    assert "4.6x30mm AP SX" in table
    assert "4,579 哈夫币" in table
    assert "25,381 哈夫币" in table


def test_missing_price_renders_dash():
    payload = {
        **PAYLOAD_WITH_COST,
        "ammo_price_meta": {**PAYLOAD_WITH_COST["ammo_price_meta"], "available": False},
        "weapons": [
            {**PAYLOAD_WITH_COST["weapons"][0],
             "ammo": {"ammo_item_id": "x", "name": "AP SX", "caliber": "4.6x30mm",
                      "price_avg_30d": None},
             "bands": {"贴脸": {"rank": 1, "tier": "T0", "mean_ms": 286.92, "worst_ms": 286.92,
                                "best_ms": 286.92, "mean_expected_shots": 5.543,
                                "kill_cost": None}}}
        ],
    }
    table = render_band_table(payload, "贴脸", PART_NAMES)
    assert "AP SX" in table
    assert "哈夫币" not in table  # 缺价时不得出现金额
    assert "—" in table


def test_empty_caliber_renders_name_only():
    payload = {
        **PAYLOAD_WITH_COST,
        "weapons": [
            {**PAYLOAD_WITH_COST["weapons"][0],
             "ammo": {"ammo_item_id": "y", "name": "碳纤维穿甲箭矢", "caliber": "",
                      "price_avg_30d": 1000},
             "bands": {"贴脸": {"rank": 1, "tier": "T0", "mean_ms": 286.92, "worst_ms": 286.92,
                                "best_ms": 286.92, "mean_expected_shots": 5.0, "kill_cost": 5000}}}
        ],
    }
    table = render_band_table(payload, "贴脸", PART_NAMES)
    assert "碳纤维穿甲箭矢" in table
    assert "哈夫币" in table  # 有价时金额正常出现


def test_ammo_label_skips_empty_caliber():
    """直接单测格式化函数：空口径只输出型号，无前导/尾随空格。

    不在表格层断言前导空格——表格单元格会被 strip，那类缺陷在那里测不出来（恒真断言）。
    """
    from src.renderers.ttk_report import _ammo_label

    assert _ammo_label({"caliber": "4.6x30mm", "name": "AP SX"}) == "4.6x30mm AP SX"
    assert _ammo_label({"caliber": "", "name": "碳纤维穿甲箭矢"}) == "碳纤维穿甲箭矢"
    assert _ammo_label({"caliber": None, "name": "碳纤维穿甲箭矢"}) == "碳纤维穿甲箭矢"
    assert _ammo_label({}) == "—"


def test_legacy_payload_without_new_keys_does_not_raise():
    """旧 payload（无 ammo / kill_cost / meta）必须仍能渲染。"""
    table = render_band_table(PAYLOAD, "贴脸", PART_NAMES)   # 原 PAYLOAD 未含新键
    assert "| 1 |" in table
    assert "—" in table


def test_fmt_money_groups_thousands():
    from src.renderers.ttk_report import _fmt_money

    assert _fmt_money(4579) == "4,579 哈夫币"
    assert _fmt_money(25381) == "25,381 哈夫币"
    assert _fmt_money(999) == "999 哈夫币"
    assert _fmt_money(None) == "—"


def test_readme_notes_price_source():
    md = render_readme(
        PAYLOAD_WITH_COST,
        SCENARIO_META,
        {"source": {"name": "dfttk-v3", "dataset_version": "x"}},
        PART_NAMES,
    )
    assert "2026-08-23" in md and "2026-09-21" in md
    assert "手工维护" in md
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_renderers.py -q`
Expected: FAIL — `ImportError: cannot import name '_fmt_money'` / 表头断言失败

- [ ] **Step 3: 写最小实现**

在 `src/renderers/ttk_report.py` 中：

(a) 在 `_fmt` 之后新增金额格式化：

```python
def _fmt_money(value: Any, currency: str = "哈夫币") -> str:
    """整数金额千分位格式化；``None`` 渲染为 ``—``（缺价不猜测）。"""
    if value is None:
        return "—"
    try:
        return f"{int(value):,} {currency}"
    except (TypeError, ValueError):
        return "—"


def _ammo_label(ammo: Mapping[str, Any]) -> str:
    """弹药展示名：``口径 + 型号``；口径为空时只输出型号。"""
    caliber = str(ammo.get("caliber") or "").strip()
    name = str(ammo.get("name") or "").strip()
    return f"{caliber} {name}".strip() or "—"
```

(b) `render_band_table` 表头改为：

```python
    lines = [
        "| # | 层级 | 武器 | 平均 TTK | 最差 TTK | 期望击杀发数@0m | 弹药 | 单发价 | 击杀成本 | 射速 | 优势射程 | 最优配装 |",
        "| :-- | :-- | :-- | --: | --: | --: | :-- | --: | --: | --: | --: | :-- |",
    ]
```

(c) `render_band_table` 的行模板改为（新增三个 `{}` 占位并由 `.format` 传入）：

```python
        ammo = w.get("ammo") or {}
        currency = ((payload.get("ammo_price_meta") or {}).get("currency")) or "哈夫币"
        lines.append(
            "| {rank} | {tier} | {name} | {mean} | {worst} | {shots} | {ammo} | {price} | {cost} | {rpm} | {rng} | {loadout} |".format(
                rank=band_data["rank"],
                tier=_tier_badge(band_data.get("tier", "")),
                name=name,
                mean=_fmt(band_data["mean_ms"], 1, " ms"),
                worst=_fmt(band_data["worst_ms"], 1, " ms"),
                shots=_fmt(w.get("expected_shots_0m"), 2, " 发"),
                ammo=_ammo_label(ammo),
                price=_fmt_money(ammo.get("price_avg_30d"), currency),
                cost=_fmt_money(band_data.get("kill_cost"), currency),
                rpm=_fmt(w.get("rpm"), 0),
                rng=_fmt(w.get("effective_range_m"), 1, " m"),
                loadout=loadout_text(w.get("loadout") or {}, part_names),
            )
        )
```

(d) 新增时效标注函数，并在 `render_readme` / `render_scenario_markdown` 的「数据说明」段调用：

```python
def _price_note(payload: Mapping[str, Any]) -> Optional[str]:
    """价格数据说明行；未配置价格表时返回提示缺失的文案。"""
    meta = payload.get("ammo_price_meta")
    if not meta:
        return None
    if not meta.get("available"):
        return "- 价格数据：未配置（data/reference/ammo_prices.json 缺失或为空），成本列显示 —"
    window = meta.get("window") or {}
    span = f"（{window.get('from')} ~ {window.get('to')}）" if window.get("from") else ""
    return f"- 价格数据：手工维护 30 天均价{span}，截至 {meta.get('updated_at') or '未知'}"
```

在 `render_scenario_markdown` 的数据说明段（`- 开镜时间、初速、后坐/散布等维度不计入 TTK` 之后）插入：

```python
    note = _price_note(payload)
    if note:
        lines.append(note)
```

在 `render_readme` 的「方法学与可信度」段末尾（`详细设计见` 之前）插入：

```python
    note = _price_note(main_payload)
    if note:
        lines.append(note)
        lines.append("")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_renderers.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/renderers/ttk_report.py tests/test_renderers.py
git commit -m "feat(renderers): 榜单新增弹药/单发价/击杀成本三列与价格时效标注"
```

---

## Task 8: 管线注入与端到端验证

**Files:**
- Modify: `src/pipeline.py`（`run_pipeline`）
- Test: `tests/test_pipeline.py`（追加）
- Regenerate: `README.md`、`docs/tierlist/*.md`、`docs/gunsmith-guide.md`、`data/tierlist/*.json`

**Interfaces:**
- Consumes: `load_ammo_prices`（Task 1）、`to_export(..., price_table=...)`（Task 5）、`rank_weapons_for_scenario(..., price_table=...)`（Task 4）
- Produces: `run_pipeline(...)` 的 payload 含 `ammo_price_meta`；`result` 字典新增 `ammo_price_table`（`AmmoPriceTable`）

- [ ] **Step 1: 写失败测试**

在 `tests/test_pipeline.py` 追加：

```python
def test_pipeline_payload_includes_ammo_price_meta(result):
    payload = result["payloads"][DEFAULT_SCENARIOS[0]]
    assert "ammo_price_meta" in payload
    assert set(payload["ammo_price_meta"]) == {"currency", "window", "updated_at", "available"}
    for weapon in payload["weapons"]:
        assert "ammo" in weapon
        assert set(weapon["ammo"]) == {"ammo_item_id", "name", "caliber", "price_avg_30d"}
        for band, data in weapon["bands"].items():
            assert "mean_expected_shots" in data
            assert "kill_cost" in data


def test_pipeline_injects_price_table(result):
    """守护本任务的核心改动：管线必须真的加载并透传了价格表。

    没有这条断言时，即使 `run_pipeline` 完全不加载 `price_table` 也能通过
    ——因为 payload 里的价格字段由 `to_export` 无条件输出。
    """
    assert "ammo_price_table" in result
    assert result["ammo_price_table"].currency == "哈夫币"


def test_pipeline_combat_fields_present_and_sane(result):
    """战斗字段齐备且自洽。

    本测试**不**声称「零漂移」——那由重新生成后的 diff 核验（见 Step 5）；
    这里只保证字段存在且内部自洽，故按实际能力命名。
    """
    payload = result["payloads"][DEFAULT_SCENARIOS[0]]
    for weapon in payload["weapons"]:
        assert weapon["overall_mean_ms"] > 0
        for data in weapon["bands"].values():
            assert data["mean_ms"] > 0
            assert data["worst_ms"] >= data["mean_ms"] - 1e-9
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline.py -q`
Expected: FAIL — `KeyError: 'ammo_price_meta'`

- [ ] **Step 3: 写最小实现**

在 `src/pipeline.py` 中：

(a) import 增加：

```python
from src.engine.ammo_pricing import load_ammo_prices
```

(b) 新增常量（紧随 `MAIN_SCENARIO` 之后）：

```python
#: 手工维护的弹药 30 天均价表（非官方数据，与 data/game/* 物理隔离）
AMMO_PRICE_TABLE = "data/reference/ammo_prices.json"
```

(c) `run_pipeline` 中，加载价格表（在 `game_data = load_game_data(...)` 之后）：

```python
    game_data = load_game_data(os.path.join(output_dir, DEFAULT_DATA_DIR))
    price_table = load_ammo_prices(os.path.join(output_dir, AMMO_PRICE_TABLE))
```

(d) 传给 `rank_weapons_for_scenario` 与 `to_export`：

```python
        rankings, thresholds, excluded = tiering.rank_weapons_for_scenario(
            game_data, sid, solver=solver, beam_width=beam_width, top_k=top_k,
            profile_keys=keys, price_table=price_table,
        )
        payload = tiering.to_export(rankings, thresholds, sid, excluded, price_table=price_table)
```

(e) 返回字典追加：

```python
    return {
        "scenarios": targets,
        "weapon_count": len(keys),
        "payloads": payloads,
        "files_written": files_written,
        "ammo_price_table": price_table,
    }
```

- [ ] **Step 4: 跑全量测试确认通过**

Run: `python -m pytest tests/ -q`
Expected: PASS（全部通过，含既有 66 项）

- [ ] **Step 5: 重新生成榜单并核对**

Run: `python -m src.pipeline`

然后核对（用 git 判断战斗数值是否零漂移）：

```bash
git diff --stat data/tierlist/
```

Expected：`data/tierlist/*.json` 仅新增 `ammo` / `ammo_price_meta` / `mean_expected_shots` / `kill_cost` 字段；
`mean_ms` / `worst_ms` / `rank` / `tier` / `expected_shots_0m` 数值**逐位不变**（用 `git diff` 逐行确认）。

- [ ] **Step 6: Commit**

```bash
git add src/pipeline.py tests/test_pipeline.py README.md docs/tierlist data/tierlist
git commit -m "feat(pipeline): 注入弹药均价表并重新生成榜单"
```

---

## 自检结果

**1. Spec 覆盖检查**

| Spec 节 | 覆盖任务 |
| :-- | :-- |
| §2 口径定义 | Task 3（`compute_kill_cost`）、Task 4（用带内均值） |
| §3.1 数据层 schema | Task 5（骨架生成）、Task 1（加载） |
| §3.2 骨架脚本幂等 | Task 6 |
| §4.1 `ammo_pricing` 模块 | Task 1 |
| §4.2 `band_summary` 扩展 | Task 2 |
| §5.1 装配 | Task 4 |
| §5.2 `to_export` | Task 5 |
| §5.3 `pipeline` 注入 | Task 8 |
| §6 渲染层三列 + 千分位 + 缺键降级 + 时效标注 | Task 7 |
| §7 边界处理 | Task 1（缺文件/非法值）、Task 4（缺价）、Task 7（缺键降级/空口径） |
| §8 测试要求 | 每个任务的 Step 1 |

无遗漏。

**2. 占位符扫描**：已清除。Task 7 Step 3(c) 中一段带 `if False` 的示意写法已在该步骤内显式标注为"最终代码就是…"，执行时按标注写。

**3. 类型一致性**：`AmmoPriceTable.price_for(str) -> Optional[int]`、`compute_kill_cost(Optional[float], Optional[int]) -> Optional[int]`、`BandResult.mean_expected_shots: float` / `kill_cost: Optional[int]`、`GunRanking.ammo_price_avg_30d: Optional[int]` — 在 Task 1/3/4/5/7 中引用一致。

---

## 执行提示

- 每个 Task 结束后跑 `python -m pytest tests/ -q`，确保不破坏既有测试。
- Task 8 的榜单重新生成会改动 `README.md` 与 `docs/`，属预期产物更新。
- 价格表初始 `price_avg_30d` 全为 `null`；填价后重跑 Task 8 Step 5 即可看到成本列。
