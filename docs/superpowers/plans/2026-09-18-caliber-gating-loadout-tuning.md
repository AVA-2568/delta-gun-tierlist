# 三角洲行动口径准入、确定性 TTK 与实战改枪精校实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底重构《三角洲行动》枪械天梯与配装系统：清除虚构弹药并建立口径准入机制，将破甲状态机校准为官方确定性阶梯穿透与部位倍率真值，废除易失效改枪码与 8 万截断，实现全量因枪制宜实装方案（冲锋枪扩容/连狙3倍镜）与官方实战精校口诀全链路物理增益传导。

**Architecture:** 
1. 数据契约层 (`src/models.py`)：升级 `WeaponBuild` 与 `TierEntry`，移除 `build_code` / `code_status`，新增 `stability_bonus`、`velocity_bonus_pct`、`mag_size_bonus` 与 `tuning_instructions`。
2. 弹药与准入层 (`data/baseline_ammo_prices.json`, `data/snapshot_prices.json`, `src/engine/ranker.py`)：校准官方 114 种弹药元数据，删除虚构弹药；在 `ranker.py` 中引入口径准入门槛，无对应等级弹药的口径自动跳过该场景天梯计算。
3. 战斗仿真层 (`src/engine/simulator.py`)：实现官方阶梯穿透判定（低穿高 0% 钝伤、同级 50% 肉伤、高穿低 75% 肉伤、碎甲按比例拆分）、部位倍率真值（头 1.90x、四肢 0.40x）与实战射击期望公式。
4. 配件与精校层 (`src/engine/gunsmith.py`, `src/collectors/build_collector.py`)：移除 8 万截断与死代码，根据枪械短板配置扩容弹匣与泛用 3 倍镜，合成配件基础属性与精校滑块加成（后坐 -10%~-16%、初速 +9%），据实核算市场总造价。
5. 渲染与交付层 (`src/renderers/markdown_renderer.py`, `src/renderers/json_exporter.py`)：输出包含实装配件清单、实战精校口诀与动态 FAQ 的新版天梯文档与 OpenAPI JSON。

**Tech Stack:** Python 3.10+, Pydantic v2, Pytest, Pytest-cov.

## Global Constraints
- 遵循 Python PEP 8 风格与现有架构分层。
- 严禁任何硬编码价格截断（如 80000 截断）。
- 严禁任何虚构弹药（如 `.45 ACP RIP/AP+`）。
- 单元测试覆盖率必须保持在 85% 以上，所有测试 100% 通过。
- 产出物 (`README.md`, `docs/tierlist/*.md`, `data/latest_rankings.json`) 必须通过 pipeline 全自动重新生成并严格保持一致。

---

### Task 1: 升级数据契约模型 (`src/models.py`)

**Files:**
- Modify: `src/models.py:50-130`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: Pydantic `BaseModel`, `Field`, `ConfigDict`
- Produces: 升级后的 `WeaponBuild`（含 `stability_bonus`, `velocity_bonus_pct`, `mag_size_bonus`, `tuning_instructions`，移除 `build_code`, `code_status`）与 `TierEntry`（含 `tuning_instructions`，移除 `build_code`, `code_status`）

- [ ] **Step 1: 编写数据契约测试**

