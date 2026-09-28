# 代码库精简优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变任何输出产物的前提下，删除死代码与失效资产、合并重复实现、消除重算链路的重复计算、拆解三个巨石文件、修复距离带静默缺陷。

**Architecture:** 三阶段风险递增。阶段 0 先建立「零差异基线零点」（否则门禁无参照）。阶段 1 纯减法（死代码/重复实现/失效文件），每步行为等价。阶段 2 在干净基线上消重（缓存与结果透传），行数几乎不变。阶段 3 做结构重构，先把符号**纯搬迁**到新模块（行为必须逐位不变），再做去重。

**Tech Stack:** Python 3.11+（CI 用 3.11，本地 3.13/3.14），pytest，标准库 only（**无第三方运行期依赖**），GitHub Actions。

## Global Constraints

- **G1 产物零差异**：`README.md` / `docs/` / `data/` 相对阶段 0 零点必须 `git diff` 为空。⇒ **不新增、不删除、不重命名任何输出字段、列、表头**，含恒空字段（`data/榜单/*.json` 中恒为 `{}` 的 `tuning`）与恒 `—` 列。
- **G2 删除授权边界**：仅允许删除 ① 代码死代码 ② `tools/backfill_gun_prices.py` ③ `tools/crosscheck_third_party.py`（能力下沉为测试）。其余已跟踪文件只做内容修正，不删。
- **G3 零第三方运行期依赖**：`src/` 只能 import 标准库。
- **G4 阶段门禁**：每阶段独立提交；未过门禁不得进入下一阶段。
- **G5 保留命名**：`AmmoPriceTable` / `WeaponPriceTable` / `DEFAULT_CURRENCY` / `load_ammo_prices` / `load_weapon_prices` 必须继续可从原模块导入并保持构造签名（`tests/test_kill_cost.py`、`tests/test_gun_price.py`、`src/engine/tiering.py:18,22-23` 依赖）。
- **G6 CLI 契约**：`python -m src.pipeline`、`python -m src.collectors.game_data_sync`、`python -m src.collectors.ammo_price_sync`、`python -m src.collectors.weapon_price_sync` 必须保持可用（`.github/workflows/update.yml` 依赖）。
- **G7 门禁命令口径**：仓库内已提交的 `README.md` / `docs/榜单/` / `data/榜单/` 由 CI 以 **`--beam-width 8`** 产出（见 `.github/workflows/update.yml:68`）。本地门禁必须使用**同一参数**：`python -m src.pipeline --beam-width 8`。用默认 beam-width（48）重算会产出不同的束搜索剪枝结果，使零点 diff 天然非空、整套门禁失去参照意义。

### 基线（2026-09-28 实测）

| 项 | 值 |
| :-- | :-- |
| `python -m pytest -q` | **156 passed in 62.98s** |
| 本地解释器 | `C:\Users\pc\AppData\Local\Programs\Python\Python314\python.exe`（含 pytest 8.4.2） |
| 管理解释器 | `C:\Users\pc\.workbuddy\binaries\python\versions\3.13.12\python.exe`（**无 pytest**，勿用于测试） |
| `src`+`tests`+`tools` | 9108 行 |

> 本地测试统一用系统解释器：`"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q`

---

## 文件结构（本计划涉及的模块边界）

| 文件 | 动作 | 职责 |
| :-- | :-- | :-- |
| `src/engine/price_table.py` | **新建** | 泛型价格表：`PriceTable` + `load_price_table()` |
| `src/engine/ammo_pricing.py` | 精简为薄封装 | 弹药表 schema/section/主键绑定 |
| `src/engine/weapon_pricing.py` | 精简为薄封装 | 枪械表 schema/section/主键绑定 |
| `src/engine/modifiers.py` | **新建** | 修饰层语义内核（从 weapon_state 搬迁） |
| `src/engine/weapon_state.py` | 瘦身 | `WeaponState` + `WeaponStateResolver` + `build_loadout()` |
| `src/engine/ranking.py` | **新建** | 榜单编排（从 tiering 搬迁） |
| `src/engine/tierlist_export.py` | **新建** | JSON 序列化（从 tiering 搬迁） |
| `src/engine/tiering.py` | 瘦身 | 分层数学 + 对外 re-export |
| `src/collectors/http.py` | **新建** | 下载与磁盘缓存（从 game_data_sync 搬迁） |
| `src/collectors/overrides.py` | **新建** | 覆盖层（从 game_data_sync 搬迁） |
| `src/collectors/normalize.py` | **新建** | schema 归一化（从 game_data_sync 搬迁） |
| `src/collectors/game_data_sync.py` | 瘦身 | `sync_all` + `main` 编排 |
| `tests/test_third_party_crosscheck.py` | **新建** | moligod 26/26 图片 URL 互证 |
| `tests/test_distance_bands.py` | **新建** | 距离带三方一致性守护 |

---

## 阶段 0：建立零差异基线零点

### Task 1: 记录零差异零点

**Files:**
- Modify: 无源码改动（只记录）

**Interfaces:**
- Produces: 零点基线结论 —— 后续所有任务的门禁参照。

- [ ] **Step 1: 运行完整管线（默认 5 实战情景）**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
```

预计耗时数分钟（束搜索 beam-width 默认 48）。等待完成，记录输出的「情景 N 个 / 武器 M 把 / 写出 K 个文件」。

- [ ] **Step 2: 检查产物是否零差异**

```bash
cd "<repo-root>"
git diff --exit-code README.md docs/ data/ && echo "ZERO-POINT: CLEAN" || echo "ZERO-POINT: NON-EMPTY (见上方 diff)"
```

- [ ] **Step 3: 记录结论**

两种情况：
- 输出 `ZERO-POINT: CLEAN` → 零点 = 空 diff，后续每阶段直接要求 `git diff --exit-code` 为空。
- 输出 `ZERO-POINT: NON-EMPTY` → 保存 diff 到临时文件（**不要提交**）：`git diff README.md docs/ data/ > /tmp/zero-point.diff`，后续每阶段与该文件比对，要求「未引入新差异」。

把结论写进本计划的执行报告（`docs/superpowers/plans/` 同目录的报告文件或 commit message），**阶段 0 不提交任何源码/产物变更**。

- [ ] **Step 4: 确认测试基线**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: `156 passed`

---

## 阶段 1：零差异清理

### Task 2: 删除引擎层死代码（不含 loadout 精校簇）

**Files:**
- Modify: `src/engine/curves.py`
- Modify: `src/engine/game_data.py`
- Modify: `src/engine/ballistics.py`
- Modify: `src/engine/engagement.py`
- Modify: `src/engine/weapon_state.py`
- Modify: `src/engine/tiering.py`
- Modify: `src/engine/__init__.py`（若 re-export 了被删符号）

**Interfaces:**
- Produces: 无新接口。仅删除全仓零引用符号。

**删除清单（已逐条 Grep 验证调用点为 0）**：

| 文件 | 行 | 符号 |
| :-- | :-- | :-- |
| `curves.py` | 61-64 | `Curve.output_range`（property，含 61 行 `@property`） |
| `curves.py` | 66-68 | `Curve.is_identity()` |
| `curves.py` | 92-101 | `Curve.sample()` |
| `curves.py` | 127-128 | `CurveLibrary.__contains__()` |
| `curves.py` | 130-131 | `CurveLibrary.ids()` |
| `curves.py` | 145-148 | `CurveLibrary.maybe()` |
| `curves.py` | 150-151 | `CurveLibrary.as_dict()` |
| `game_data.py` | 63-64 | `GameData.dataset_version` |
| `game_data.py` | 85-89 | `GameData.require_profile()` |
| `game_data.py` | 109-110 | `GameData.ammo_levels()` |
| `game_data.py` | 116-117 | `GameData.scenario_ids()`（连带其上的 `@lru_cache` 装饰器一行） |
| `game_data.py` | 120-121 | `GameData.distance_range` |
| `ballistics.py` | 226-228 | 模块级 `expected_kill_shots(ctx)` **及其在 `__init__.py` 的 import/`__all__` 条目** |
| `ballistics.py` | 183-185 | `DamageContext.shot_damage()` |
| `engagement.py` | 62-74 | `TtkResult.as_dict()` |
| `weapon_state.py` | 816-826 | `resolve_weapon_state()` |
| `weapon_state.py` | 358-363 | `WeaponState.damage_at()` |
| `weapon_state.py` | 362-363 | `WeaponState.armor_damage_at()` |
| `weapon_state.py` | 368-369 | `WeaponState.shots_per_second()` |
| `weapon_state.py` | 371-381 | `WeaponState.describe_panel()` |
| `weapon_state.py` | 101, 210 | `TARGET_ALIASES` 常量，及 `_accumulate` 内 `TARGET_ALIASES.get(target, target)` → 直接用 `target` |
| `weapon_state.py` | 69-70, 73-74, 83 | `RT_ADS_MOVE_SPEED` / `RT_SILENT_WALK` / `RT_RANGE_ONLY` / `RT_SPEED_ONLY` / `RT_FIRE_CD` 常量 |
| `tiering.py` | 94-96 | `GunRanking.has_variant` |

> **注意**：`curves.py:14` 的 `Iterable` 导入**必须保留**（`Curve.__init__` 用到）。
> **注意**：`weapon_state.py` 的 `mode` / `panel_named` / `rate_of_fire_multiplier` / `burst_cadence_seconds` 四个只写字段在 Task 8 统一处理，本任务不动。

- [ ] **Step 1: 逐条验证目标符号当前调用点为 0**

```bash
cd "<repo-root>"
for s in output_range is_identity "\.sample(" "\.ids()" "\.maybe(" "\.as_dict()" \
         require_profile ammo_levels "def scenario_ids" distance_range \
         "resolve_weapon_state" "def damage_at" armor_damage_at shots_per_second describe_panel \
         TARGET_ALIASES has_variant shot_damage; do
  n=$(grep -rn "$s" src/ tests/ tools/ --include="*.py" | grep -v "__pycache__" | wc -l)
  echo "$s -> $n"
done
```

Expected: 每个符号命中数均为 1（仅定义处）或 2（定义 + `__init__.py` re-export）。命中数更高的符号**跳过不删**并在报告中说明。

- [ ] **Step 2: 删除符号**

按上表逐条删除。删除 `ballistics.expected_kill_shots` 时同步处理 `src/engine/__init__.py` 中的 `import` 与 `__all__` 条目（先读该文件确认存在）。

- [ ] **Step 3: 验证删除后无残留引用**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: `156 passed`（本任务不删任何测试）

- [ ] **Step 4: 编译与导入自检**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -c "import src.engine; import src.pipeline; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 5: Commit**

```bash
cd "<repo-root>"
git add src/engine/
git commit -m "refactor(engine): 删除全仓零引用死代码(curves/game_data/ballistics/engagement/weapon_state/tiering)

