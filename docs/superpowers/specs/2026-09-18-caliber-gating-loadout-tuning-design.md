# 三角洲行动枪械梯度天梯与实战改枪精校系统设计规范 v2.0 (Design Spec)

- **项目名称**：Delta Force Weapon Tier List & Tactical Gunsmithing System (`delta-gun-tierlist`)
- **创建日期**：2026-09-18
- **文档版本**：v2.0.0
- **项目类型**：开源数据、战斗仿真状态机与自动化天梯系统

---

## 1. 业务背景与重构核心目标

在《三角洲行动》（Delta Force: Operations 烽火地带模式）实战中，早期系统的数值计算存在四项严重失真：
1. **虚构高级穿甲弹导致榜首虚假倒挂**：原数据中臆造了不存在的 `.45 ACP RIP/AP+` 和 `.300 BLK V-Max+`，导致汤姆逊冲锋枪在 5 级弹场景虚假登顶；
2. **伤害与破甲机制套用了塔科夫式概率公式**：错误使用了 Sigmoid 穿透概率和 15% 钝伤，与官方 SDK 的确定性分级阶梯算法和 0% 钝伤相割裂；
3. **改枪码维护成本高且实际易失效**：改枪码需依赖官方服务端鉴权签名，离线无法更新且随版本更迭极易失效；
4. **配件成本强行截断 80,000 与配件增益断链**：改枪方案千篇一律，配件造价被强行限制，且丢失了稳定性增益和官方精校（Tuning）白嫖后坐力的机制。

### 核心重构目标：
1. **口径准入机制 (Caliber Gating)**：彻底清除虚构弹药，建立严格的口径准入门槛，无 5 级弹口径的武器不参与 5 级弹场景天梯。
2. **官方确定性阶梯 TTK 状态机**：严格按官方 dfttk SDK 解包算法实现阶梯穿透判定、碎甲比例拆分与部位倍率真值。
3. **废除改枪码，全面转向“因枪制宜实价装配方案 + 官方精校口诀”**：移除不可靠的改枪码，提供真实市场计价的配件清单，并附带针对性精校说明。
4. **全链路配件物理增益与精校合成**：将配件基础加成与精校滑块增益（初速提升、开镜微调、后坐压制、扩容弹匣）完整传导至实战 TTK 仿真与评分体系。

---

## 2. 弹药体系校准与口径准入机制 (Caliber Gating)

### 2.1 弹药基准库纠正
彻底清除 `data/baseline_ammo_prices.json` 和 `data/snapshot_prices.json` 中的虚构弹药，全量对齐官方 114 种弹药元数据：
- **9x19mm**：最高仅有 4 级弹 **PBP**（穿透 40），无 5 级弹；3 级弹为 **AP6.3**。
- **.45 ACP**：4 级弹为 **AP**（穿透 40），5 级弹为官方 **Super**（穿透 50，肉伤倍率 0.85）。删除虚构的 RIP/AP+。
- **.300 BLK**：4 级弹为 **BCP-FMJ**（穿透 40），5 级弹为官方 **TAC-TX**（穿透 50）。删除虚构的 V-Max+。
- **5.8x42mm**：纠正历史错误：**DVP88 是 3 级弹**；真实 4 级弹为 **DBP10**，5 级弹为 **DVC12**。
- **12.7x55mm**：4 级弹为 **PS12**，5 级弹为 **PS12B**。
- **45-70 Govt**：4 级弹为 **FMJ**，5 级弹为 **FTX**。

### 2.2 场景准入过滤逻辑 (`src/engine/ranker.py`)
在计算特定场景（如 4套5弹、5套5弹）时，若某武器口径在当前弹药库中不存在该等级弹药，`resolve_ammo` 返回 `None`，天梯计算引擎直接跳过该武器在该场景下的排名：
```python
def resolve_ammo(ammo_prices: Dict[str, AmmoPrice], caliber: str, level: int) -> Optional[AmmoPrice]:
    key = f"{caliber}_{level}"
    return ammo_prices.get(key)
```
- 结果：Vector 9mm、MP5、野牛等 9x19mm 武器将仅在“4套4弹”场景中展现近战统治力，不会在 5 级局中虚假登顶。