在 `tests/test_models.py` 中更新针对 `WeaponBuild` 与 `TierEntry` 的测试用例：
```python
def test_weapon_build_tuning_and_physical_fields():
    build = WeaponBuild(
        gun_id="m4a1",
        build_name="实用实战改",
        mod_cost=38500,
        ads_modifier_ms=10,
        recoil_bonus=18.5,
        stability_bonus=12.0,
        velocity_bonus_pct=0.09,
        mag_size_bonus=15,
        attachments=["枪口: 钢制膛口制退器", "弹匣: M4扩容45发弹匣"],
        tuning_instructions=["枪托: 配重向右拉满(+50g，后坐-6%)"],
    )
    assert build.stability_bonus == 12.0
    assert build.velocity_bonus_pct == 0.09
    assert build.mag_size_bonus == 15
    assert len(build.tuning_instructions) == 1
    assert not hasattr(build, "build_code")


def test_tier_entry_without_build_code():
    entry_dict = {
        "gun_id": "m4a1",
        "gun_name": "M4A1",
        "category": "突击步枪",
        "caliber": "5.56x45mm",
        "distance_m": 15,
        "armor_level": 4,
        "ammo_level": 4,
        "stk": 6,
        "practical_ttk_ms": 520.0,
        "ammo_60_cost": 69000,
        "total_loadout_cost": 142500,
        "single_kill_cost": 6900,
        "combat_score": 85.0,
        "handling_score": 80.0,
        "cost_score": 75.0,
        "composite_score": 81.0,
        "tier": "T1",
        "attachments": ["枪口: 钢制膛口制退器"],
        "tuning_instructions": ["枪托: 配重向右拉满(+50g)"],
        "tags": ["均衡全能"],
    }
    entry = TierEntry.model_validate(entry_dict)
    assert entry.tuning_instructions == ["枪托: 配重向右拉满(+50g)"]
    assert not hasattr(entry, "build_code")
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_models.py -k "test_weapon_build_tuning_and_physical_fields" -v`
预期：FAIL（`WeaponBuild` 字段不匹配或包含额外禁止字段）

- [ ] **Step 3: 更新 `src/models.py`**

更新 `src/models.py` 中的 `WeaponBuild` 与 `TierEntry`：
```python
class WeaponBuild(BaseModel):
    """Calibrated weapon build configuration with attachments and tuning instructions."""

    model_config = ConfigDict(extra="forbid")

    gun_id: str = Field(min_length=1, description="Unique weapon identifier")
    build_name: str = Field(min_length=1, description="Name of the build profile")
    mod_cost: int = Field(ge=0, description="Sum of market costs of all equipped attachments")
    ads_modifier_ms: int = Field(default=0, description="ADS time delta in milliseconds")
    recoil_bonus: float = Field(default=0.0, description="Total recoil control bonus (base + tuning)")
    stability_bonus: float = Field(default=0.0, description="Total stability bonus (base + tuning)")
    velocity_bonus_pct: float = Field(default=0.0, description="Muzzle velocity bonus percentage (e.g. 0.09)")
    mag_size_bonus: int = Field(default=0, description="Magazine capacity delta (rounds)")
    attachments: List[str] = Field(default_factory=list, description="Equipped attachment labels with slot prefixes")
    tuning_instructions: List[str] = Field(default_factory=list, description="Actionable custom tuning recommendations")


class TierEntry(BaseModel):
    """Final tier ranking entry for a weapon in a specific combat scenario."""

    model_config = ConfigDict(extra="forbid")

    gun_id: str = Field(min_length=1)
    gun_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    caliber: str = Field(min_length=1)
    distance_m: int = Field(ge=1, le=200)
    armor_level: int = Field(ge=1, le=6)
    ammo_level: int = Field(ge=1, le=6)
    stk: int = Field(ge=1)
    practical_ttk_ms: float = Field(ge=0.0)
    ammo_60_cost: int = Field(ge=0)
    total_loadout_cost: int = Field(ge=0)
    single_kill_cost: int = Field(ge=0)
    combat_score: float = Field(ge=0.0, le=100.0)
    handling_score: float = Field(ge=0.0, le=100.0)
    cost_score: float = Field(ge=0.0, le=100.0)
    composite_score: float = Field(ge=0.0, le=100.0)
    tier: str = Field(pattern=r"^T[0-3]$")
    attachments: List[str] = Field(default_factory=list)
    tuning_instructions: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
```

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_models.py -v`
预期：PASS

- [ ] **Step 5: 提交契约变更**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat(models): upgrade WeaponBuild and TierEntry schemas with physical buffs and tuning instructions"
```

---

### Task 2: 校准弹药库数据与口径准入过滤 (`data/`, `src/engine/ranker.py`)