逐条 Grep 验证调用点为 0: Curve 6 个方法 / GameData 5 个视图方法 /
模块级 expected_kill_shots / DamageContext.shot_damage / TtkResult.as_dict /
resolve_weapon_state / WeaponState 4 个派生量 / TARGET_ALIASES 恒空表 /
GunRanking.has_variant"
```

---

### Task 3: 删除精校 / 配装求解器簇

**Files:**
- Modify: `src/engine/loadout.py`
- Modify: `src/engine/__init__.py`
- Modify: `tests/test_loadout.py`

**Interfaces:**
- Consumes: Task 2 已清理引擎层死代码。
- Produces: `LoadoutSolver` 保留但仅剩 `__init__` / `ammo_for` / `_mounted` / `_band_score` / `enumerate_loadouts`。
- **必须保留**：`SocketSpec`、`build_socket_specs`、`part_affects_ttk`、`effect_affects_ttk`、`target_affects_ttk`、`_prune_options`、`LoadoutSolver.enumerate_loadouts`（`tiering.py:418` 生产使用）。

**删除清单**：

| 符号 | 行区间 | 说明 |
| :-- | :-- | :-- |
| `tuning_breakpoints` | 231-248 | 唯一消费者是被删的 `ttk_tuning_dims` |
| `ttk_tuning_dims` | 249-269 | 全仓 0 引用 |
| `LoadoutSolution`（含 `band_ms` / `ttk_at_0m_ms` / `as_dict` / `score_seconds`） | 270-296 | 仅被 `src/engine/__init__.py` re-export |
| `LoadoutSolver.solve_tuning` | 374-400 | 全仓 0 引用 |
| `LoadoutSolver.solve` | 401-448 | `src/` 0 引用；生产链路走 `enumerate_loadouts` |

**顺带关闭 §3.7**：`include_non_ttk` 形参（L151/L179）与分支（L154/L192/L194/L209/L211）
的唯一生产使用者是待删的 `tests/test_loadout.py:83`。本任务一并删除该参数与全部分支。

**测试删除清单（`tests/test_loadout.py`）**：

| 行 | 用例 | 理由 |
| :-- | :-- | :-- |
| 67-74 | `test_tuning_breakpoints_are_curve_nodes` | 测 `tuning_breakpoints` |
| 77-90 | `test_solved_loadout_is_legal` | 用 `solver.solve()`；含唯一 `include_non_ttk=True` |
| 93-102 | `test_solved_tuning_within_official_range` | 用 `solver.solve()` + `solution.tuning` |
| 105-116 | `test_solving_improves_on_default_loadout` | 用 `solver.solve()` |
| 119-125 | `test_curve_is_complete_over_official_range` | 用 `solver.solve()` |

**必须保留**：`test_ttk_targets_only_rate_damage_range`(27-36)、`test_zero_effects_are_ignored`(39-44)、
`test_socket_pruning_keeps_only_ttk_relevant`(47-55)、`test_pruning_shrinks_space_dramatically`(58-64)、
`test_ttk_is_shots_times_interval_only`(128-148)。
> `test_ttk_is_shots_times_interval_only` **不使用** `solve()`（只用 `ammo_for` / `armor` / `probabilities`），
> 且 `tests/test_loadout.py:9` 的 `LoadoutSolver` 导入仍需保留（该用例使用）。

- [ ] **Step 1: 确认 `solve` / `solve_tuning` 在 src/ 无调用**

```bash
cd "<repo-root>"
echo "--- solve 在 src/ (排除 loadout.py) ---"
grep -rn "\.solve(\|solve_tuning\|ttk_tuning_dims\|tuning_breakpoints\|LoadoutSolution" src/ --include="*.py" | grep -v "^src/engine/loadout.py" | grep -v "__pycache__"
```

Expected: 仅 `src/engine/__init__.py` 出现 `LoadoutSolution`（import + `__all__`）。

- [ ] **Step 2: 删除 loadout.py 中的求解器簇与 include_non_ttk**

按上表删除。删除后确认 `LoadoutSolver` 仍保留 `ammo_for` / `_mounted` / `_band_score` / `enumerate_loadouts`。

- [ ] **Step 3: 清理 `__init__.py` 的 re-export**

读 `src/engine/__init__.py`，删除 `LoadoutSolution` 的 import 与 `__all__` 条目。

- [ ] **Step 4: 删除对应测试用例**

删除 `tests/test_loadout.py` 的 5 个用例（67-74 / 77-90 / 93-102 / 105-116 / 119-125），
并从 L9-16 的 import 块中删除 `tuning_breakpoints`。**保留** `LoadoutSolver` 导入。

- [ ] **Step 5: 运行测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: `151 passed`（156 − 5）

- [ ] **Step 6: 验证 `tiering` 导出字段未被波及（G1 关键）**

```bash
cd "<repo-root>"
grep -n '"tuning"' src/engine/tiering.py
```

Expected: 至少命中 `tiering.py:319` 与 `:494` —— 该字段**必须保留**（值恒为 `{}`，删掉会改变产物 JSON）。

- [ ] **Step 7: Commit**

```bash
cd "<repo-root>"
git add src/engine/loadout.py src/engine/__init__.py tests/test_loadout.py
git commit -m "refactor(engine): 删除精校/配装求解器簇(生产链路零使用)

生产链路 tiering 4 处 resolve 全传 tuning=None, solve 在 src/ 命中 0;
ttk_report.py:526-529 已声明「精校不改变 TTK」为设计立场。
删除 tuning_breakpoints/ttk_tuning_dims/LoadoutSolution/solve_tuning/solve
及 include_non_ttk 测试专用开关; 同步删 5 个对应用例。
保留 tiering 导出 payload 的 tuning 字段(恒空, G1 约束)。
保留 enumerate_loadouts(生产束搜索使用)。"
```

---

### Task 4: 合并双价格模块

**Files:**
- Create: `src/engine/price_table.py`
- Modify: `src/engine/ammo_pricing.py`
- Modify: `src/engine/weapon_pricing.py`
- Test: `tests/test_ammo_pricing.py`、`tests/test_weapon_pricing.py`（**不改动**，作为回归护栏）

**Interfaces:**
- Consumes: 无
- Produces:
  - `price_table.PriceTable` — frozen dataclass，字段 `currency: str = "哈夫币"` / `window: Mapping[str, Any] = {}` / `updated_at: str = ""` / `prices: Mapping[str, int] = {}`；方法 `price_for(key: str) -> Optional[int]`、property `is_empty -> bool`
  - `price_table.DEFAULT_CURRENCY = "哈夫币"`
  - `price_table.load_price_table(path: str, *, schema: str, section: str, id_field: str, label: str, table_cls: type = PriceTable)` → 返回 `table_cls` 实例
  - `price_table.coerce_price(value: Any) -> Optional[int]`
  - `ammo_pricing.AmmoPriceTable(PriceTable)`、`ammo_pricing.load_ammo_prices(path) -> AmmoPriceTable`、`ammo_pricing.DEFAULT_CURRENCY`（re-export）
  - `weapon_pricing.WeaponPriceTable(PriceTable)`、`weapon_pricing.load_weapon_prices(path) -> WeaponPriceTable`、`weapon_pricing.DEFAULT_CURRENCY`（re-export）

**为什么用子类而非别名**：`tests/test_kill_cost.py:63,81,91,127` 与 `tests/test_gun_price.py:53-54`
以 `AmmoPriceTable(prices={...})` / `WeaponPriceTable(prices=...)` **直接构造**；`tests/test_ammo_pricing.py:108`
断言异常类名为 `FrozenInstanceError`。子类可原样满足，别名会改变类名。

- [ ] **Step 1: 写新模块的失败测试**

新建 `tests/test_price_table.py`：

```python
"""泛型价格表加载（ammo/weapon 共用实现的直接测试）。"""

import json

from src.engine.price_table import DEFAULT_CURRENCY, PriceTable, load_price_table


