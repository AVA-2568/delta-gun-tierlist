# 三角洲行动枪械梯度排行榜与60发备弹性价比系统实施计划 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个在 GitHub Actions 上全自动定时运行的三角洲行动枪械天梯与 60 发备弹性价比评估系统，输出结构化数据与 Markdown 矩阵文档。

**Architecture:** 系统解耦为四层：数据采集与三级容灾层（爬虫 + Snapshot + Baseline）、离散逐发战斗仿真引擎（耐久递减 + EHR 距离修正）、加权综合经济学评分引擎（60发起枪总价 + 单发击杀成本 + 0~100评分）、多格式渲染层（README/分册/JSON）。

**Tech Stack:** Python 3.10+, Pydantic v2, pytest, requests / curl_cffi, jinja2 / Markdown.

## Global Constraints

- 绝不硬编码绝对单发伤害除法，必须使用逐发命中状态机计算真实 STK 与 TTK。
- 必须严格遵循「裸枪成本 + 实用合理改装成本 + 60发备弹消耗」作为基准起枪战术单元。
- 网络请求必须有三级容灾降级（Live -> Snapshot -> Baseline），确保在 GitHub Actions 环境下永不断流。
- 评分输出覆盖 3 种甲弹对抗（4-4、4-5、5-5）$\times$ 3 种作战距离（15m、35m、50m）共 9 个细分维度。
- CI/CD 必须包含语义级差异保护，只有梯队迁移或评分波动绝对值 $\ge 3.0$ 时才触发 Git 自动提交。

---

### Task 1: 项目基础脚手架与基础数据底表建立

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `data/base_guns.json`
- Create: `data/default_builds.json`
- Create: `data/baseline_ammo_prices.json`
- Test: `tests/test_data_integrity.py`

**Interfaces:**
- Produces: 核心底表 JSON 文件，包含 10+ 把主流枪械（M4A1、Vector、SVD、AS Val、K416、M14等）的真实物理与伤害数据，主流实用改枪码及配件基准价，4/5 级弹药官方参考单价。

- [ ] **Step 1: 编写依赖清单与项目配置**

```txt
# requirements.txt
pydantic>=2.5.0
requests>=2.31.0
curl-cffi>=0.7.0
pytest>=8.0.0
pytest-cov>=4.1.0
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 2: 编写测试验证数据底表文件完整性**

```python
# tests/test_data_integrity.py
import json
import os

def test_base_guns_file_exists_and_valid():
    path = "data/base_guns.json"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) >= 6
    for gun in data:
        assert "id" in gun
        assert "rpm" in gun and gun["rpm"] > 0
        assert "caliber" in gun
        assert "dropoffs" in gun and len(gun["dropoffs"]) > 0

def test_baseline_ammo_prices_exists_and_valid():
    path = "data/baseline_ammo_prices.json"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) >= 6
    for ammo in data:
        assert ammo["level"] in [4, 5]
        assert ammo["price_per_round"] > 0

def test_default_builds_exists_and_valid():
    path = "data/default_builds.json"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) >= 6
    for build in data:
        assert "gun_id" in build
        assert "build_code" in build
        assert build["mod_cost"] > 0
```

- [ ] **Step 3: 运行测试验证失败**

运行：`pytest tests/test_data_integrity.py -v`
预期：FAIL (文件尚不存在)

- [ ] **Step 4: 创建基础数据底表文件**

创建 `data/base_guns.json`、`data/default_builds.json`、`data/baseline_ammo_prices.json`，填充真实测算数据（涵盖 M4A1, M14, SVD, Vector, MP5, K416, AS Val 等主流武器、各口径 4/5 级弹药价格与实用改枪方案）。

- [ ] **Step 5: 运行测试验证通过**

运行：`pytest tests/test_data_integrity.py -v`
预期：PASS

- [ ] **Step 6: 提交代码**

```bash
git add requirements.txt pyproject.toml data/ tests/test_data_integrity.py
git commit -m "chore: setup project dependencies and initial baseline datasets"
```

---

### Task 2: Pydantic 核心数据契约模型

**Files:**
- Create: `src/__init__.py`
- Create: `src/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `GunMeta`, `DamageDropoff`, `AmmoPrice`, `WeaponBuild`, `SimulationResult`, `TierEntry`, `DataSourceStatus`.