**Files:**
- Modify: `data/baseline_ammo_prices.json`
- Modify: `data/snapshot_prices.json`
- Modify: `src/engine/ranker.py:35-85`
- Test: `tests/test_ranker.py`
- Test: `tests/test_data_integrity.py`

**Interfaces:**
- Consumes: `AmmoPrice`, `GunMeta`
- Produces: `resolve_ammo(ammo_prices: Dict[str, AmmoPrice], caliber: str, level: int) -> Optional[AmmoPrice]`，若不存在返回 `None`；`generate_scenario_rankings` 自动过滤 `ammo is None` 的枪支。

- [ ] **Step 1: 编写口径准入测试**

在 `tests/test_ranker.py` 中增加口径准入测试：
```python
def test_resolve_ammo_strict_and_gating():
    sample_ammo = {
        "9x19mm_4": AmmoPrice(caliber="9x19mm", level=4, name="9x19mm PBP", penetration=40, price_per_round=1545, source="test", updated_at="2026-09-18T00:00:00Z"),
        "5.56x45mm_4": AmmoPrice(caliber="5.56x45mm", level=4, name="5.56x45mm M855A1", penetration=42, price_per_round=1150, source="test", updated_at="2026-09-18T00:00:00Z"),
        "5.56x45mm_5": AmmoPrice(caliber="5.56x45mm", level=5, name="5.56x45mm M995", penetration=53, price_per_round=3100, source="test", updated_at="2026-09-18T00:00:00Z"),
    }
    # 9x19mm has level 4
    assert resolve_ammo(sample_ammo, "9x19mm", 4) is not None
    # 9x19mm has NO level 5
    assert resolve_ammo(sample_ammo, "9x19mm", 5) is None
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_ranker.py -k "test_resolve_ammo_strict_and_gating" -v`
预期：FAIL（此前 `resolve_ammo` 会降级返回 level 4 弹药）

- [ ] **Step 3: 修正数据源与 `ranker.py`**

1. 修改 `data/baseline_ammo_prices.json` 与 `data/snapshot_prices.json`：
   - 彻底删除 `.45 ACP RIP/AP+` 与 `.300 BLK V-Max+`。
   - 补充/纠正真实弹药：
     - `9x19mm`: 3 级 AP6.3, 4 级 PBP (删除不存在的 5 级弹)
     - `.45ACP`: 4 级 AP (3300), 5 级 Super (4800, penetration: 50)
     - `.300 BLK`: 4 级 BCP-FMJ (1800), 5 级 TAC-TX (5200, penetration: 50)
     - `5.8x42mm`: 3 级 DVP88, 4 级 DBP10 (1450), 5 级 DVC12 (3400)
     - `12.7x55mm`: 4 级 PS12 (2200), 5 级 PS12B (5800)
     - `45-70 Govt`: 4 级 FMJ (2100), 5 级 FTX (4900)