---

## 3. 官方底层确定性阶梯 TTK 状态机

### 3.1 官方穿透率阶梯 (`pen_rate`)
废除塔科夫式的 Sigmoid 曲线，采用官方 SDK 确立的离散阶梯穿透率：
- **低穿高（弹等级 < 甲等级）**：`pen_rate = 0.0`。护甲打碎前，肉体伤害扣减为 **0%**（**钝伤为 0**）。
- **同级对抗（弹等级 == 甲等级）**：`pen_rate = 0.50`（50% 肉伤穿透）。
- **高穿低 1 级（弹等级 == 甲等级 + 1）**：`pen_rate = 0.75`（75% 肉伤穿透）。
- **高穿低 2 级及以上或护甲碎裂**：`pen_rate = 1.00`（100% 全额肉体伤害）。

### 3.2 分段碎甲机制 (Proportional Durability Break)
当单发实际甲伤超过当前护甲剩余耐久（$D_{\text{cur}}$）时发生碎甲：
$$f_{\text{armored}} = \frac{D_{\text{cur}}}{\text{actual\_armor\_dmg}}$$
$$\text{damage} = \text{chest\_damage} \times \text{hitbox\_mult} \times \left[ (1 - f_{\text{armored}}) \times 1.0 + f_{\text{armored}} \times \text{pen\_rate} \right]$$
护甲耐久归零，后续子弹全部按 100% 结算。

### 3.3 官方部位倍率真值 (Hitbox Multipliers)
- **头部 (Head, 17.24%)**：**1.90x**（受到头盔防护，计算头盔穿透与耐久损耗）。
- **胸部 (Chest, 30.46%)**：**1.00x**（受到胸部防弹衣防护）。
- **腹部 (Abdomen, 18.97%)**：**0.90x**（全甲保护；若半甲则裸露受到全额 0.90x 直伤）。
- **四肢 (Upper Arm 8.33%, Limbs 24.97%)**：**统一为 0.40x**（无护甲直伤，低倍率惩罚）。

### 3.4 实战 TTK 期望公式
$$\text{Expected Shots} = \frac{\text{STK}}{\text{EHR}}$$
$$\text{TTK}_{\text{practical}} = \text{effective\_ads} \times k_{\text{ads}} + \max\left(0, \, (\text{Expected Shots} - 1) \times \frac{60}{\text{RPM}} \times 1000\right)$$
- $k_{\text{ads}}$ 在 15m 取 0.5，在 35m/50m 取 0.8。

---

## 4. 实装配件方案、精校系统与模型契约升级

### 4.1 彻底废除改枪码与 8 万截断
- 移除 `build_code`、`code_status` 字段。
- 移除 `build_collector.py` 中 `new_cost = 80000` 强行截断，方案总成本严格等于各配件在 `official_attachment_prices.json` 中的单价之和。

### 4.2 数据模型契约升级 (`src/models.py`)
```python
class TuningSetting(BaseModel):
    dimension: str          # 如 "配重" / "安装位置" / "长度"
    value: float            # 如 50.0, 10.0
    unit: str               # 如 "g", "mm", "格"
    effect_summary: str     # 如 "垂直/水平后坐-6%"

class WeaponBuild(BaseModel):
    gun_id: str
    build_name: str
    mod_cost: int                                       # 真实配件市场造价之和
    ads_modifier_ms: int = 0                            # 综合开镜耗时修正 (ms)
    recoil_bonus: float = 0.0                           # 综合后坐控制加成 (基础+精校)
    stability_bonus: float = 0.0                        # 综合据枪稳定度加成 (基础+精校)
    velocity_bonus_pct: float = 0.0                     # 子弹初速加成比例 (如 +0.09)
    mag_size_bonus: int = 0                             # 弹匣扩容增益 (发)
    attachments: List[str] = Field(default_factory=list)# 真实配件清单
    tuning_instructions: List[str] = Field(default_factory=list) # 精校实战口诀

class TierEntry(BaseModel):
    # 继承原有字段，移除 build_code, code_status，新增：
    tuning_instructions: List[str] = Field(default_factory=list)
```