- [ ] **Step 1: 编写数据模型的单元测试**

```python
# tests/test_models.py
import pytest
from pydantic import ValidationError
from src.models import GunMeta, DamageDropoff, AmmoPrice, WeaponBuild, TierEntry

def test_gun_meta_validation():
    dropoff = DamageDropoff(max_distance=20.0, chest_damage=32.0, armor_damage=28.0)
    gun = GunMeta(
        id="m4a1",
        name="M4A1",
        category="突击步枪",
        caliber="5.56x45mm",
        rpm=800,
        bullet_velocity=750.0,
        base_price=35000,
        default_mag_size=30,
        ads_time_ms=220,
        recoil_control=72.0,
        stability=68.0,
        dropoffs=[dropoff]
    )
    assert gun.id == "m4a1"
    assert gun.rpm == 800

def test_ammo_price_validation():
    ammo = AmmoPrice(
        caliber="5.56x45mm",
        level=4,
        name="5.56mm A1",
        penetration=42,
        price_per_round=1200,
        source="baseline",
        updated_at="2026-09-17T00:00:00Z"
    )
    assert ammo.price_per_round == 1200

def test_invalid_gun_rpm():
    with pytest.raises(ValidationError):
        GunMeta(
            id="bad_gun",
            name="Bad",
            category="突击步枪",
            caliber="5.56x45mm",
            rpm=-100, # Invalid
            bullet_velocity=700.0,
            base_price=30000,
            default_mag_size=30,
            ads_time_ms=200,
            recoil_control=50.0,
            stability=50.0,
            dropoffs=[]
        )
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_models.py -v`
预期：FAIL (ModuleNotFoundError)

- [ ] **Step 3: 编写 `src/models.py` 完整实现**

实现 `GunMeta`, `DamageDropoff`, `AmmoPrice`, `WeaponBuild`, `SimulationResult`, `TierEntry` 等结构并增加合理校验（范围、正数约束）。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_models.py -v`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add src/__init__.py src/models.py tests/test_models.py
git commit -m "feat: implement pydantic data models and schemas"
```

---

### Task 3: 战斗仿真与实战 TTK 引擎 (`simulator.py`)

**Files:**
- Create: `src/engine/__init__.py`
- Create: `src/engine/simulator.py`
- Test: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `GunMeta`, `AmmoPrice` from `src.models`.
- Produces: `simulate_duel(gun: GunMeta, ammo: AmmoPrice, armor_level: int, distance_m: int) -> SimulationResult`

- [ ] **Step 1: 编写仿真引擎测试用例**

```python
# tests/test_simulator.py
from src.models import GunMeta, DamageDropoff, AmmoPrice
from src.engine.simulator import simulate_duel, calc_effective_hit_rate

def test_effective_hit_rate_distance_dropoff():
    # 近距离 EHR 应该接近 1.0
    ehr_15m = calc_effective_hit_rate(recoil_control=70.0, stability=70.0, velocity=700.0, distance_m=15)
    ehr_50m = calc_effective_hit_rate(recoil_control=70.0, stability=70.0, velocity=700.0, distance_m=50)
    assert 0.90 <= ehr_15m <= 1.0
    assert ehr_50m < ehr_15m

def test_simulation_level_4_ammo_vs_level_4_armor():
    dropoffs = [
        DamageDropoff(max_distance=25.0, chest_damage=34.0, armor_damage=30.0),
        DamageDropoff(max_distance=60.0, chest_damage=28.0, armor_damage=24.0),
    ]
    gun = GunMeta(
        id="m4a1", name="M4A1", category="突击步枪", caliber="5.56x45mm",
        rpm=800, bullet_velocity=750.0, base_price=35000, default_mag_size=30,
        ads_time_ms=220, recoil_control=75.0, stability=70.0, dropoffs=dropoffs
    )
    ammo_4 = AmmoPrice(
        caliber="5.56x45mm", level=4, name="5.56mm 4级", penetration=42,
        price_per_round=1200, source="test", updated_at="2026-09-17"
    )
    # 15米测试
    result = simulate_duel(gun, ammo_4, armor_level=4, distance_m=15)
    assert 3 <= result.stk <= 6
    assert result.practical_ttk_ms > 0
    assert result.theoretical_ttk_ms <= result.practical_ttk_ms
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_simulator.py -v`
预期：FAIL