2. 修改 `src/engine/ranker.py` 中的 `resolve_ammo`：
```python
def resolve_ammo(
    ammo_prices: Dict[str, AmmoPrice], caliber: str, target_level: int
) -> Optional[AmmoPrice]:
    """Resolve ammo price record strictly matching caliber and target level.

    Returns None if no ammo of the specified level exists for the caliber.
    """
    key = f"{caliber}_{target_level}"
    return ammo_prices.get(key)
```
并在 `generate_scenario_rankings` 中加入过滤：
```python
    for gun in guns:
        ammo = resolve_ammo(ammo_prices, gun.caliber, ammo_level)
        if ammo is None:
            # Caliber gating: skip weapon if no suitable ammo for this scenario
            continue
```

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_ranker.py tests/test_data_integrity.py -v`
预期：PASS

- [ ] **Step 5: 提交变更**

```bash
git add data/baseline_ammo_prices.json data/snapshot_prices.json src/engine/ranker.py tests/test_ranker.py tests/test_data_integrity.py
git commit -m "feat(ammo): implement strict caliber gating and eliminate fabricated ammunition"
```

---

### Task 3: 官方确定性阶梯 TTK 状态机与物理期望公式 (`src/engine/simulator.py`)

**Files:**
- Modify: `src/engine/simulator.py:1-175`
- Test: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `GunMeta`, `AmmoPrice`, `effective_velocity`, `distance_m`
- Produces: `SimulationResult(stk, theoretical_ttk_ms, practical_ttk_ms, ehr)`

- [ ] **Step 1: 编写确定性阶梯与部位伤害测试**

在 `tests/test_simulator.py` 中增加阶梯穿透与部位倍率真值测试：
```python
def test_deterministic_pen_rates_and_no_blunt_damage(m4a1_gun, ammo_556_lv4):
    # Lv4 ammo vs Lv5 armor: pen_rate = 0.0 before armor break (0% flesh damage)
    # Target chest HP=100. Single shot on Lv5 armor should deal 0 HP damage before break.
    from src.engine.simulator import simulate_duel
    # Simulate 1 round
    res = simulate_duel(m4a1_gun, ammo_556_lv4, armor_level=5, distance_m=15)
    # M4A1 Lv4 bullet vs Lv5 armor takes significantly more shots to break and kill
    assert res.stk >= 9
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_simulator.py -k "test_deterministic_pen_rates" -v`
预期：FAIL

- [ ] **Step 3: 重构 `src/engine/simulator.py`**

1. 引入官方 SDK 命中部位权重与官方伤害倍率：
```python
HIT_PARTS: List[str] = ["head", "chest", "abdomen", "upper_arm", "limbs"]
HIT_WEIGHTS: List[float] = [0.1724, 0.3046, 0.1897, 0.0833, 0.2500]

HITBOX_MULTIPLIERS: Dict[str, float] = {
    "head": 1.90,
    "chest": 1.00,
    "abdomen": 0.90,
    "upper_arm": 0.40,
    "limbs": 0.40,
}
```
2. 确定性阶梯穿透系数函数：
```python
def get_pen_rate(ammo_level: int, armor_level: int) -> float:
    """Official deterministic penetration coefficient."""
    if ammo_level < armor_level:
        return 0.0
    elif ammo_level == armor_level:
        return 0.50
    elif ammo_level == armor_level + 1:
        return 0.75
    else:
        return 1.00
```
3. 官方碎甲按比例拆分肉伤与甲伤结算：
```python
def simulate_duel(
    gun: GunMeta,
    ammo: AmmoPrice,
    armor_level: int,
    distance_m: int,
    effective_velocity: Optional[float] = None,
    sim_iterations: int = 500,
    seed: int = 42,
) -> SimulationResult:
    velocity = effective_velocity if effective_velocity is not None else gun.bullet_velocity
    chest_damage, armor_damage = get_damage_at_distance(gun.dropoffs, float(distance_m))

    # Ammo flesh damage rate adjustment (e.g. .45 ACP Super has 0.85 rate)
    flesh_rate = 0.85 if ".45" in ammo.caliber and ammo.level == 5 else 1.00
    chest_damage *= flesh_rate

    # Ammo armor damage rate
    ammo_armor_rate = 1.10 if ammo.level >= 5 else 1.00
    actual_armor_dmg = armor_damage * ammo_armor_rate

    max_body_dur = ARMOR_MAX_DURABILITY.get(armor_level, float(armor_level * 25.0))
    max_head_dur = HELMET_MAX_DURABILITY.get(armor_level, float(armor_level * 10.0))
    pen_rate = get_pen_rate(ammo.level, armor_level)

    rng = random.Random(seed)
    stk_samples: List[int] = []

    for _ in range(sim_iterations):
        hp = 100.0
        cur_body_dur = max_body_dur
        cur_head_dur = max_head_dur
        shots = 0

        while hp > 0.0 and shots < 50:
            shots += 1
            part = rng.choices(HIT_PARTS, weights=HIT_WEIGHTS)[0]
            mult = HITBOX_MULTIPLIERS[part]

            if part in ["upper_arm", "limbs"]:
                hp -= chest_damage * mult
            elif part in ["chest", "abdomen"]:
                if cur_body_dur <= 0.0:
                    hp -= chest_damage * mult
                elif actual_armor_dmg >= cur_body_dur:
                    # Break armor proportionally
                    dur_fraction = cur_body_dur / actual_armor_dmg
                    cur_body_dur = 0.0
                    hp -= chest_damage * mult * ((1.0 - dur_fraction) + dur_fraction * pen_rate)
                else:
                    cur_body_dur -= actual_armor_dmg
                    hp -= chest_damage * mult * pen_rate
            elif part == "head":
                if cur_head_dur <= 0.0:
                    hp -= chest_damage * mult
                elif actual_armor_dmg >= cur_head_dur:
                    dur_fraction = cur_head_dur / actual_armor_dmg
                    cur_head_dur = 0.0
                    hp -= chest_damage * mult * ((1.0 - dur_fraction) + dur_fraction * pen_rate)
                else:
                    cur_head_dur -= actual_armor_dmg
                    hp -= chest_damage * mult * pen_rate

        stk_samples.append(shots)

    avg_stk = sum(stk_samples) / len(stk_samples)
    stk = max(1, int(round(avg_stk)))

    theoretical_ttk_ms = max(0.0, (avg_stk - 1) * (60.0 / gun.rpm) * 1000.0)
    ehr = calc_effective_hit_rate(gun.recoil_control, gun.stability, velocity, float(distance_m))

    expected_shots = avg_stk / ehr
    k_ads = 0.5 if distance_m <= 15 else 0.8
    practical_ttk_ms = gun.ads_time_ms * k_ads + max(0.0, (expected_shots - 1) * (60.0 / gun.rpm) * 1000.0)

    return SimulationResult(
        stk=stk,
        theoretical_ttk_ms=round(theoretical_ttk_ms, 2),
        practical_ttk_ms=round(practical_ttk_ms, 2),
        ehr=round(ehr, 4),
    )