### 4.3 因枪制宜的实战配件与精校设计 (`src/engine/gunsmith.py`)
1. **高射速冲锋枪 (MP7, Vector, MP5, UZI 等)**：
   - 必须加装专属扩容弹匣（MP7 40发、Vector 40发、MP5 50发鼓），解决原厂 30 发瞬间泼空暴毙痛点；
   - 配件：短款轻型制退器 + 实用垂直/阻手器 + 实用反射式瞄具 + 扩容弹匣；
   - 精校：前握把靠前 (+100格，后坐-4%)，枪托配重右拉满 (+50g，后坐-6%)。
2. **精确射手步枪 (SVD, M14, SR-25, SVCH 等)**：
   - 全面换装实战泛用性最佳的 **1p-29 俄制3倍瞄准镜** 或 **实用3倍瞄准镜**，拆除开镜笨重、视野狭窄的 8 倍镜；
   - 补装 20 发扩容弹匣与重型消音器/制退器；
   - 精校：枪管长度右拉满 (+10mm，初速+9%)，枪托配重右拉满 (+50g，后坐-6%)。
3. **大后坐突击步枪 (AKM, PTR-32, MK47, ASh-12 等)**：
   - 重点压制垂直跳动：钢制多口制退器 + 实用垂直握把 + 全息二型 + 实用稳定托；
   - 精校：枪托配重 (+50g，后坐-6%)，前握把 (+100格，后坐-4%)。
4. **全能均衡步枪 (M4A1, K416, AUG, MDR 等)**：
   - 均衡平民件：钢制制退器 + 实用垂直握把 + 全息二型 + 30/45发聚合物弹匣；造价控制在 3.5w ~ 5.5w 真实市场价。

### 4.4 物理增益全链路传导
在 `src/engine/ranker.py` 中：
- `effective_velocity = gun.bullet_velocity * (1.0 + build.velocity_bonus_pct)` $\implies$ 传入 `calc_effective_hit_rate`，初速提高直接改善中远距离有效命中率；
- `effective_recoil = gun.recoil_control + build.recoil_bonus` $\implies$ 显著改善散布；
- `effective_ads = max(50, gun.ads_time_ms + build.ads_modifier_ms)` $\implies$ 影响起手瞄准时间；
- `handling_score` 全面采用合成后的后坐力与据枪稳定性。

---

## 5. 渲染层与交付物规范

1. **`README.md` 与分册文档 (`docs/tierlist/*.md`)**：
   - 移除所有“改枪码”列和代码，改为展示“最优高性价比配件清单（实战推荐）”与“精校口诀（调校要点）”；
   - 价格数据展示真实市场改装造价，取消 8 万人为截断；
   - FAQ 问答改为基于当期跑分结果动态引用，保证文案与天梯数据 100% 吻合。
2. **结构化数据 (`data/latest_rankings.json`)**：
   - 移除 `build_code`、`code_status`，增加 `tuning_instructions`。

---

## 6. 验证命令与测试用例规划

- 单元测试全量更新与扩充：
  - `tests/test_simulator.py`：验证阶梯确定性穿透率（低穿高 0% 肉伤）、部位倍率真值（头 1.9x、四肢 0.4x）、碎甲比例结算与实战 TTK 期望公式。
  - `tests/test_ranker.py`：验证口径准入机制（5 级弹对局自动过滤 9x19mm 武器）、精校增益对 TTK 和操控分的影响。
  - `tests/test_gunsmith.py`：验证 50 把武器均包含扩容/3倍镜的合理配件配置与精校说明，造价据实核算。
  - `tests/test_models.py` & `test_pipeline.py`：验证 schema 变更与全链路输出。
- 验收标准：
  - `pytest` 全部测试 100% 通过（预计覆盖率 $\ge 85\%$）；
  - 全链路执行 `python -m src.pipeline` 重新生成天梯，文档与 JSON 均成功刷新且数据无倒挂。