- [ ] **Step 3: 编写 `src/engine/simulator.py` 实现**

实现：
1. 护甲耐久逐发扣减与钝伤/穿透动态结算状态机（包含 4 级甲 75 耐久、5 级甲 95 耐久；材质吸收系数与临界击穿函数）。
2. `calc_effective_hit_rate(recoil, stability, velocity, distance)` 曲线函数。
3. `simulate_duel` 输出 `SimulationResult(stk, theoretical_ttk_ms, practical_ttk_ms, ehr)`.

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_simulator.py -v`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add src/engine/__init__.py src/engine/simulator.py tests/test_simulator.py
git commit -m "feat: implement bullet-by-bullet combat simulation and practical TTK engine"
```

---

### Task 4: 经济学成本与加权综合评分引擎 (`cost_model.py` & `ranker.py`)

**Files:**
- Create: `src/engine/cost_model.py`
- Create: `src/engine/ranker.py`
- Test: `tests/test_ranker.py`

**Interfaces:**
- Consumes: `SimulationResult`, `GunMeta`, `AmmoPrice`, `WeaponBuild`
- Produces: `calc_loadout_cost(gun, build, ammo, reserve_rounds=60) -> (total_cost, ammo_cost, single_kill_cost)`
- Produces: `rank_weapons(guns, builds_dict, ammo_dict, armor_level, ammo_level, distance_m) -> List[TierEntry]`

- [ ] **Step 1: 编写经济学与加权排行的单元测试**

```python
# tests/test_ranker.py
from src.models import GunMeta, DamageDropoff, AmmoPrice, WeaponBuild
from src.engine.cost_model import calc_loadout_cost
from src.engine.ranker import rank_weapons

def test_cost_calculation_60_rounds():
    gun = GunMeta(
        id="m4a1", name="M4A1", category="突击步枪", caliber="5.56x45mm",
        rpm=800, bullet_velocity=750.0, base_price=35000, default_mag_size=30,
        ads_time_ms=220, recoil_control=75.0, stability=70.0,
        dropoffs=[DamageDropoff(max_distance=50.0, chest_damage=32.0, armor_damage=30.0)]
    )
    build = WeaponBuild(
        gun_id="m4a1", build_name="实用改", build_code="M4-PRACTICAL-01",
        mod_cost=45000, ads_modifier_ms=-20, recoil_bonus=15.0
    )
    ammo = AmmoPrice(
        caliber="5.56x45mm", level=4, name="5.56 M855A1", penetration=42,
        price_per_round=1000, source="test", updated_at="2026-09-17"
    )
    total_cost, ammo_60_cost, single_kill_cost = calc_loadout_cost(gun, build, ammo, stk=4, reserve_rounds=60)
    assert ammo_60_cost == 60 * 1000 # 60000
    assert total_cost == 35000 + 45000 + 60000 # 140000
    assert single_kill_cost == 4 * 1000 # 4000

def test_ranking_tier_distribution():
    # 验证评分返回结果包含 T0~T3 且按 composite_score 倒序排列
    # (构造多把枪并验证 rank_weapons 输出)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_ranker.py -v`
预期：FAIL

- [ ] **Step 3: 编写 `src/engine/cost_model.py` 与 `src/engine/ranker.py`**

实现：
1. 成本精确计算公式（总成本、60发备弹费、单杀耗弹费）。
2. 战力分、操控分、成本分归一化算法（Min-Max 缩放）。
3. 综合指数打分（权重 50% 战力 + 20% 操控 + 30% 成本效益）。
4. 梯队自动裁定器（T0 $\ge 88$, T1 $[78, 88)$, T2 $[65, 78)$, T3 $<65$）以及特征标签标注。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_ranker.py -v`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add src/engine/cost_model.py src/engine/ranker.py tests/test_ranker.py
git commit -m "feat: implement cost economics and weighted multi-dimensional ranker"
```