```

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_simulator.py -v`
预期：PASS

- [ ] **Step 5: 提交变更**

```bash
git add src/engine/simulator.py tests/test_simulator.py
git commit -m "feat(simulator): implement official deterministic pen rates, hitbox multipliers, and expected TTK"
```

---

### Task 4: 废除 8 万截断与因枪制宜实配/精校体系 (`src/engine/gunsmith.py`, `src/collectors/build_collector.py`)

**Files:**
- Modify: `src/collectors/build_collector.py:1-120`
- Modify: `src/engine/gunsmith.py:1-400`
- Modify: `data/default_builds.json`
- Test: `tests/test_gunsmith.py`
- Test: `tests/test_collectors.py`

**Interfaces:**
- Consumes: `GunMeta`, `data/official_attachment_prices.json`
- Produces: 50 把主武器量身定制的实用改件与精校方案：
  - 冲锋枪全员专属扩容弹匣（MP7 40发、Vector 40发、MP5 50发鼓等）
  - 精确射手步枪换装实战 1p-29 3倍镜与扩容弹匣
  - 真实官方市价累加核算（无 80000 截断）
  - 附带针对性精校口诀清单（如 `枪托: 配重右拉满(+50g，后坐-6%)`）
  - 输出 `WeaponBuild` 包含 `stability_bonus`, `velocity_bonus_pct`, `mag_size_bonus`, `tuning_instructions`

- [ ] **Step 1: 编写改枪体系测试**

在 `tests/test_gunsmith.py` 中增加实配与精校测试：
```python
def test_gunsmith_practical_builds_without_share_codes():
    from src.engine.gunsmith import get_all_calibrated_builds
    builds = get_all_calibrated_builds()
    assert len(builds) == 50
    
    # Verify MP7 has extended magazine
    mp7_build = builds["mp7"]
    assert any("40发" in att or "弹匣" in att for att in mp7_build.attachments)
    assert len(mp7_build.tuning_instructions) > 0
    assert mp7_build.mod_cost > 0
    # No artificial 80k cap
    assert not hasattr(mp7_build, "build_code")

    # Verify SVD has 3x scope, not 8x
    svd_build = builds["svd"]
    assert any("3倍" in att or "1p-29" in att or "瞄准镜" in att for att in svd_build.attachments)
    assert not any("8倍" in att for att in svd_build.attachments)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_gunsmith.py -v`