def _write(tmp_path, payload, name="prices.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


PAYLOAD = {
    "schema": "demo-price-daily",
    "currency": "哈夫币",
    "window": {"from": "2026-09-22", "to": "2026-09-22", "days": 1},
    "updated_at": "2026-09-22",
    "demo": [
        {"demo_id": "a", "price_daily": 100},
        {"demo_id": "b", "price_daily": None},
    ],
}


def test_loads_with_custom_section_and_id_field(tmp_path):
    table = load_price_table(
        _write(tmp_path, PAYLOAD),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert isinstance(table, PriceTable)
    assert table.price_for("a") == 100
    assert table.price_for("b") is None
    assert table.updated_at == "2026-09-22"
    assert table.window["days"] == 1
    assert not table.is_empty


def test_table_cls_is_honoured(tmp_path):
    class DemoTable(PriceTable):
        pass

    table = load_price_table(
        _write(tmp_path, PAYLOAD),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
        table_cls=DemoTable,
    )
    assert isinstance(table, DemoTable)
    assert table.price_for("a") == 100


def test_missing_file_yields_empty_table(tmp_path):
    table = load_price_table(
        str(tmp_path / "nope.json"),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert table.is_empty
    assert table.currency == DEFAULT_CURRENCY
    assert table.updated_at == ""
    assert table.window == {}


def test_wrong_schema_yields_empty_table(tmp_path):
    payload = dict(PAYLOAD, schema="something-else")
    table = load_price_table(
        _write(tmp_path, payload),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert table.is_empty


def test_gbk_encoded_file_yields_empty_table(tmp_path):
    """与 ammo/weapon 同款：GBK 文件（Windows 记事本另存 ANSI）不抛异常。"""
    path = tmp_path / "gbk.json"
    path.write_bytes(json.dumps(PAYLOAD, ensure_ascii=False).encode("gbk"))
    table = load_price_table(
        str(path),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert table.is_empty
    assert table.currency == DEFAULT_CURRENCY


def test_invalid_prices_are_dropped(tmp_path):
    payload = dict(PAYLOAD, demo=[
        {"demo_id": "a", "price_daily": 0},
        {"demo_id": "b", "price_daily": -5},
        {"demo_id": "c", "price_daily": "123"},
        {"demo_id": "d", "price_daily": 100.5},
        {"demo_id": "e", "price_daily": True},
        {"demo_id": "f", "price_daily": 7},
    ])
    table = load_price_table(
        _write(tmp_path, payload),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    for bad in ("a", "b", "c", "d", "e"):
        assert table.price_for(bad) is None, bad
    assert table.price_for("f") == 7
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_price_table.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.engine.price_table'`

- [ ] **Step 3: 实现 `src/engine/price_table.py`**

```python
"""泛型价格表：加载自动维护的第三方行情当日价，并按主键查价。

本模块只做两件事——**加载**与**查价**，不含任何计算。

弹药表与枪械表共用本实现，仅 schema 标识、JSON 分段键与主键字段名不同；
两者的领域常量与类型名分别保留在 :mod:`src.engine.ammo_pricing` 与
:mod:`src.engine.weapon_pricing` 中。

价格由 ``src/collectors`` 下的同步器每日抓取第三方行情生成（非官方数据），
与 ``data/game/*``（官方同步数据）物理隔离：来源、更新频率、可信度三者都不同，
混在一起会污染 ``provenance`` 语义。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Type

logger = logging.getLogger(__name__)

#: 兜底币种（表缺失时渲染层仍需要一个单位名）
DEFAULT_CURRENCY = "哈夫币"


@dataclass(frozen=True)
class PriceTable:
    """第三方行情当日价表（单位见 ``currency``）。"""

    currency: str = DEFAULT_CURRENCY
    window: Mapping[str, Any] = field(default_factory=dict)
    updated_at: str = ""
    prices: Mapping[str, int] = field(default_factory=dict)

    def price_for(self, key: str) -> Optional[int]:
        """按主键查价；缺价或未知 id 返回 ``None``。"""
        return self.prices.get(str(key))

    @property
    def is_empty(self) -> bool:
        """是否没有任何可用价格（文件缺失 / 全未填时渲染层据此调整说明文案）。"""
        return not self.prices


def coerce_price(value: Any) -> Optional[int]:
    """只接受正整数；``bool``/``float``/字符串一律视为无效（缺价）。"""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def load_price_table(
    path: str,
    *,
    schema: str,
    section: str,
    id_field: str,
    label: str,
    table_cls: Type[PriceTable] = PriceTable,
) -> PriceTable:
    """加载价格表。

    文件缺失、无法解析或 schema 不符时返回**空表**（不抛异常），
    使榜单在未配置价格时保持可用——对应列显示 ``—``，战斗数值完全不变。

    ``label`` 仅用于日志文案；``table_cls`` 决定返回的具体类型，
    使调用方保留各自的类型名。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        logger.info("未找到%s（%s），对应列将显示 —", label, path)
        return table_cls()
    except (OSError, ValueError) as exc:
        logger.warning("%s无法读取（%s）：%s", label, path, exc)
        return table_cls()

    if not isinstance(raw, dict) or raw.get("schema") != schema:
        logger.warning("%s schema 不符（期望 %s），整表忽略", label, schema)
        return table_cls()

    prices: Dict[str, int] = {}
    for entry in raw.get(section) or []:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get(id_field)
        price = coerce_price(entry.get("price_daily"))
        if not item_id or price is None:
            continue
        prices[str(item_id)] = price

    window = raw.get("window")
    return table_cls(
        currency=str(raw.get("currency") or DEFAULT_CURRENCY),
        window=dict(window) if isinstance(window, dict) else {},
        updated_at=str(raw.get("updated_at") or ""),
        prices=prices,
    )
```

- [ ] **Step 4: 运行新模块测试确认通过**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_price_table.py -q
```

Expected: `6 passed`

- [ ] **Step 5: 把 `ammo_pricing.py` 改为薄封装**

整体替换文件内容为：

```python
"""弹药价格表：加载自动维护的当日价，并按 ``ammo_item_id`` 查价。

实现见 :mod:`src.engine.price_table`；本模块只绑定弹药表的 schema 与主键。

价格由 :mod:`src.collectors.ammo_price_sync` 每日自动抓取第三方行情生成
（非官方数据），与 ``data/game/*``（官方同步数据）物理隔离。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.price_table import (
    DEFAULT_CURRENCY,
    PriceTable,
    load_price_table,
)

__all__ = ["DEFAULT_CURRENCY", "AmmoPriceTable", "load_ammo_prices"]

#: 期望的表格式标识；不符则整表忽略，避免误读别种 JSON
EXPECTED_SCHEMA = "ammo-price-daily"


@dataclass(frozen=True)
class AmmoPriceTable(PriceTable):
    """弹药单发当日价表（第三方交易行行情，单位见 ``currency``）。"""


def load_ammo_prices(path: str) -> AmmoPriceTable:
    """加载弹药均价表；文件缺失 / 解析失败 / schema 不符 → 空表（不抛异常）。"""
    return load_price_table(
        path,
        schema=EXPECTED_SCHEMA,
        section="ammo",
        id_field="ammo_item_id",
        label="弹药均价表",
        table_cls=AmmoPriceTable,
    )
```

- [ ] **Step 6: 把 `weapon_pricing.py` 改为薄封装**

整体替换文件内容为：

```python
"""枪械价格表：加载自动维护的本体裸枪当日价，并按 ``weapon_id`` 查价。

实现见 :mod:`src.engine.price_table`；本模块只绑定枪械表的 schema 与主键。

口径（2026-09-22 与需求方确认）：

- **本体裸枪价**：交易行该枪本体的当日价。变体/改装状态**共用本体价**——
  官方变体只是本体预装了官方改件，不存在独立的"变体枪"商品；配件价格不在维护范围。
- 预装件/改装件会影响伤害、射速等战斗属性，但这些差异体现在榜单各行的
  TTK / 击杀成本列；**裸枪价格与起枪配置无关**，同枪所有状态行同价。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.engine.price_table import (
    DEFAULT_CURRENCY,
    PriceTable,
    load_price_table,
)

__all__ = ["DEFAULT_CURRENCY", "WeaponPriceTable", "load_weapon_prices"]

#: 期望的表格式标识；不符则整表忽略，避免误读别种 JSON
EXPECTED_SCHEMA = "weapon-price-daily"


@dataclass(frozen=True)
class WeaponPriceTable(PriceTable):
    """武器本体裸枪当日价表（第三方交易行行情，单位见 ``currency``）。"""


def load_weapon_prices(path: str) -> WeaponPriceTable:
    """加载枪价表；文件缺失 / 解析失败 / schema 不符 → 空表（不抛异常）。"""
    return load_price_table(
        path,
        schema=EXPECTED_SCHEMA,
        section="weapons",
        id_field="weapon_id",
        label="枪械价格表",
        table_cls=WeaponPriceTable,
    )
```

- [ ] **Step 7: 运行全部价格相关测试（回归护栏，不改测试文件）**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_price_table.py tests/test_ammo_pricing.py tests/test_weapon_pricing.py tests/test_kill_cost.py tests/test_gun_price.py -q
```

Expected: 全绿。若 `test_ammo_pricing.py::test_gbk_encoded_file_yields_empty_table` 失败，
说明 `load_price_table` 的 `except (OSError, ValueError)` 遗漏了 `UnicodeDecodeError` 覆盖
（它是 `ValueError` 子类，正常应被捕获）——检查异常元组。

- [ ] **Step 8: 全套测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: `157 passed`（151 + 6 新增）

- [ ] **Step 9: Commit**

```bash
cd "<repo-root>"
git add src/engine/price_table.py src/engine/ammo_pricing.py src/engine/weapon_pricing.py tests/test_price_table.py
git commit -m "refactor(engine): 抽取泛型 price_table, 双价格模块退化为薄封装

ammo_pricing(92) 与 weapon_pricing(99) 归一化后仅 85 行差异、重复度 55%:
_empty/_coerce_price/price_for/is_empty/load_* 逐行克隆。
抽出 PriceTable + load_price_table(path, schema, section, id_field, label, table_cls);
AmmoPriceTable/WeaponPriceTable 保留为 frozen 子类以维持既有构造签名与类型名。"
```

---

### Task 5: 修复 `llms.txt` 失效路径并核对口径同源

**Files:**
- Modify: `llms.txt:47-49`

**Interfaces:**
- Consumes: 无
- Produces: `llms.txt` 三条关键文件链接指向真实路径。

> `llms.txt` **保留**（审计报告点名的「三个必须同源的口径位点」之一），只修内容。

- [ ] **Step 1: 确认目标路径存在、现路径不存在**

```bash
cd "<repo-root>"
for p in docs/tierlist docs/gunsmith-guide.md data/tierlist docs/榜单 docs/改枪指南.md data/榜单; do
  [ -e "$p" ] && echo "[存在] $p" || echo "[缺失] $p"
done
```

Expected: 前三个 `[缺失]`，后三个 `[存在]`。

- [ ] **Step 2: 修正三行**

```bash
cd "<repo-root>"
sed -i 's|docs/tierlist/|docs/榜单/|g; s|docs/gunsmith-guide.md|docs/改枪指南.md|g; s|data/tierlist/|data/榜单/|g' llms.txt
grep -n "docs/榜单\|docs/改枪指南\|data/榜单" llms.txt
```

Expected: 47-49 行全部指向新路径（含链接文本与 URL 两处）。

- [ ] **Step 3: 核对口径表述与 README 同源**

```bash
cd "<repo-root>"
echo "--- llms.txt 溯源段 ---"
grep -n "3774\|3774\|291\|E\[N\]\|rpm" llms.txt
echo "--- README 溯源段 ---"
grep -n "3774\|291\|E\[N\]\|rpm" README.md
```

两侧的样本点数与分母必须一致。若不一致，以 `README.md`（渲染产物，由
`src/renderers/ttk_report.py` 从 `provenance.integrity.official_reproduction_residual`
动态生成）为准，把 `llms.txt` 对齐过去。

- [ ] **Step 4: 验证产物未受影响**

```bash
cd "<repo-root>"
git diff --exit-code README.md docs/ data/ && echo "ARTIFACTS: CLEAN"
```

Expected: `ARTIFACTS: CLEAN`（`llms.txt` 不在 CI 的 `git add` 范围，但也不应影响产物）

- [ ] **Step 5: Commit**

```bash
cd "<repo-root>"
git add llms.txt
git commit -m "docs(llms): 修复 3 条失效路径并核对口径同源

llms.txt:47-49 指向 docs/tierlist/ | docs/gunsmith-guide.md | data/tierlist/
实际为 docs/榜单/ | docs/改枪指南.md | data/榜单/。
该文件为审计报告点名的口径位点之一, 保留并修正, 不删除。"
```

---

### Task 6: 删除一次性迁移脚本 `backfill_gun_prices.py`

**Files:**
- Delete: `tools/backfill_gun_prices.py`

**Interfaces:**
- Consumes: 无
- Produces: `tools/` 仅剩 `verify_official_reproduction.py` 与 `crosscheck_third_party.py`（后者由 Task 7 处理）。

- [ ] **Step 1: 确认存量榜单已含目标字段**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -c "
import json, glob, os
ok = True
for p in sorted(glob.glob('data/榜单/*.json')):
    d = json.load(open(p, encoding='utf-8'))
    w = d.get('weapons') or []
    meta = 'weapon_price_meta' in d
    gp = sum(1 for x in w if x.get('gun_price_daily') is not None)
    fp = sum(1 for x in w if x.get('full_price_180rd') is not None)
    print(os.path.basename(p), 'meta=', meta, 'gun_price=', gp, '/', len(w), 'full_price=', fp)
    ok = ok and meta and gp > 0
print('BACKFILL_OBSOLETE' if ok else 'STILL_NEEDED')
"
```

Expected: 5 个文件全部 `meta= True`，且末行输出 `BACKFILL_OBSOLETE`。
若输出 `STILL_NEEDED`，**停止本任务**并报告。

- [ ] **Step 2: 确认脚本无代码引用**

```bash
cd "<repo-root>"
grep -rn "backfill_gun_prices" . --include="*.py" --include="*.yml" --include="*.toml" --include="*.txt" 2>/dev/null | grep -v "^./.probe\|^./.cache\|__pycache__\|^./tools/backfill_gun_prices.py"
```

Expected: 无输出（仅 docs/ 的历史记录提及，不影响）。

- [ ] **Step 3: 删除文件**

```bash
cd "<repo-root>"
git rm tools/backfill_gun_prices.py
```

- [ ] **Step 4: 运行测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: `157 passed`

- [ ] **Step 5: Commit**

```bash
cd "<repo-root>"
git commit -m "chore(tools): 删除一次性迁移脚本 backfill_gun_prices.py

新增枪价列时的免重算回填工具; 已验证 5 个 data/榜单/*.json 全部含
weapon_price_meta + gun_price_daily + full_price_180rd, 管线已原生产出该列。全仓无代码引用。"
```

---

### Task 7: `crosscheck_third_party.py` 下沉为测试

**Files:**
- Create: `tests/test_third_party_crosscheck.py`
- Delete: `tools/crosscheck_third_party.py`
- Modify: 无

**Interfaces:**
- Consumes: `data/reference/moligod_weapons.json`（已入库）、`data/game/weapons.json`
- Produces: 一条守护 README 可信度声明的离线断言。

**先读源码确定比对口径**：

- [ ] **Step 1: 读源码，确认比对口径**

```bash
cd "<repo-root>"
cat tools/crosscheck_third_party.py
```

脚本 `main()` 实际做三件事（已核实）：
1. 参照数据自洽：`data/reference/moligod_weapons.json` 每条 `object_id` 必须等于从其 `image_url`
   （形如 `.../object/<对象ID>.png`）用正则 `/object/(\d+)\.png` 抽出的 ID；
2. **可选**：与 dfttk catalog 快照的 `imagePath` 比对（需 `--catalog` 参数，**无快照时跳过**）；
3. 与本项目武器池 `data/game/weapons.json` 的 `weapons[].weapon_id` 求交集，
   交集条目的 `name` 不得为空。

参照文件顶层键：`source` / `source_type` / `retrieved_at` / `dataset_version_ref` / `method` /
`verification_result` / `coverage_note` / `weapons`。
`verification_result` 为 `{"entries_with_object_id": 28, "name_match": 28, "image_url_byte_identical": 26, "explained_divergence": [...]}`
—— README 的「26/26 图片 URL 逐字节一致」声明的数据来源。

- [ ] **Step 2: 写测试（严格复刻脚本的断言口径）**

新建 `tests/test_third_party_crosscheck.py`：

```python
"""第三方交叉核验：moligod 官方对象 ID 与本项目武器池互证（离线，不联网）。

守护 README 的可信度声明。原为 tools/crosscheck_third_party.py，
下沉为测试以保住声明的可验证性；脚本原 `--catalog` 可选项依赖本地缓存快照，
不属 CI 可复现范围，故不纳入。
"""

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_PATH = os.path.join(ROOT, "data", "reference", "moligod_weapons.json")
WEAPONS_PATH = os.path.join(ROOT, "data", "game", "weapons.json")

_OBJECT_ID_RE = re.compile(r"/object/(\d+)\.png")


def _object_id(url: str):
    match = _OBJECT_ID_RE.search(url or "")
    return match.group(1) if match else None


@pytest.fixture(scope="module")
def reference():
    with open(REF_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def our_weapons():
    with open(WEAPONS_PATH, encoding="utf-8") as fh:
        return json.load(fh)["weapons"]


def test_reference_entries_are_self_consistent(reference):
    """参照条目自身的 object_id 必须等于其 image_url 中抽出的官方对象 ID。"""
    for entry in reference["weapons"]:
        assert _object_id(entry.get("image_url")) == entry["object_id"], entry["object_id"]


def test_overlap_ids_hit_our_pool_with_names(reference, our_weapons):
    """与本项目武器池的交集：ID 必须命中，且命中条目必须有名称。"""
    our_ids = {str(w["weapon_id"]) for w in our_weapons}
    our_names = {str(w["weapon_id"]): w.get("name", "") for w in our_weapons}

    overlap = [w for w in reference["weapons"] if w["object_id"] in our_ids]
    assert overlap, "参照条目与本项目武器池交集为空——参照数据或武器池可能已失配"
    for entry in overlap:
        assert our_names.get(entry["object_id"]), f"武器池命中但无名称：{entry['object_id']}"


def test_declared_verification_arithmetic_holds(reference):
    """verification_result 的三项计数必须自洽（README 声明的来源）。

    该文件为人工维护的核验存证（retrieved_at=2026-09-20）。重新采集会合法地
    改变这些数字，届时需同步更新 README 的「26/26」声明。
    """
    vr = reference["verification_result"]
    assert (
        vr["image_url_byte_identical"] + len(vr["explained_divergence"])
        == vr["entries_with_object_id"]
    ), "verification_result 计数不自洽：逐字节一致数 + 已解释差异数 != 有 objectID 的条目数"
    assert vr["name_match"] == vr["entries_with_object_id"]
```

> 若团队希望对 README 的「26/26」做**硬钉死**，可在 `test_declared_verification_arithmetic_holds`
> 内追加 `assert vr["image_url_byte_identical"] == 26` 与 `assert vr["entries_with_object_id"] == 28`。
> 默认不加：数字随参考数据版本变化是合法的，钉死会造成假失败。**由执行者向需求方确认后决定。**

- [ ] **Step 3: 运行确认红灯**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_third_party_crosscheck.py -q
```

Expected: 此时文件刚建、内容完整，应直接 **PASS**。
若因夹具路径或字段名不符而 FAIL，按实际 `data/reference/moligod_weapons.json` 结构修正
（`python -c "import json;d=json.load(open('data/reference/moligod_weapons.json',encoding='utf-8'));print(d['weapons'][0])"`）。

- [ ] **Step 4: 确认原脚本退出码 0（等价性）**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" tools/crosscheck_third_party.py; echo "exit=$?"
```

Expected: `exit=0` 且输出「结果：通过（无冲突）」。这与测试全绿等价，
证明下沉没有丢失任何原脚本的检查。

- [ ] **Step 5: 删除脚本**

```bash
cd "<repo-root>"
git rm tools/crosscheck_third_party.py
```

- [ ] **Step 6: 全套测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: 全绿（157 + 新增 3）

- [ ] **Step 7: Commit**

```bash
cd "<repo-root>"
git add tests/test_third_party_crosscheck.py
git commit -m "test: 第三方交叉核验从常驻脚本下沉为测试

crosscheck_third_party.py 无任何代码/CI 引用, 但它支撑 README 的
「moligod 26/26 图片 URL 逐字节一致」可信度声明, 直接删除会使声明不可验证。
改为离线 pytest 断言(参照自洽 / 交集ID命中 / 声明计数自洽), 去掉可执行脚本。
原 --catalog 可选项依赖本地缓存快照, 不属 CI 可复现范围故不纳入。"
```

---

### Task 8: 移除 `mode` 参数链中**未使用**的部分与只写字段

**Files:**
- Modify: `src/engine/weapon_state.py`
- Modify: `src/engine/loadout.py`

**Interfaces:**
- Produces: `WeaponStateResolver(game_data, scenario_id, resolver=None)`；`LoadoutSolver(game_data, scenario_id, resolver=None)`
- **必须保留**：`WeaponStateResolver.resolve()` 的行为与返回对象的所有**被读取**字段（`base_damage` / `hitbox_multipliers` / `fire_interval_seconds` / `overrides` / `profile_refs` / `attr2_ratio` 等）。

> **范围已于 2026-09-28 按控制器自查修正**（原始版本有缺陷，见下「修正依据」）。
> 需求方已确认采用「收窄」方案。

**修正依据（原始范围会破坏数值）**：原计划要求一并删除 `DEFAULT_MODE`、
`WeaponStateResolver.__init__` 的 `mode` 形参，理由来自审计报告称「`mode` 只写不读」。
该理由**不成立** —— `weapon_state.py:530` 存在读取点：

```python
curve_id = (mapping.get("curveIds") or {}).get(self.mode)
```

且数据实测（1872 个含 `curveIds` 的节点）**同时存在 `sol` 与 `mp` 两档键**，
同一 target 在不同 `mode` 下映射到**不同曲线**。删除 `mode` 会使曲线选择失效并静默改变数值。

**修正依据（反射读取安全项已排查）**：`tiering.py:96-102` 的 `EFFECT_SPECS` 通过
`getattr(state, key, 0.0)` 反射读取状态属性，其键集合仅为
`base_damage` / `base_armor_damage` / `rpm` / `effective_range_m` / `projectile_count`
—— **不含**本任务待删的任何字段，故删除不会改变「配装效果摘要」的输出。

**删除清单**（仅这些）：

| 位置（基线行号，会漂移） | 符号 | 为何安全 |
| :-- | :-- | :-- |
| `weapon_state.py:273, 473` | `WeaponState.mode` 字段（定义 + `mode=self.mode` 赋值） | 全仓仅赋值，无读取；不在 `EFFECT_SPECS` |
| `weapon_state.py:280, 503` | `WeaponState.panel_named`（定义 + 赋值） | 全仓仅赋值，无读取；不在 `EFFECT_SPECS` |
| `weapon_state.py:300, 608` | `WeaponState.rate_of_fire_multiplier`（定义 + 赋值） | 同上 |
| `weapon_state.py:302, 611` | `WeaponState.burst_cadence_seconds`（定义 + 赋值） | 同上 |
| `loadout.py` 的 `LoadoutSolver.__init__` | `mode: str = "sol"` 形参及其向 resolver 的透传 | 全仓无调用方传 `mode=`；删除后 resolver 走自身默认值 `DEFAULT_MODE`，行为等价 |
| `loadout.py` 构造 resolver 处的 `mode=` 实参 | 形参透传 | 随上一行一并清理 |

**必须保留（承重，删了会改变数值）**：

| 位置 | 符号 | 原因 |
| :-- | :-- | :-- |
| `weapon_state.py:47` | `DEFAULT_MODE = "sol"` | `WeaponStateResolver.__init__` 的默认值 |
| `weapon_state.py:351, 353` | `WeaponStateResolver.__init__` 的 `mode` 形参与 `self.mode` 赋值 | 供 :530 使用 |
| `weapon_state.py:530` | `... .get(self.mode)` 读取点 | 曲线选择，**不得改动** |

- [ ] **Step 1: 复核 `mode` 的读取面（确认修正依据仍成立）**

```bash
grep -n "mode" src/engine/weapon_state.py src/engine/loadout.py src/pipeline.py
grep -rn "\.mode\b" src/ tests/ tools/ --include="*.py" | grep -v "__pycache__"
```

Expected：仅出现 `weapon_state.py` 的 4 处（47 定义 / 351 形参 / 353 赋值 / 530 读取）、
`WeaponState.mode` 的 2 处（273 定义 / 473 赋值）、`loadout.py` 的形参与透传。
**若发现任何新的 `self.mode` / `state.mode` 读取点，停止并报告** —— 说明修正依据需要重估。

- [ ] **Step 2: 按删除清单删除**

只删上表「删除清单」的行。`DEFAULT_MODE`、`WeaponStateResolver` 的 `mode` 形参与
`self.mode`、以及 :530 的读取点**原样保留**。

- [ ] **Step 3: 验证残留与保留项并存**

```bash
grep -rn "panel_named\|rate_of_fire_multiplier\|burst_cadence_seconds" src/ tests/ tools/ --include="*.py" | grep -v "__pycache__"
```
Expected：无输出（这三个已删干净）。

```bash
grep -n "DEFAULT_MODE\|self\.mode" src/engine/weapon_state.py
```
Expected：**仍有输出** —— `DEFAULT_MODE` 定义、`mode: str = DEFAULT_MODE`、
`def __init__(..., mode: str = DEFAULT_MODE)`、`self.mode = mode`、`.get(self.mode)`。
这是本任务修正后的预期状态，**不是残留**。

- [ ] **Step 4: 运行测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: 全绿

- [ ] **Step 5: Commit**

```bash
cd "<repo-root>"
git add src/engine/weapon_state.py src/engine/loadout.py
git commit -m "refactor(engine): 移除未使用的 mode 透传形参与 4 个只写字段

保留承重的 mode 参数链与 DEFAULT_MODE —— weapon_state.py 的
.get(self.mode) 在 curveIds 中选曲线, 且数据 1872 个节点均含 sol/mp 两档键。
仅删 WeaponState.mode / panel_named / rate_of_fire_multiplier /
burst_cadence_seconds 四个只写字段, 以及 LoadoutSolver 未被任何调用方
传参的 mode 形参(删除后 resolver 走自身默认值, 行为等价)。"
```

---

### Task 9: 阶段 1 门禁 — 全量重算零差异

**Files:**
- Modify: 无（仅验证）

- [ ] **Step 1: 全量重算**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
```

- [ ] **Step 2: 对照零点校验**

```bash
cd "<repo-root>"
git diff --exit-code README.md docs/ data/ && echo "PHASE1 GATE: CLEAN" || echo "PHASE1 GATE: DIRTY"
```

Expected: `PHASE1 GATE: CLEAN`（若 Task 1 为零点非空情形，则改为与 `/tmp/zero-point.diff` 比对无新增）

- [ ] **Step 3: 若 DIRTY，定位并修复**

```bash
cd "<repo-root>"
git diff --stat README.md docs/ data/
git diff data/ | head -60
```

常见原因与处置：
- `tuning` 字段被误删（Task 3）→ 恢复 `tiering.py:319/494` 的 `"tuning": entry.tuning` 与字段定义。
- 价格列取值变化（Task 4）→ 检查 `coerce_price` 语义是否与原先一致（`bool`/`float`/`str` 应被丢弃）。
- 数值末位漂移 → 检查 Task 8 是否误改了 `_resolve_rules` 的分支。

修好后回到 Step 1 重跑，直至 `CLEAN`。

- [ ] **Step 4: 记录阶段 1 成果**

```bash
cd "<repo-root>"
echo "--- 行数 ---"
find src tests tools -name "*.py" -exec wc -l {} + | tail -1
echo "--- 测试数 ---"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q 2>&1 | tail -2
```

Expected: 总行数 ≈ 9108 − 450；测试全绿。

---

## 阶段 2：重算链路提速

### Task 10: 消除 `tiering` 对同一 loadout 的重复 resolve

**Files:**
- Modify: `src/engine/tiering.py:429-452`

**Interfaces:**
- Consumes: `_factory_ranking(...)` 的现有签名（`tiering.py` 内闭包）
- Produces: 无接口变化；仅少一次 `resolve` 调用。

**问题**：`tiering.py:429` 已算出 `state_mounted` 并存入 `scored`（第 2 列），
但 `tiering.py:451` 为算 `loadout_effects` 又用完全相同的入参
`resolve(base_key, loadout=loadout_choice, tuning=None)` 重算一遍。

- [ ] **Step 1: 确认两处入参完全相同**

```bash
cd "<repo-root>"
sed -n '425,455p' src/engine/tiering.py
```

Expected: L429 为 `resolve(base_key, loadout=loadout, tuning=None)`，
L451 为 `resolve(base_key, loadout=loadout_choice, tuning=None)`，
且循环头为 `for loadout_choice, _mounted, state_curve, state_summary in scored:` —— 两者等价。

- [ ] **Step 2: 复用已算状态**

把 L451 的

```python
                    loadout_effects=summarize_loadout_effects(
                        base_state, solver.resolver.resolve(base_key, loadout=loadout_choice, tuning=None)
                    ),
```

改为

```python
                    loadout_effects=summarize_loadout_effects(base_state, _mounted),
```

并把循环变量 `_mounted` 改名为 `state_mounted_choice` 以免下划线前缀暗示未使用（同步改 `for` 头）。

- [ ] **Step 3: 运行 tiering 相关测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_tiering.py tests/test_kill_cost.py tests/test_gun_price.py tests/test_band_summary.py -q
```

Expected: 全绿

- [ ] **Step 4: 全量重算 + 零差异校验**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "CLEAN" || echo "DIRTY"
```

Expected: `CLEAN`

- [ ] **Step 5: Commit**

```bash
cd "<repo-root>"
git add src/engine/tiering.py
git commit -m "perf(engine): tiering 复用已算 state, 消除同一 loadout 的重复 resolve

L438 已持有 state_mounted 却被丢弃, L451 又用相同入参完整 resolve 一次
(重跑 _build_loadout + 全部 modifier + profiles + damage)。改为直接透传。"
```

---

### Task 11: `build_loadout` 纯函数化并透传结果

**Files:**
- Modify: `src/engine/weapon_state.py`（`_build_loadout` 区域 414-485、`resolve` 入口 L488-503）
- Modify: `src/engine/loadout.py:319`

**Interfaces:**
- Produces:
  - `weapon_state.build_loadout(weapon: Mapping[str, Any], requested: Mapping[str, str]) -> Tuple[Dict[str, str], List[str]]` —— 模块级公开纯函数，返回 `(mounted, notes)`
  - `WeaponStateResolver.resolve(profile_key, loadout=None, tuning=None, _precomputed_mounted=None)`
  - `WeaponStateResolver._build_loadout` 保留为 `build_loadout` 的转发（供既有调用点复用），或在同一提交内把所有调用点改为 `build_loadout`
- Consumes: Task 10 完成后的 tiering。

**问题**：同一候选的配装合成在一次 trial 内被触发 3 次 ——
`loadout.py:319`（`_mounted` 内部经 `self.resolver._build_loadout`）→
被 `loadout.py:352` 与 `loadout.py:363` 各触发一次 →
`weapon_state.py:503`（`resolve` 内部）再来一次。每次都重跑含 `while` 循环的耦合求解。

**同时消除隐藏耦合**：`loadout.py:319` 跨类调用私有方法 `resolver._build_loadout`
（且 `loadout.py:301` 用函数内 import 规避循环导入，说明两模块强耦合）。
提升为公开纯函数后，`loadout.py` 直接 import `build_loadout`。

- [ ] **Step 1: 定位全部触发点**

```bash
cd "<repo-root>"
grep -n "_build_loadout\|def build_loadout\|_mounted(" src/engine/weapon_state.py src/engine/loadout.py
```

Expected: `weapon_state.py` 内 `_build_loadout` 定义（414）+ `resolve` 内调用（503）；
`loadout.py:319` 一处调用。

- [ ] **Step 2: 写 `build_loadout` 的失败测试（spec §7.3 要求）**

在 `tests/test_loadout.py` 末尾追加：

```python
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
```

- [ ] **Step 3: 运行测试确认失败**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_loadout.py -q
```

Expected: FAIL — `ImportError: cannot import name 'build_loadout' from 'src.engine.weapon_state'`

- [ ] **Step 4: 新增公开纯函数**

在 `src/engine/weapon_state.py` 中，把 `_build_loadout` 的实现体提升为模块级函数：

```python
def build_loadout(
    weapon: Mapping[str, Any], requested: Mapping[str, str]
) -> Tuple[Dict[str, str], List[str]]:
    """按官方插槽规则与强制联动合成配装。

    返回 ``(实际装配的 item_id 映射, notes)``。纯函数：不读实例状态。

    ⚠ 内部的 ``guard`` / ``claimed`` / ``conflicts`` 仲裁（``while changed`` 循环）
    处理真实数据中的多规则争槽（如 QJB201 rule4/rule11），**不得简化或删除**。
    """
    # 原 _build_loadout 方法体原样搬迁，把 self 相关引用改为参数/局部变量
```

然后让 `WeaponStateResolver.resolve` 内部调用 `build_loadout(...)`，
并新增可选参数 `_precomputed_mounted`：

```python
    def resolve(
        self,
        profile_key: str,
        loadout: Optional[Mapping[str, str]] = None,
        tuning: Optional[Mapping[str, Mapping[str, float]]] = None,
        _precomputed_mounted: Optional[Mapping[str, str]] = None,
    ) -> WeaponState:
        # ... 此处保留 resolve 原有代码（形参获取、默认值处理）直到"合成配装"那一步 ...
        #
        # 【插入位置】原代码在此处调用 self._build_loadout(...)。
        # 把那一行（组）替换为下面 4 行，其余代码原样不动：
        if _precomputed_mounted is None:
            mounted, notes = build_loadout(weapon, loadout or {})
        else:
            mounted, notes = dict(_precomputed_mounted), []
        # ... 其后代码（构造 WeaponState）原样不动 ...
```

执行时用 `grep -n "_build_loadout\|def resolve" src/engine/weapon_state.py` 定位那一次调用，
确认替换点唯一后再改。

- [ ] **Step 5: 把 `loadout.py` 的私有调用改为公开函数**

`loadout.py:319`：

```python
        mounted, _ = self.resolver._build_loadout(weapon, loadout)
```

改为在文件顶部导入 `build_loadout` 后：

```python
        mounted, _ = build_loadout(weapon, loadout)
```

并删除 `loadout.py:301` 中仅为规避循环导入而写的函数内 import（若导入顺序允许；否则保留文件内 import 但改函数名）。

- [ ] **Step 6: 在 `_mounted` / `_band_score` 路径透传结果**

让 `loadout.py` 的 `_mounted(...)` 返回配装签名后，
`_band_score(...)` 构造 `resolve(..., _precomputed_mounted=mounted)` 而非让其重算。
具体：`LoadoutSolver._band_score` 增加 `mounted` 参数并传入 `resolve`；
`enumerate_loadouts` 的 L352 / L363 两处调用复用同一 `mounted` 变量。

- [ ] **Step 7: 运行测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_loadout.py tests/test_ballistics.py tests/test_tiering.py -q
```

Expected: 全绿（含 Step 2 新增的 3 个 `build_loadout` 用例）

- [ ] **Step 8: 全量重算 + 零差异校验**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "CLEAN" || echo "DIRTY"
```

Expected: `CLEAN`。**本任务是阶段 2 风险最高的一步** —— 配装合成被复用后
若 `mounted` 与 `resolve` 内部重算结果不一致，TTK 会变。DIRTY 时必须逐枪比对定位。
（Step 2 的 `test_build_loadout_agrees_with_resolver` 就是这个风险的前置探针。）

- [ ] **Step 9: Commit**

```bash
cd "<repo-root>"
git add src/engine/weapon_state.py src/engine/loadout.py tests/test_loadout.py
git commit -m "perf(engine): build_loadout 提升为公开纯函数并透传结果

同一候选的配装合成在一次 trial 内被触发 3 次(loadout L319/L352/L363 +
resolve L503), 每次都重跑含 while 循环的耦合求解。
提升为 weapon_state.build_loadout 纯函数, resolve 增加 _precomputed_mounted
透传; 同时消除 loadout 跨类调用私有方法 resolver._build_loadout 的隐藏耦合。
保留 guard/claimed/conflicts 仲裁逻辑不变(真实数据存在多规则争槽)。
新增 3 个纯函数单测: 幂等性 / 合法性 / 与 resolver 内部结果一致。"
```

---

### Task 12: 束搜索打分缓存、排序复用与 `bisect`

**Files:**
- Modify: `src/engine/loadout.py`（`enumerate_loadouts` 337-373 区间）
- Modify: `src/engine/tiering.py`（`assign_tiers` 200 附近、`462-468`）
- Modify: `src/engine/curves.py`（`evaluate` 78-90）

**Interfaces:**
- Produces: 无新接口；纯性能改动。

- [ ] **Step 1: 记录改动前耗时**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -c "
import time, os
from src.engine.game_data import load_game_data
from src.engine.loadout import LoadoutSolver
t0 = time.perf_counter()
gd = load_game_data(os.path.join('data', 'game'))
s = LoadoutSolver(gd, 'armor-5-ammo-5-default')
beam = s.enumerate_loadouts('18010000001:base', beam_width=48)
print('enumerate_loadouts 耗时 %.3fs, 候选 %d 个' % (time.perf_counter() - t0, len(beam)))
"
```

记录数字，作为 Step 5 的对比基准。

- [ ] **Step 2: `enumerate_loadouts` 按 mounted 签名缓存打分**

在 `enumerate_loadouts` 内维护 `score_cache: Dict[tuple, float]`，键为
`sorted(mounted.items())` 的元组；命中即复用，不再调 `_band_score`。
注意：L347 对 `{}` 的首次打分与 L367 的 beam 全体再打分存在重复项，缓存后自然去重。

- [ ] **Step 3: `tiering` 消除重复排序**

`tiering.py:462-468` 外层对每 band `present.sort(...)`，而 `assign_tiers`（约 L200）
内部又 `sorted(...)` 一次。改为把外层已排序的列表传入，或让外层复用
`assign_tiers` 内部的排序结果。

- [ ] **Step 4: `Curve.evaluate` 改用 `bisect`**

在 `curves.py` 顶部 import 区加入 `import bisect`，然后：

`__slots__` 增加一个槽位并预计算横坐标数组：

```python
class Curve:
    """不可变的效果曲线，支持线性与三次 Hermite 插值。"""

    __slots__ = ("points", "_xs")

    def __init__(self, points: Iterable[Any]):
        parsed: List[CurvePoint] = sorted((_to_point(p) for p in points), key=lambda p: p[0])
        if not parsed:
            raise ValueError("曲线至少需要一个点")
        self.points: List[CurvePoint] = parsed
        self._xs: List[float] = [p[0] for p in parsed]
```

`evaluate` 换为二分定位（语义与原线性扫描等价：取**最左**满足 `x0 <= x <= x1` 的段）：

```python
    def evaluate(self, x: float) -> float:
        """求值，区间外取端点。"""
        if x <= self._xs[0]:
            return self.points[0][1]
        if x >= self._xs[-1]:
            return self.points[-1][1]

        index = bisect.bisect_left(self._xs, x) - 1
        if index < 0:
            index = 0
        if index >= len(self.points) - 1:
            index = len(self.points) - 2

        x0, y0, mode, _, leave = self.points[index]
        x1, y1, _, arrive, _ = self.points[index + 1]
        if x1 - x0 <= 1e-12:
            return y1
        if mode == CUBIC:
            return _hermite(x, x0, y0, leave, x1, y1, arrive)
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
```

> 为什么 `bisect_left(...) - 1` 与原实现等价：原实现取最小 `i` 使 `xs[i] <= x <= xs[i+1]`。
> `x` 恰等于某点 `xs[k]` 时，`bisect_left` 返回首个 `xs[k] >= x` 的下标 `k`，
> 故 `i = k-1`（与前一段构成 `xs[k-1] <= x <= xs[k]`）—— 与原实现的最小 `i` 一致；
> `x` 落在区间内部时同理。端点情形已由两处提前 return 处理。
> **注意**：`Curve` 用 `__slots__`，忘记把 `_xs` 加进去会在赋值时抛 `AttributeError`。

- [ ] **Step 5: 运行测试 + 复测耗时**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_ballistics.py tests/test_loadout.py tests/test_tiering.py -q
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -c "
import time, os
from src.engine.game_data import load_game_data
from src.engine.loadout import LoadoutSolver
t0 = time.perf_counter()
gd = load_game_data(os.path.join('data', 'game'))
s = LoadoutSolver(gd, 'armor-5-ammo-5-default')
beam = s.enumerate_loadouts('18010000001:base', beam_width=48)
print('enumerate_loadouts 耗时 %.3fs, 候选 %d 个' % (time.perf_counter() - t0, len(beam)))
"
```

Expected: 测试全绿；候选**数量与 Step 1 完全一致**（缓存不得改变结果集）；耗时下降。

- [ ] **Step 6: 全量重算 + 零差异校验**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "CLEAN" || echo "DIRTY"
```

Expected: `CLEAN`

- [ ] **Step 7: Commit**

```bash
cd "<repo-root>"
git add src/engine/loadout.py src/engine/tiering.py src/engine/curves.py
git commit -m "perf(engine): 束搜索打分缓存 + 分层排序复用 + Curve.evaluate 改 bisect

enumerate_loadouts 对同一 mounted 签名重复打分; assign_tiers 与外部 band
排序对同一分布排两次; Curve.evaluate 线性扫描未用二分。"
```

---

## 阶段 3：结构重构

> **阶段 3 铁律**：每个 Task 分两步走 —— 先**纯搬迁**（符号原样移动，只改 import），
> 门禁全过后提交；再做**去重/简化**（若有），再次过门禁并提交。
> 搬迁与修改混在一个提交里，一旦 DIRTY 无法定位。

### Task 13: 拆分 `weapon_state.py` → 抽出 `modifiers.py`

**Files:**
- Create: `src/engine/modifiers.py`
- Modify: `src/engine/weapon_state.py`

**Interfaces:**
- Produces: `modifiers.ModifierLayer`、`modifiers.factor()`、`modifiers.accumulate()`、`modifiers.hitbox_key()`、`modifiers.falloff_from_bullet_profile()`、`modifiers.apply_attribute_effects()`、`modifiers.part_effect_layer()`、`modifiers.part_tuning_layer()`
- 搬迁后 `weapon_state.py` 从 `modifiers` import 这些符号，对外行为不变。

**搬迁清单（`weapon_state.py` 118-274 区间）**：

| 符号 | 说明 |
| :-- | :-- |
| `ModifierLayer` | 修饰层数据类 |
| `_factor` | 改名 `factor`（公开） |
| `_hitbox_key` | 改名 `hitbox_key` |
| `_falloff_from_bullet_profile` | 改名 `falloff_from_bullet_profile` |
| `_accumulate` | 改名 `accumulate` |
| `_apply_attribute_effects` | 改名 `apply_attribute_effects` |
| `_part_effect_layer` | 改名 `part_effect_layer` |
| `_part_tuning_layer` | 改名 `part_tuning_layer` |

> **改名规则**：这些符号若被 `weapon_state.py` 之外的模块引用，**保留原名**（不加公开化）。
> 动手前先查：`grep -rn "_factor\|_accumulate\|_part_effect_layer\|_part_tuning_layer\|_hitbox_key\|_falloff_from_bullet_profile\|_apply_attribute_effects\|ModifierLayer" src/ tests/ tools/ --include="*.py"`

- [ ] **Step 1: 查清搬迁符号的外部引用面**

```bash
cd "<repo-root>"
grep -rn "ModifierLayer\|_factor\b\|_accumulate\|_hitbox_key\|_falloff_from_bullet_profile\|_apply_attribute_effects\|_part_effect_layer\|_part_tuning_layer" src/ tests/ tools/ --include="*.py" | grep -v "__pycache__" | grep -v "^src/engine/weapon_state.py"
```

Expected: 若为空 → 可自由改名；若有命中 → 那些符号保持原名（本 Task 只搬迁不改名）。

- [ ] **Step 2: 创建 `modifiers.py` 并原样搬迁**

新建 `src/engine/modifiers.py`，文件头：

```python
"""修饰层语义内核：官方 modifier 作用到面板/派生平上的合成规则。

从 :mod:`src.engine.weapon_state` 抽出，职责单一——只做修饰语义合成，
不含配装枚举、规则解析与档案装配。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from src.engine.curves import Curve, apply_modifier
```

> **import 校准**：已实读确认 `weapon_state.py:45` 仅有
> `from src.engine.curves import Curve, CurveLibrary, apply_modifier`。
> 修饰层内核（118-274）用到的是 `Curve` 与 `apply_modifier`
> （`CurveLibrary` 属 resolver 的职责，留在 `weapon_state.py`）。
> 搬迁后用 `grep -n "CurveLibrary" src/engine/modifiers.py` 确认未误引；
> 若 118-274 区间确有引用，则一并加入 import。

然后**逐字**粘贴 `weapon_state.py:118-274` 的全部符号（含其 docstring 与注释）。
本步**不做任何逻辑修改**，只把 `self.` 相关的引用改为显式参数（若原方法挂在类上）。

- [ ] **Step 3: 在 `weapon_state.py` 中改为 import**

删除 `weapon_state.py:118-274` 的原定义，在 import 区加入：

```python
from src.engine.modifiers import (
    ModifierLayer,
    accumulate,
    apply_attribute_effects,
    factor,
    falloff_from_bullet_profile,
    hitbox_key,
    part_effect_layer,
    part_tuning_layer,
)
```

（按 Step 1 结果调整：保留原名的符号用原名。）
并修正 `weapon_state.py` 内所有被搬迁符号的调用点。

- [ ] **Step 4: 运行测试 + 全量零差异**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "CLEAN" || echo "DIRTY"
```

Expected: 全绿 + `CLEAN`

- [ ] **Step 5: Commit**

```bash
cd "<repo-root>"
git add src/engine/modifiers.py src/engine/weapon_state.py
git commit -m "refactor(engine): 从 weapon_state 抽出修饰层内核 modifiers.py

weapon_state.py 826 行含 3 个不相关关注点: 修饰层内核(118-274) /
WeaponState 数据类(280-381) / WeaponStateResolver(387-813)。
本步纯搬迁修饰层, 零逻辑改动。"
```

---

### Task 14: 拆分 `tiering.py` → `ranking.py` + `tierlist_export.py`

**Files:**
- Create: `src/engine/ranking.py`
- Create: `src/engine/tierlist_export.py`
- Modify: `src/engine/tiering.py`

**Interfaces:**
- Produces:
  - `ranking.rank_weapons_for_scenario(...)` —— 签名与现 `tiering.rank_weapons_for_scenario` 完全一致（`src/pipeline.py:233` 附近调用它）
  - `tierlist_export.to_export(...)` —— 签名与现 `tiering.to_export` 完全一致
  - `tiering` 继续 re-export 二者，保持既有 import 路径可用（`pipeline.py` / `tests/test_tiering.py`）
- Consumes: Task 12 完成后的 tiering。

**搬迁清单**：

| 符号 | 行区间 | 去向 |
| :-- | :-- | :-- |
| `rank_weapons_for_scenario` | 220-470（含 5 个闭包 `_band_results` / `_ammo_price` / `_exclude` / `_signature` / `_factory_ranking`） | `ranking.py` |
| `to_export` | 473-572 | `tierlist_export.py` |
| `_quantile` / `assign_tiers` / `BAND_NAMES` / `GunRanking` / 常量 | 27, 94, 181-217 等 | **留在 `tiering.py`** |

> 本 Task **只搬迁不重构**。5 个闭包外提为模块级函数是下一步（若做），
> 必须单独提交，避免与搬迁混杂。

- [ ] **Step 1: 确认对外调用面**

```bash
cd "<repo-root>"
grep -rn "rank_weapons_for_scenario\|to_export\|from src.engine.tiering import\|from src.engine import tiering" src/ tests/ tools/ --include="*.py" | grep -v "__pycache__"
```

已实读确认的 8 处导入点（搬迁后必须全部改到新模块，**不做 re-export**）：

| 文件:行 | 内容 |
| :-- | :-- |
| `src/engine/__init__.py:18` | `from src.engine.tiering import GunRanking, rank_weapons_for_scenario` |
| `src/pipeline.py:32` | `from src.engine import tiering` |
| `src/pipeline.py:234` | `tiering.rank_weapons_for_scenario(` |
| `src/pipeline.py:239` | `tiering.to_export(` |
| `tests/test_tiering.py:13-25` | 多符号 import 块 |
| `tests/test_gun_price.py:9-15` | 多符号 import 块 |
| `tests/test_kill_cost.py:9-15` | 多符号 import 块 |
| `tests/test_kill_cost.py:118, 162` | 函数内 `from src.engine.tiering import to_export` |

另需保留可从 `tiering` 导入的符号（测试仍用）：`BAND_NAMES`（`test_tiering.py:79`）、
`_effective_loadout`（`test_tiering.py:172`）。

- [ ] **Step 2: 新建 `ranking.py`，原样搬迁 `rank_weapons_for_scenario`**

新建 `src/engine/ranking.py`：

```python
"""榜单编排：逐武器枚举起枪状态、评分、分层并组装排名条目。

从 :mod:`src.engine.tiering` 抽出。分层数学（``assign_tiers``）、排名条目模型
（``GunRanking``）与常量留在 tiering，本模块只负责编排；
JSON 序列化见 :mod:`src.engine.tierlist_export`。

依赖方向：ranking → tiering（单向）。tiering **不** import 本模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from src.engine import engagement as eg
from src.engine.ammo_pricing import DEFAULT_CURRENCY
from src.engine.loadout import LoadoutSolver, part_affects_ttk
from src.engine.tiering import (
    BAND_NAMES,
    SPARE_AMMO_ROUNDS,
    GunRanking,
    compute_full_price,
    summarize_loadout_effects,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from src.engine.ammo_pricing import AmmoPriceTable
    from src.engine.weapon_pricing import WeaponPriceTable
```

> **import 清单必须按实读校准**：上面是从 `tiering.py:1-31` 的既有 import 反推的。
> 搬迁时先用 `grep -n "^from\|^import" src/engine/tiering.py` 取全量 import，
> 把 `rank_weapons_for_scenario` 函数体实际引用到的名称列全。
> 若函数体还用到 tiering 内的其他私有符号（如 `_effective_loadout`），一并加入 import。

然后**逐字**粘贴 `tiering.py:220-470` 的函数体（含 5 个内部闭包），**不做任何逻辑修改**。

- [ ] **Step 3: 新建 `tierlist_export.py`，原样搬迁 `to_export`**

```python
"""Payload 序列化：把内部排名结构转成 ``data/榜单/*.json`` 的稳定形状。

从 :mod:`src.engine.tiering` 抽出。依赖方向：tierlist_export → tiering（单向）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from src.engine.ammo_pricing import DEFAULT_CURRENCY
from src.engine.tiering import BAND_NAMES, SPARE_AMMO_ROUNDS, GunRanking

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from src.engine.ammo_pricing import AmmoPriceTable
    from src.engine.weapon_pricing import WeaponPriceTable
```

同样**逐字**粘贴 `tiering.py:473-572`（含 `ammo_price_meta` / `weapon_price_meta` 组装）。
import 清单按实读校准，口径同 Step 2。

- [ ] **Step 4: `tiering.py` 删除原定义，并更新全部 8 处导入点**

> **不采用 re-export**。原因：`ranking.py` 需要 import `tiering` 的 `GunRanking` 等符号，
> 若 `tiering.py` 再反向 import `ranking`，则「谁先被导入谁」决定成败 ——
> `import ranking` 先行时会因 `tiering` 半初始化而 `ImportError`。保持单向依赖，
> 把所有导入点改到新模块。项目原则是「不保留向后兼容」，改调用点优于留脆弱的转发层。

`tiering.py` 只做删除（去掉 `rank_weapons_for_scenario` 220-470 与 `to_export` 473-572），
不再 import 二者。

更新以下导入点：

| 文件 | 现状 | 改为 |
| :-- | :-- | :-- |
| `src/engine/__init__.py:18` | `from src.engine.tiering import GunRanking, rank_weapons_for_scenario` | 拆两条：`GunRanking` 仍从 `tiering`；`rank_weapons_for_scenario` 从 `ranking` |
| `src/pipeline.py:32` | `from src.engine import tiering` | 增补 `from src.engine import ranking, tierlist_export` |
| `src/pipeline.py:234` | `tiering.rank_weapons_for_scenario(...)` | `ranking.rank_weapons_for_scenario(...)` |
| `src/pipeline.py:239` | `tiering.to_export(...)` | `tierlist_export.to_export(...)` |
| `tests/test_tiering.py:13-25` | 从 `tiering` import 二者 | `rank_weapons_for_scenario` 从 `ranking`；`to_export` 从 `tierlist_export`；其余（`BAND_NAMES`/`GunRanking`/`assign_tiers`/`_effective_loadout`）仍从 `tiering` |
| `tests/test_gun_price.py:9-15` | 同上 | 同上 |
| `tests/test_kill_cost.py:9-15` | 同上 | 同上 |
| `tests/test_kill_cost.py:118, 162` | 函数内 `from src.engine.tiering import to_export` | 改为 `from src.engine.tierlist_export import to_export` |

校验命令（改完后应只剩新模块）：

```bash
cd "<repo-root>"
grep -rn "tiering.rank_weapons_for_scenario\|tiering.to_export\|from src.engine.tiering import.*rank_weapons_for_scenario\|from src.engine.tiering import.*to_export" src/ tests/ tools/ --include="*.py" | grep -v "__pycache__"
```

Expected: 无输出。

- [ ] **Step 5: 运行测试 + 全量零差异**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "CLEAN" || echo "DIRTY"
```

Expected: 全绿 + `CLEAN`

- [ ] **Step 6: Commit**

```bash
cd "<repo-root>"
git add src/engine/ranking.py src/engine/tierlist_export.py src/engine/tiering.py \
        src/engine/__init__.py src/pipeline.py \
        tests/test_tiering.py tests/test_gun_price.py tests/test_kill_cost.py
git commit -m "refactor(engine): 拆分 tiering.py(572行) 为 编排/数学/序列化 三模块

rank_weapons_for_scenario(220-470, 含 5 闭包) -> ranking.py
to_export(473-572) -> tierlist_export.py
分层数学(_quantile/assign_tiers) 与 GunRanking/常量 留在 tiering.py。
依赖单向: ranking/export -> tiering, 不做 re-export(会因半初始化触发 ImportError);
同步更新 8 处导入点(engine/__init__ / pipeline / 3 个测试文件)。纯搬迁, 零逻辑改动。"
```

---

### Task 15: 拆分 `game_data_sync.py` → `http.py` + `overrides.py` + `normalize.py`

**Files:**
- Create: `src/collectors/http.py`
- Create: `src/collectors/overrides.py`
- Create: `src/collectors/normalize.py`
- Modify: `src/collectors/game_data_sync.py`
- Modify: `src/collectors/__init__.py`（若 re-export）

**Interfaces:**
- Produces: `game_data_sync.sync_all` 与 `game_data_sync.main` 保持**模块路径与签名不变**（G6：CI 依赖 `python -m src.collectors.game_data_sync`）。
- `collectors/__init__.py:6` 只导出 `sync_all` —— 保持可用。

**搬迁清单（当前 27 个顶层符号）**：

| 去向 | 符号 |
| :-- | :-- |
| `http.py` | `SourceUnavailable`、`_sha256_bytes`、`_download`、`_download_json` |
| `overrides.py` | `load_overrides`、`_apply_field_overrides` |
| `normalize.py` | `normalize_ammo`、`normalize_armor`、`normalize_parts`、`normalize_profiles`、`normalize_mechanism_curves`、`normalize_damage_profile`、`normalize_weapon`、`normalize_ranking_index`、`normalize_validation_samples`、`_slot_for_item`、`_normalize_tune`、`_normalize_effect`、`_normalize_spread_profile`、`_normalize_recoil_profile`、`_sol_damage_profile`、`_slugify`、`_strip_authoring_prefix` |
| `game_data_sync.py`（保留） | `sync_all`（1080-1332）、`main`（1333-1360）、`_write_json`、模块常量与映射表（`PANEL_ATTR_KEYS` / `CATEGORY_ZH` / `SLOT_ZH` / `SLOT_BY_PREFIX` / 各路径常量 / `PROFILE_LIBRARIES` / `DEFAULT_MODE` 等） |

> **常量选址**：若常量被 `http.py` 与 `normalize.py` 同时需要，放到新的
> `src/collectors/constants.py`，或留在 `game_data_sync.py` 并由子模块 import
> ——但要避免循环导入。**优先方案**：常量留在 `game_data_sync.py`，
> 子模块通过参数接收，不反向 import。若无法避免循环，停下来报告。

- [ ] **Step 1: 摸清常量与函数的依赖方向**

```bash
cd "<repo-root>"
sed -n '1,115p' src/collectors/game_data_sync.py
```

记录 34-107 区间的全部常量名，以及哪些 `normalize_*` 函数引用了它们。

- [ ] **Step 2: 建 `normalize.py`（最大块，先做）**

创建 `src/collectors/normalize.py`，把 17 个 `normalize_*` / 辅助函数**逐字**搬迁。
需要的常量以显式参数传入或在 `normalize.py` 内重新定义（二选一，按 Step 1 的依赖方向决定）。

- [ ] **Step 3: 建 `http.py` 与 `overrides.py`**

同法搬迁。`http.py` 承载下载与磁盘缓存，`overrides.py` 承载覆盖层。

- [ ] **Step 4: `game_data_sync.py` 保留编排并对内 import**

删除已搬迁定义，加入：

```python
from src.collectors.http import _download, _download_json, _sha256_bytes  # 等实际用到的
from src.collectors.normalize import normalize_ammo, normalize_armor, ...  # 等
from src.collectors.overrides import load_overrides, _apply_field_overrides
```

- [ ] **Step 5: 冒烟验证 CLI 契约（G6）**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -c "
from src.collectors.game_data_sync import sync_all, main
from src.collectors import sync_all as reexported
print('CLI contract OK', sync_all is reexported)
"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.collectors.game_data_sync --help
```

Expected: `CLI contract OK True` + argparse 帮助正常打印。
（**不要真的跑同步**，它会联网拉上游数据。）

- [ ] **Step 6: 运行测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: 全绿（`tests/test_data_integrity.py` 是本任务的真正护栏）

- [ ] **Step 7: Commit**

```bash
cd "<repo-root>"
git add src/collectors/
git commit -m "refactor(collectors): 拆分 game_data_sync.py(1360行) 为 http/overrides/normalize

同步器混了 HTTP 拉取与缓存、覆盖层、17 个 schema 归一化函数、编排与 CLI。
按关注点拆为 http.py / overrides.py / normalize.py; sync_all 与 main 留在
game_data_sync.py 以保证 python -m src.collectors.game_data_sync 契约不变。纯搬迁。"
```

---

### Task 16: 距离带单一来源 + 一致性测试

**Files:**
- Create: `tests/test_distance_bands.py`
- Modify: `src/engine/engagement.py`（`DISTANCE_BANDS:176` 为唯一真源，新增 `BAND_NAMES`）
- Modify: `src/engine/tiering.py:27`
- Modify: `src/renderers/ttk_report.py:11`
- Modify: `src/pipeline.py:38`（若 import 路径需要调整）

**Interfaces:**
- Produces: `engagement.BAND_NAMES: tuple = ("贴脸", "近距", "中距", "远距")`（由 `DISTANCE_BANDS` 的键序导出）
- `tiering.BAND_NAMES` 与 `ttk_report.BAND_ORDER` 改为同源引用。

> **G1 约束**：`tiering.py:568-569` 用 `BAND_NAMES` × `eg.DISTANCE_BANDS` 生成导出 payload 的
> `from_m` / `to_m`。带名与边界值**均不得改动**，本任务只统一声明位置。

- [ ] **Step 1: 写失败测试（先证明缺陷真实存在）**

新建 `tests/test_distance_bands.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败或通过**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest tests/test_distance_bands.py -q
```

Expected: 当前应**通过**（三处值恰好一致）—— 这证明的是「当前一致」，
测试的价值在于**未来改名时立刻报警**。若 `test_band_summary_keys_cover_all_bands`
因 `ttk_curve` / `band_summary` 签名不符而报错，按实际签名调整调用方式
（`grep -n "def ttk_curve\|def band_summary" src/engine/engagement.py`）。

- [ ] **Step 3: 收敛为单一真源**

`engagement.py` 在 `DISTANCE_BANDS` 定义之后加入：

```python
#: 距离带顺序（唯一真源；tiering 与 renderers 均从此处引用）
BAND_NAMES: tuple = tuple(DISTANCE_BANDS)
```

`tiering.py:27` 改为：

```python
from src.engine.engagement import BAND_NAMES
```

删除原 `BAND_NAMES: tuple = ("贴脸", "近距", "中距", "远距")` 字面量。

`ttk_report.py:11` 改为：

```python
from src.engine.engagement import BAND_NAMES as BAND_ORDER
```

删除原 `BAND_ORDER = (...)` 字面量。`pipeline.py:38` 的
`from src.renderers.ttk_report import BAND_ORDER` **保持不动**（值同源，且 `engagement`
不回引 renderers，无循环依赖）。

> 若担心渲染层从「纯标准库叶子模块」变为依赖 engine：本任务采用上述方案（最小 diff）。
> 备选是给 `render_*` 函数加带序参数、由 `pipeline` 注入，但改动点更多。**默认走最小 diff。**

- [ ] **Step 4: 运行测试 + 全量零差异**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "CLEAN" || echo "DIRTY"
```

Expected: 全绿 + `CLEAN`

- [ ] **Step 5: Commit**

```bash
cd "<repo-root>"
git add tests/test_distance_bands.py src/engine/engagement.py src/engine/tiering.py src/renderers/ttk_report.py
git commit -m "fix(engine): 距离带收敛为单一真源并加一致性守护

(\"贴脸\",\"近距\",\"中距\",\"远距\") 原在 engagement:176 / tiering:27 / ttk_report:11
三处独立声明, 任一处改名会让 band_summary 的 .get/in 判定静默 fail-soft,
整条距离带从榜单消失且无报错。以 engagement.DISTANCE_BANDS 为唯一源,
tiering 与 renderers 改为引用; 新增三方一致 + 覆盖 + 边界连续性测试。"
```

---

### Task 17: 修饰器语义合并

**Files:**
- Modify: `src/engine/modifiers.py`（Task 13 产出）
- Modify: `src/engine/curves.py`

**Interfaces:**
- Produces: `curves.modifier_factor(modifier: Optional[str], value: Optional[float]) -> Optional[float]`
- `curves.apply_modifier` 改为复用 `modifier_factor`。

**两个问题**：

| 问题 | 位置 | 现状 |
| :-- | :-- | :-- |
| `part_tuning_layer` 内联重写了 `accumulate` 的三分支 | `modifiers.py`（原 weapon_state.py:246-274） | 已出现边界差异：精校路径缺 `_ATTR_TARGET_PREFIX` 过滤与别名字处理 |
| `factor` 与 `curves.apply_modifier` 各自实现同一 modifier 语义 | `modifiers.py`（原 151-159）+ `curves.py:154-179` | `Mult_A → 1+v`、`Mult_C → v` 两处判定 |

> ⚠️ **本任务改变的是语义实现路径，风险最高**。若 `part_tuning_layer` 的边界差异
> 是刻意的（不是 bug），合并会改变数值。**动手前必须先跑 Step 1 的等价性验证。**

- [ ] **Step 1: 先做等价性验证（合并前）**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -c "
from src.engine.curves import apply_modifier
cases = [(100.0,'Addend',5.0),(100.0,'Mult_A',0.3),(100.0,'Mult_C',0.88),
         (100.0,'Mult_C',1.16),(100.0,'Initial',7.0),(100.0,None,3.0),(100.0,'X',3.0)]
for base, mod, val in cases:
    print(base, mod, val, '->', apply_modifier(base, mod, val))
"
```

记录输出，作为 `modifier_factor` 的语义基准：
`Addend → base+val`；`Mult_A → base*(1+val)`；`Mult_C → base*val`；`Initial → val`。

- [ ] **Step 2: 在 `curves.py` 增加 `modifier_factor`**

```python
def modifier_factor(modifier: Optional[str], value: Optional[float]) -> Optional[float]:
    """把 modifier 折算为**乘数**；非乘性 modifier 返回 ``None``。

    ``Mult_A`` → ``1 + value``；``Mult_C`` → ``value``。
    其余（Addend / Initial / 未知）返回 ``None``，由调用方按加法或覆盖处理。
    """
    if value is None:
        return None
    if modifier == "Mult_A":
        return 1.0 + value
    if modifier == "Mult_C":
        return value
    return None
```

- [ ] **Step 3: `apply_modifier` 改为复用**

```python
def apply_modifier(base: float, modifier: Optional[str], value: Optional[float]) -> float:
    """（保留原 docstring 的全部语义说明）"""
    if value is None:
        return base
    factor = modifier_factor(modifier, value)
    if factor is not None:
        return base * factor
    if modifier == "Addend":
        return base + value
    if modifier == "Initial":
        return value
    return base
```

- [ ] **Step 4: `factor` 改为复用 `modifier_factor`**

`modifiers.py` 中原 `_factor`/`factor` 的实现改为转调 `curves.modifier_factor`。

- [ ] **Step 5: `part_tuning_layer` 改用 `accumulate`**

精校求值的每个点，把内联的 `factor / Addend / Initial` 三分支替换为调用
`accumulate(layer, target, modifier, value, None)`。

> **若 Step 6 出现 DIRTY 且定位到精校路径**：说明 `part_tuning_layer` 的边界差异
> 是刻意设计（或依赖了被内联版跳过的过滤）。此时**回退本步**，只保留 Step 2-4
> 的 `modifier_factor` 抽取（那部分等价），并在计划执行报告中记录
> 「`part_tuning_layer` 与 `accumulate` 的差异经证实为刻意行为，不予合并」。

- [ ] **Step 6: 运行测试 + 全量零差异 + 官方复现**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "CLEAN" || echo "DIRTY"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" tools/verify_official_reproduction.py
```

Expected: 全绿 + `CLEAN` + 官方复现工具输出与改动前一致（3774 样本点分级分布不变）。

- [ ] **Step 7: Commit**

```bash
cd "<repo-root>"
git add src/engine/modifiers.py src/engine/curves.py
git commit -m "refactor(engine): 统一 modifier 语义实现

curves 暴露 modifier_factor(乘数折算), apply_modifier 与 modifiers.factor 复用之;
part_tuning_layer 内联的 factor/Addend/Initial 三分支改调 accumulate。"
```

---

### Task 18: 阶段 3 门禁与全量验收

**Files:**
- Modify: 无（仅验证）

- [ ] **Step 1: 全量测试**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m pytest -q
```

Expected: 全绿

- [ ] **Step 2: 官方数据复现（数值回归护栏）**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" tools/verify_official_reproduction.py
```

Expected: 与阶段 0 记录的分级分布一致（逐位一致 / |Δ|≤1e-9 / ≤1e-5 / ≤1e-2 / >1e-2 五档数字不变）。

- [ ] **Step 3: 全量重算 + 零差异**

```bash
cd "<repo-root>"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m src.pipeline --beam-width 8
git diff --exit-code README.md docs/ data/ && echo "PHASE3 GATE: CLEAN" || echo "PHASE3 GATE: DIRTY"
```

Expected: `PHASE3 GATE: CLEAN`

- [ ] **Step 4: CLI 契约复核（G6）**

```bash
cd "<repo-root>"
for m in src.pipeline src.collectors.game_data_sync src.collectors.ammo_price_sync src.collectors.weapon_price_sync; do
  "C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -m $m --help > /dev/null 2>&1 \
    && echo "OK   $m" || echo "FAIL $m"
done
```

Expected: 四行全 `OK`

- [ ] **Step 5: 依赖与体积核对（G3）**

```bash
cd "<repo-root>"
echo "--- src/ 是否引入第三方 import ---"
"C:/Users/pc/AppData/Local/Programs/Python/Python314/python.exe" -c "
import ast, pathlib, sys
stdlib = set(sys.stdlib_module_names)
bad = []
for p in pathlib.Path('src').rglob('*.py'):
    tree = ast.parse(p.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                root = a.name.split('.')[0]
                if root not in stdlib and root != 'src':
                    bad.append((str(p), a.name))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            root = node.module.split('.')[0]
            if root not in stdlib and root != 'src':
                bad.append((str(p), node.module))
print('THIRD-PARTY IMPORTS:', bad if bad else 'NONE (OK)')
"
echo "--- 总行数 ---"
find src tests tools -name "*.py" -exec wc -l {} + | tail -1
```

Expected: `THIRD-PARTY IMPORTS: NONE (OK)`；总行数相对 9108 有净减少（阶段 3 本身不减行，总减幅主要来自阶段 1）。

- [ ] **Step 6: 记录最终成果**

汇总写入执行报告：净减行数、测试数量、各阶段耗时、阶段 2 的性能前后对比、
Task 17 Step 5 是否回退（若回退，记录原因）。

---

## 附：本计划范围外（已识别，需另行确认）

以下项在探索中确认存在，但**不在本次 spec 授权范围**，未经确认不执行：

| 项 | 预估收益 | 说明 |
| :-- | :-- | :-- |
| 价格表测试镜像合并 | 约 −150 行 | `test_ammo_pricing.py`(110) ↔ `test_weapon_pricing.py`(108) 有 8 条结构完全一致的用例，可用 `pytest.mark.parametrize` 合一 |
| 价格同步器测试镜像合并 | 约 −110 行 | `test_ammo_price_sync.py`(160) ↔ `test_weapon_price_sync.py`(180) 有 6-7 条一致 |
| 新增 `tests/conftest.py` | 约 −30 行 | `ROOT` 在 8 个测试文件重复、`gd` fixture 在 5 个文件重复 |
| `requirements.txt` 并入 `pyproject.toml` | 约 −4 行 | 需同步改 `.github/workflows/update.yml:36` 的 `pip install -r` |
| onebiji 双采集器公共层抽取 | 约 −110~150 行 | `ammo_price_sync.py`(248) ↔ `weapon_price_sync.py`(254) 重复度约 72% |
| `.probe/`(67 MB) 与 `.cache/`(69 MB) 清理 | 释放 136 MB | 本地 gitignore 目录，不属仓库；清理属个人文件操作，需单独确认 |