---

### Task 5: 数据采集与三级容灾降级收集器 (`collectors/`)

**Files:**
- Create: `src/collectors/__init__.py`
- Create: `src/collectors/ammo_collector.py`
- Create: `src/collectors/build_collector.py`
- Create: `src/collectors/gun_loader.py`
- Test: `tests/test_collectors.py`

**Interfaces:**
- Consumes: `data/base_guns.json`, `data/default_builds.json`, `data/baseline_ammo_prices.json`, `data/snapshot_prices.json`
- Produces: `load_all_guns() -> List[GunMeta]`
- Produces: `fetch_ammo_prices() -> (Dict[str, AmmoPrice], DataSourceStatus)`
- Produces: `fetch_weapon_builds() -> Dict[str, WeaponBuild]`

- [ ] **Step 1: 编写采集器及容灾降级测试**

```python
# tests/test_collectors.py
from src.collectors.gun_loader import load_all_guns
from src.collectors.ammo_collector import fetch_ammo_prices
from src.collectors.build_collector import fetch_weapon_builds

def test_load_all_guns():
    guns = load_all_guns()
    assert len(guns) >= 6
    assert all(g.rpm > 0 for g in guns)

def test_fetch_ammo_prices_fallback_chain(monkeypatch):
    # 模拟网络失败，验证触发降级到快照或基准库
    def mock_failed_get(*args, **kwargs):
        raise ConnectionError("Network blocked by WAF")
    
    monkeypatch.setattr("requests.get", mock_failed_get)
    prices, status = fetch_ammo_prices()
    assert len(prices) > 0
    assert status.source in ["snapshot", "baseline"]
    assert status.is_fallback is True
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_collectors.py -v`
预期：FAIL

- [ ] **Step 3: 编写采集器实现与容灾断路器**

实现：
1. `gun_loader.py`：载入校验基础枪械元数据。
2. `ammo_collector.py`：使用 `curl_cffi` 配合 User-Agent 随机化请求 `zxfps.com` 弹药价格；发生 403/429/超时或格式校验不通过时自动熔断，降级读取 `data/snapshot_prices.json`；若快照不存在再降级读取 `data/baseline_ammo_prices.json`。成功抓取时原子写入更新 `snapshot_prices.json`。
3. `build_collector.py`：载入实用改枪方案并实现防天价溢价过滤替换规则。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_collectors.py -v`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add src/collectors/ tests/test_collectors.py
git commit -m "feat: implement data collectors with multi-tier fallback resilience"
```

---

### Task 6: 报告与文档渲染器 (`renderers/`)

**Files:**
- Create: `src/renderers/__init__.py`
- Create: `src/renderers/markdown_renderer.py`
- Create: `src/renderers/json_exporter.py`
- Test: `tests/test_renderers.py`

**Interfaces:**
- Consumes: 全场景 9 维 `List[TierEntry]` 结果集与 `DataSourceStatus`
- Produces: 生成并覆写 `README.md`
- Produces: 生成 `docs/tierlist/4armor_4ammo.md`, `docs/tierlist/4armor_5ammo.md`, `docs/tierlist/5armor_5ammo.md`
- Produces: 生成 `data/latest_rankings.json`

- [ ] **Step 1: 编写渲染器测试**

```python
# tests/test_renderers.py
import os
import json
from src.renderers.markdown_renderer import render_main_readme, render_scenario_docs
from src.renderers.json_exporter import export_rankings_json

def test_markdown_rendering_structure(sample_ranking_results, sample_status, tmp_path):
    readme_path = tmp_path / "README.md"
    render_main_readme(sample_ranking_results, sample_status, output_path=str(readme_path))
    assert readme_path.exists()
    content = readme_path.read_text(encoding="utf-8")
    assert "三角洲行动" in content
    assert "T0" in content
    assert "60发备弹" in content

def test_json_export(sample_ranking_results, sample_status, tmp_path):
    json_path = tmp_path / "latest_rankings.json"
    export_rankings_json(sample_ranking_results, sample_status, output_path=str(json_path))
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "metadata" in data
    assert "rankings" in data
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_renderers.py -v`
预期：FAIL