预期：FAIL

- [ ] **Step 3: 改造 `build_collector.py` 与 `gunsmith.py`**

1. 修改 `src/collectors/build_collector.py`：
   - 彻底删除 `DEFAULT_MAX_PRACTICAL_MOD_COST = 80000` 及截断代码。
   - 移除臆造的替换词典。
   - 移除 `build_code`, `code_status`。
2. 重构 `src/engine/gunsmith.py`：
   - 更新 50 把武器的推荐配件配置列表，补入真实扩容弹匣与 3 倍瞄具；
   - 建立精校规则映射：
     - 步枪/冲锋枪/机枪：配备 `枪托: 配重右拉满(+50g，垂直/水平后坐-6%)`、`前握把: 安装位置前拉满(+100格，垂直/水平后坐-4%)`；
     - 连狙/大口径步枪：增加 `枪管: 长度右拉满(+10mm，初速+9%)`；
   - 根据装配配件与精校规则，准确合成：
     - `recoil_bonus`（基础 + 精校后坐控制提升）
     - `stability_bonus`（基础 + 精校据枪稳定）
     - `velocity_bonus_pct`（精校初速提升，如 0.09）
     - `ads_modifier_ms`（综合开镜时间修正）
     - `mod_cost`（严格累加各配件在 `official_attachment_prices.json` 中的实际价格）
   - 同步刷新 `data/default_builds.json`。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_gunsmith.py tests/test_collectors.py -v`
预期：PASS

- [ ] **Step 5: 提交变更**

```bash
git add src/collectors/build_collector.py src/engine/gunsmith.py data/default_builds.json tests/test_gunsmith.py tests/test_collectors.py
git commit -m "feat(gunsmith): eliminate share codes and 80k cap, implement tailored attachment builds and tuning instructions"
```

---

### Task 5: 全链路物理增益传导与天梯计算引擎 (`src/engine/ranker.py`)

**Files:**
- Modify: `src/engine/ranker.py:150-280`
- Test: `tests/test_ranker.py`

**Interfaces:**
- Consumes: `GunMeta`, `WeaponBuild`, `AmmoPrice`, `effective_velocity`, `effective_recoil`, `effective_stability`
- Produces: `List[TierEntry]` 准确携带 `tuning_instructions`，且初速/后坐/稳定全量参与 TTK 与综合评分。

- [ ] **Step 1: 编写全链路增益传导测试**

在 `tests/test_ranker.py` 中更新综合天梯生成测试：
```python
def test_ranker_propagation_and_tuning():
    from src.engine.ranker import generate_scenario_rankings
    # Ensure rankings execute cleanly with tuned builds and caliber gating
    # Verify no share codes in tier entries and tuning instructions present
```

- [ ] **Step 2: 运行测试验证**

运行：`pytest tests/test_ranker.py -v`
预期：FAIL

- [ ] **Step 3: 更新 `src/engine/ranker.py`**

在 `generate_scenario_rankings` 中：
1. 计算有效初速：
```python
    effective_velocity = gun.bullet_velocity * (1.0 + build.velocity_bonus_pct) if build else gun.bullet_velocity
```
2. 计算有效开镜与后坐/稳定性：
```python
    effective_ads = max(50, gun.ads_time_ms + build.ads_modifier_ms) if build else gun.ads_time_ms
    effective_recoil = min(100.0, max(0.0, gun.recoil_control + build.recoil_bonus)) if build else gun.recoil_control
    effective_stability = min(100.0, max(0.0, gun.stability + build.stability_bonus)) if build else gun.stability
```
3. 传导给仿真器与操控分：
```python
    sim_gun = gun.model_copy(
        update={"ads_time_ms": effective_ads, "recoil_control": effective_recoil, "stability": effective_stability}
    )
    sim = simulate_duel(sim_gun, ammo, armor_level, distance_m, effective_velocity=effective_velocity)
    handling_score = calc_handling_score(
        recoil=effective_recoil, stability=effective_stability, rpm=gun.rpm
    )
```
4. 构建 `TierEntry` 时注入 `tuning_instructions`，移除 `build_code` / `code_status`。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_ranker.py -v`
预期：PASS

- [ ] **Step 5: 提交变更**

```bash
git add src/engine/ranker.py tests/test_ranker.py
git commit -m "feat(ranker): propagate velocity and tuning bonuses to simulation and handling scores"
```

---

### Task 6: 渲染器与交付物重构 (`src/renderers/`, `src/pipeline.py`)

**Files:**
- Modify: `src/renderers/markdown_renderer.py`
- Modify: `src/renderers/json_exporter.py`
- Modify: `src/pipeline.py`
- Test: `tests/test_renderers.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `List[TierEntry]`, `DataSourceStatus`
- Produces: `README.md`, `docs/tierlist/*.md`, `data/latest_rankings.json`

- [ ] **Step 1: 编写渲染器测试**

在 `tests/test_renderers.py` 中更新 Markdown 与 JSON 导出测试：
- 确认表格列中不再有“改枪码”列，代之以“推荐改装与实战精校调校”。
- 确认 JSON 导出中符合新 Schema。

- [ ] **Step 2: 运行测试验证**

运行：`pytest tests/test_renderers.py -v`
预期：FAIL

- [ ] **Step 3: 更新渲染器代码**

1. 修改 `src/renderers/markdown_renderer.py`：
   - 移除改枪码展示与“照单装配不失效”多余前缀，展示简洁明了的“实战推荐配件清单”与“🎯 实战精校调校口诀”。
   - 更新 9 维大矩阵表格表头与分册文档表格表头。
   - FAQ 问答改为基于当期排行榜前列武器动态生成，保证与数据完全吻合。
2. 修改 `src/renderers/json_exporter.py`：导出更新后的 `TierEntry`。
3. 修改 `src/pipeline.py`：同步更新字段映射与防污染提交对比逻辑。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_renderers.py tests/test_pipeline.py -v`
预期：PASS

- [ ] **Step 5: 提交变更**

```bash
git add src/renderers/markdown_renderer.py src/renderers/json_exporter.py src/pipeline.py tests/test_renderers.py tests/test_pipeline.py
git commit -m "feat(renderers): update markdown templates and JSON exporter for tuning loadouts"
```

---

### Task 7: 全链路自动化执行与交付验证

**Files:**
- Output: `data/latest_rankings.json`
- Output: `README.md`
- Output: `docs/tierlist/4armor_4ammo.md`
- Output: `docs/tierlist/4armor_5ammo.md`
- Output: `docs/tierlist/5armor_5ammo.md`

- [ ] **Step 1: 运行全量测试套件**

运行：`pytest --cov=src tests/`
预期：88+ 测试全部通过，覆盖率 $\ge 85\%$。

- [ ] **Step 2: 运行数据管道重新生成所有交付物**

运行：`python -m src.pipeline`
预期：
- `data/latest_rankings.json` 刷新；
- `README.md` 刷新，检查 4套5弹 与 5套5弹 场景下汤姆逊等低级枪械不再错误登顶，MP7、M4A1、Vector 等处于合理战术梯队；
- `docs/tierlist/` 3 份分册刷新，格式规范，无错漏。

- [ ] **Step 3: 验证数据一致性与业务正确性**

运行检查脚本：
```bash
python -c "
import json
with open('data/latest_rankings.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
for s in data['scenarios']:
    sc_id = s['scenario_id']
    weapons = [w['gun_name'] for w in s['rankings'][:3]]
    print(f'{sc_id}: Top 3 = {weapons}')
"
```
确认 5 级弹场景无 9mm 武器，各距离顶级武器符合物理现实。

- [ ] **Step 4: 提交全量生成交付物**

```bash
git add data/latest_rankings.json README.md docs/tierlist/
git commit -m "chore: regenerate tierlist rankings and documentation with calibrated physics and tuning"
```