- [ ] **Step 3: 编写渲染实现代码**

实现：
1. `markdown_renderer.py`：排版精美的 Markdown 模板，包含头部状态徽章、三大主流场景 T0 卡片、近/中/远九宫格推荐天梯矩阵表格、改枪码一键复制提示。
2. `json_exporter.py`：导出带元数据时间戳的规范 JSON。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_renderers.py -v`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add src/renderers/ tests/test_renderers.py
git commit -m "feat: implement markdown document and json export renderers"
```

---

### Task 7: 统一调度流水线与语义级防污染比对 (`pipeline.py`)

**Files:**
- Create: `src/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: CLI 入口 `python -m src.pipeline [--force]`
- Produces: 计算新旧排名差异 `has_semantic_changes(old_rankings, new_rankings, delta_threshold=3.0) -> bool`
- Produces: 在 GitHub Actions 中输出环境指令 `HAS_SEMANTIC_CHANGES=true/false`

- [ ] **Step 1: 编写流水线与语义比对测试**

```python
# tests/test_pipeline.py
from src.pipeline import run_pipeline, has_semantic_changes

def test_has_semantic_changes_detects_tier_switch():
    old = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0}]
    new = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T0", "composite_score": 88.5}]
    assert has_semantic_changes(old, new, delta_threshold=3.0) is True

def test_has_semantic_changes_ignores_tiny_fluctuations():
    old = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.0}]
    new = [{"gun_id": "m4a1", "scenario": "4-4-15m", "tier": "T1", "composite_score": 85.5}]
    assert has_semantic_changes(old, new, delta_threshold=3.0) is False
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_pipeline.py -v`
预期：FAIL

- [ ] **Step 3: 编写 `src/pipeline.py`**

编排采集、仿真、评分、比对和渲染全流程，支持命令行传参 `--force` 强制全量覆盖更新。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_pipeline.py -v`
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add src/pipeline.py tests/test_pipeline.py
git commit -m "feat: implement full pipeline orchestrator with semantic diff detection"
```

---

### Task 8: GitHub Actions CI/CD 自动化工作流与端到端交付

**Files:**
- Create: `.github/workflows/update.yml`
- Modify: `README.md` (初始主文档生成)
- Test: 本地执行 `python -m src.pipeline --force` 并运行全量测试套件

- [ ] **Step 1: 编写 `.github/workflows/update.yml`**

```yaml
name: Update Gun Tier List & Prices

on:
  schedule:
    - cron: '0 0,12 * * *'  # 每天 UTC 00:00 与 12:00 定时触发
  workflow_dispatch:        # 支持手动立即触发
  push:
    branches: [ main, master ]
    paths:
      - 'data/base_guns.json'
      - 'data/default_builds.json'

permissions:
  contents: read

jobs:
  update-tierlist:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 2

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run Test Suite
        run: pytest -v

      - name: Run Pipeline
        id: run_pipeline
        run: python -m src.pipeline

      - name: Commit and Push Changes
        if: env.HAS_SEMANTIC_CHANGES == 'true' && github.event_name != 'pull_request'
        permissions:
          contents: write
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add README.md docs/ data/
          git commit -m "chore(auto): refresh weapon rankings and price data [skip ci]"
          git push
```

- [ ] **Step 2: 运行全量测试与本地端到端流水线**

运行：`pytest --cov=src -v`
运行：`python -m src.pipeline --force`
预期：生成完整的 `README.md`、`docs/tierlist/*.md` 与 `data/latest_rankings.json`。

- [ ] **Step 3: 验证输出文件规范与完整性**

检查生成的 `README.md` 是否正确展示了 4-4、4-5、5-5 场景下的 T0 推荐、60发备弹总成本以及改枪码。

- [ ] **Step 4: 提交并推送到仓库**

```bash
git add .github/workflows/update.yml README.md docs/ data/
git commit -m "ci: configure automated update workflow and generate initial tier lists"
```
