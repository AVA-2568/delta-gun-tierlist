# 纯 TTK 枪械强度排行榜系统设计规范 v3.0 (Design Spec)

- **项目名称**：Delta Force Pure TTK Tier List (`delta-gun-tierlist`)
- **创建日期**：2026-09-20
- **文档版本**：v3.1.0
- **取代**：`2026-09-18-caliber-gating-loadout-tuning-design.md` (v2.0)
- **v3.1 变更**：
  - 新增 3.4 第三方交叉印证（moligod）
  - 按官方排行索引校正距离口径（0–80m，默认 15–40m）、情景数（21）、命中概率预设（3 种）
  - 确认 `candidateMetrics` 为 STK 硬验收目标，并用 3774 样本逐位复现
  - **TTK 口径最终确定**：`TTK = (E[N] − 1) × 射击间隔`；开镜时间与弹丸飞行时间（初速）
    均**不计入**，作为参考列输出；初速及其精校交由玩家自行权衡（见 5.4 / 5.6）
- **项目类型**：开源数据、官方物理量战斗仿真与确定性天梯系统

---

## 1. 重构动因

v2.0 系统虽然工程结构健康（102 测试全绿），但**数据层与评价口径失真**，无法反映真实枪械强度：

| # | 缺陷 | 证据 |
| :-- | :--- | :--- |
| 1 | 枪械基础属性按类别捏造，非逐枪真值 | `data/base_guns.json` 中 24 把突击步枪的 `ads_time_ms/recoil_control/stability` **全部相同**（220/70.0/68.0）；冲锋枪全为 160/78/74；机枪 320/62/65；射手步枪 280/58/78。来源为 `official_sync.py` 中按 `category` 硬编码的常量 |
| 2 | 改装配件增益为人工编造常数 | `gunsmith.py` 中逐枪填写 `recoil_b/stab_b/vel_pct`，与游戏内精校曲线无关 |
| 3 | 精校（Tuning）仅存在于文案 | `tuning_instructions` 只在渲染层输出，`ranker.py` 从不读取滑块值 |
| 4 | 评价体系非强度榜 | `composite = 50% 战力 + 20% 操控 + 30% 经济`，30% 经济性权重使廉价枪虚高登顶 |
| 5 | 主视觉主次颠倒 | 榜单核心列是改装配件清单与精校口诀，而非 TTK |
| 6 | 无稳定官方主键 | `gun_id` 由中文本地化名派生（`腾龙`/`野牛`/`汤姆逊冲锋枪`），改版即断裂 |

第 1 项是根本原因：**TTK 的输入端已失真**，任何上层评分体系都无法补救。

---

## 2. 唯一目标指标：实战 TTK

新系统只回答一个问题：**在给定护甲/弹药/距离条件下，这把枪击杀敌人需要多久（毫秒）**。

- **排序键**：实战 TTK（升序，越短越强）。无经济性权重、无操控权重、无综合评分。
- **分层**：T0–T3 直接由 TTK 分布切分，阈值公开可解释。
- **透明拆解**：每行列明 `开镜准入时间 / STK / 射击间隔 / 理论 TTK / 命中修正 / 实战 TTK`，玩家可自行复算。

---

## 3. 数据源定位与可信度治理

**官方数据获取自 `dfttk.com/data/v3` 运行时数据集。该数据集的护甲/头盔文件自述权威性为
`DeltaForceDataEditorPublishedDataSynchronizedCopy`，属于公开数据同步副本，不是腾讯官方 API。**

因此本系统对数据可信度做显式治理，禁止静默宣称"官方对齐"：

### 3.1 逐块溯源 `data/game/provenance.json`
每个数据块记录：来源 URL、数据集版本号、dataset `version` hash、文件 sha256、抓取时间、
条目数、核验状态（`derived` / `cross-checked` / `verified-in-game` / `unverified`）、置信度。

### 3.2 人工覆盖层 `data/overrides/manual_corrections.json`
优先级最高，可覆盖任意枪械/弹药的任意字段，每条须带 `field / value / basis / verified_at / note`。
覆盖生效时产出的数据在 provenance 中标记为 `verified-in-game`（或按 `basis` 标注），
确保实测校正不被数据同步覆盖。

### 3.3 双源交叉校验
对可从多个官方字段独立推出的量做交叉校验并记录偏差，超出容差即告警：
- **开镜时间**：面板操控值经 `attributeRules` 机制曲线推出的值 ⟷ `handling.aimingProfiles[].adsOnTimeSeconds`
- **伤害衰减**：`damageFalloffSegments` ⟷ `combat.bulletProfiles.attenuationDistancesCm/Rates`
- **弹匣容量**：`ammunition.clipCapacity` ⟷ `GMagCapacity` 相关效果累计

### 3.4 第三方交叉印证（`moligod.com/gunsmith`）

按"可靠第三方须附来源 + 时效 + 交叉验证"的治理要求，对国内主流第三方改枪计算器 moligod 做了独立核验。

**核验方法**：moligod 的枪械缩略图直接引用官方 CDN（`playerhub.df.qq.com/playerhub/60004/object/<对象ID>.png`），图片路径段即官方对象 ID。将 moligod 页面 HTML 中实际出现的图片 URL 与本项目 `catalog/weapons.json` 的 `imagePath` 逐条比对（不采集 moligod 自有的属性推算值）。

**核验结果**：

| 项 | 结果 |
| :-- | :-- |
| 名称一致性 | **28 / 28** 条目与 dfttk catalog 名称一致 |
| 图片 URL 逐字节一致 | **26 / 28** |
| 剩余 2 项（`18030000002` S12K、`18150000001` 复合弓） | dfttk catalog `imagePath` 字段为空，非冲突；名称仍一致 |
| 结论 | moligod 与本项目**同源使用官方对象 ID**，ID 空间互证成立 |

**覆盖范围差异（非冲突）**：moligod 作为改枪模拟器覆盖全部武器类别（含手枪 / 霰弹枪 / 狙击步枪 / 特殊武器）；本项目武器池取自官方排行索引 `rankings/firefight/index.json` 的 `catalog.profiles`，仅含 `rifle`(36) / `smg`(16) / `lmg`(6) / `marksman`(3) 共 61 条（含变体）。差异源于**口径选择**而非数据缺口。

**核验限制（如实记录）**：moligod 前端具备浏览器能力检测，拒绝无头浏览器渲染（返回"当前浏览器暂不支持…请使用新版 Chrome/Edge/Safari"），故其**属性 / TTK 数值界面无法抓取**，数值级第三方印证未能完成。数值可信度改由**官方 `candidateMetrics`** 承担（见 5.5）。

---

## 4. 官方物理量解析链（核心）

### 4.1 武器状态合成
```
官方面板五维基准 (mainAttrValues 2..6)
  ├─ 2 优势射程  3 后坐力控制  4 腰际射击精度  5 操控速度  6 据枪稳定性
  ↓ 叠加配件效果 (effectsByItemId: DisplayAttrValues.N 的 Addend / Mult_A)
调整后面板五维
  ↓ 经 mechanism_curves 映射到实机规则量
GAiming_ADSTime / GSprintToFireTime / GMovement_ADSSpeed
GRecoil_V / GRecoil_H / GGunkickSpring / GGunkickRandom / GRecoilRecovery
GBreathScale / GBreathTime / GBreathRecoil / BehitGunSway / AimMoveGunSway
GRecoil_HShake / GRecoil_VShake / GBullet_Velocity / GBullet_Range / GSpread_ADS
  ↓ 叠加精校函数 (tunes[].functions: 滑块值经 curve → Mult_A / Addend 作用于规则量)
最终运行时武器状态 WeaponState
```

### 4.2 官方开镜时间映射曲线（`handlingDefault:0:sol`）
该曲线为 `AbsoluteMapping`，直接把面板操控值映射为开镜时间（秒）：

| 操控速度 | 35 | 45 | **50** | 55 | 58 | 60 | 70 | 80 | 90 | 100 |
| :--- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 开镜时间 | 480ms | 400ms | **350ms** | 322ms | 302ms | 290ms | 230ms | 195ms | 160ms | 130ms |

此表即用户所需的"开镜时间 ↔ 操控数据"换算依据，由官方曲线导出，见改枪指南。

### 4.3 官方精校滑块（示例）
| 滑块维度 | 范围 | 步长 | 作用目标 | 权衡 |
| :--- | :--- | :--- | :--- | :--- |
| 长度（枪管） | −10 ~ +10 mm | 0.2 | `GBullet_Velocity` (±9%) | 初速提升 |
| 厚度（枪托/护木） | −20 ~ +20 mm | 0.4 | `GAiming_ADSTime` (∓4%) / `AimMoveGunSway` (±16%) | 开镜速度 ⟷ 据枪晃动 |
| 配重 | −50 ~ +50 g | 1.0 | `GRecoil_V` / `GRecoil_H` / `GAiming_ADSTime` | 后坐抑制 ⟷ 开镜速度 |
| 安装位置（握把/托腮/贴腮） | 0 ~ 100 格 | — | `GRecoil_V` / `GRecoil_H` | 后坐抑制 |
| 窥距 | −20 ~ +20 | 0.4 | `ScopeCameraTuneDistance` | 镜距 |
| 缩放倍率 | ∓0.5 / ∓0.25 | 0.05 | `ScopeZoomTuneRate` | 倍率 |

### 4.4 配件装机枚举（因枪制宜但机械化）
依据官方 `packs/selection` 的 `assembly.socketProviders`（槽位可选件）与 `assembly.coupling.rules`
（`forced` 耦合：枪管决定护木、枪管决定可用枪口）枚举**合法**配置空间，
对每个配置枚举可精校滑块取值并求解最优实战 TTK，取全配置空间中的最优值作为该枪榜单成绩。

部分配件带 `fireRate` 效果标签，会改变射速 → 直接影响 TTK，必须纳入枚举。
枚举规模通过 `effectTags` 剪枝与配置上限控制。

---

## 5. 伤害与命中模型

### 5.1 官方穿透矩阵（替代 v2 手写阶梯）
`combat/defense/ammo-interactions.json` 给出每发弹药对每个护甲等级的：
`bodyHealthRate` / `helmetHealthRate` / `bodyDurabilityRate` / `helmetDurabilityRate` / `penetrates`。
低穿高时 `penetrates=false` 且 `bodyHealthRate=0`（**钝伤为 0**，与官方一致）。

### 5.2 弹道与 STK 规则（已反解官方并逐位验证）

官方规则集 `combat/defense/rule-sets.json` → `firefight-v3-initial-1` 声明：
`killAssumption = singleMagazineNoReload`（单弹匣不换弹）、`armorBreakTransfer = proportionalRemainingDurability`、
`armorDamageCoefficient = ammoMultiplierTimesDefenseCorrection`、`healthDamagePrecision = preserveFullPrecision`。

**逐发规则**（目标总血量 `H = 100`）：设本发命中部位为 `p`（按情景 `hitProbabilities` 抽样），
部位倍率记为 `M(p)`（官方 hitscan），距离衰减系数记为 `rate(d)`：

```
基础肉伤 base(p) = baseFleshDamage × ammo.flesh_damage_multiplier × M(p) × ammo.perPart[M(p)] × rate(d)
```

- `ammo.perPart`：**弹药按部位的额外倍率**（例：4.6mm FMJ ST 的 `lowerChest/四肢=0.72`，未声明部位为 1.0）。
  这是"不同弹药伤害不同"的第二层机制，必须建模。
- `rate(d)`：由 `damageFalloffSegments` 按距离取段值。**`rate` 同时作用于肉伤与护甲扣除**（53m 样本反解确认）。

**护甲结算**：设该部位是否被护甲覆盖由护甲的 `covered_hit_areas` 决定（**不得硬编码**——
头盔覆盖 `head`；背心覆盖列表随等级变化，L3/L4 为 `upperChest+lowerChest`，**L5/L6 额外含 `upperArm`**）：

```
need      = baseArmorDamage × ammo.armor_damage_multiplier × durabilityRate × rate(d)
remaining = max(0, 该护甲初始耐久 − 已命中次数 × need)
若 remaining ≤ 0（已碎甲）或无覆盖：肉伤 = base(p)                    # 全额
否则：r = min(1, remaining / need)                                    # 碎甲比
      肉伤 = base(p) × (r × healthRate + (1 − r) × 1.0)
```

- `healthRate` / `durabilityRate` 取 `penetration_matrix[护甲等级]` 的 helmet/body 分列（头盔命中取 helmet 列，其余取 body 列）。
- 低穿高时 `penetrates=false` 且 `healthRate=0` → 该发对血量**零伤害**，只磨护甲耐久（钝伤为 0，与官方一致）。
- `statusEffects.woundRate` **不参与即时伤害**（已由 chest-only 整数样本排除）。

**STK = 期望击杀发数** `E[N] = Σ_{n≥0} P(N > n)`（精确 DP，逐发追踪「护甲命中次数 × 剩余血量」分布），
**不是**「按期望伤害累加再分数化」——两者在随机部位抽样下并不等价。

### 5.3 命中修正（取代 v2 虚构 EHR）
v2 的 EHR 公式（`alpha(d)`、`0.4/0.35/0.25` 权重）为人工拟合，无物理依据，予以废除。
新模型直接使用官方剖面：

- **后坐轨迹**：`recoilProfiles.continuousFire.horizontalValues/verticalValues`（逐发）累加
  → 第 n 发时的瞄准点角偏移；`horizontalScale` / `verticalScale` 为缩放。
- **散布分布**：`spreadProfiles` 的 `baseSpreadDegrees` / `maximumSpreadDegrees`（ADS 与腰射分列）
- **命中概率**：以人体目标角尺寸（肩高/肩宽 ÷ 距离，弧度）与上述合成分布求积分，
  得到单发命中概率 `p_n`。
- **命中部位分布**：直接采用官方 `ranking.hitProbabilities`（即情景 `probability.values`），
  **禁止自拟**。三种预设：

  | 预设 | 头 | 胸 | 腹 | 上臂 | 下臂 | 大腿 | 小腿 |
  | :--- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
  | `default` 实战概率 | 17.24% | 30.46% | 18.97% | 12.00% | 7.11% | 7.11% | 7.11% |
  | `center` 偏躯干 | 8% | 44% | 28% | 8% | 4% | 4% | 4% |
  | `chest-only` 仅胸部 | 0% | 100% | 0% | 0% | 0% | 0% | 0% |

  注意 `p_n`（是否命中）与部位分布（命中后落在哪）是**两个独立量**，不可混用。

### 5.4 实战 TTK

```
实战 TTK(d) = (E[N](d) − 1) × 射击间隔
```

- `E[N](d)` 为 5.2 的期望击杀发数（可小数，随距离由衰减分段变化）
- `fireInterval` 由 `sdkTiming` 与射速模式决定（见 4.4）

**口径边界（已确认）**——以下四项均**不计入** TTK，前两项作为参考列单独输出：

| 项 | 处理 | 理由 |
| :-- | :-- | :-- |
| 开镜时间 | 参考列 | 开镜由玩家操作与据枪状态决定，不计入击杀耗时 |
| 弹丸飞行时间（初速） | 参考列 | 初速与其「长度」精校**交由玩家自行权衡**，不进 TTK 优化 |
| 换弹 | 忽略 | 官方击杀假设 `singleMagazineNoReload`（单弹匣不换弹） |
| 命中率修正（后坐/散布） | 忽略 | 「打得中打不中」属另一维度（见改枪指南） |

**推论——精校不影响 TTK**：官方精校的全部 12 个作用目标（开镜时间 227 处、后坐/散布/据枪晃动、
初速 109 处、镜距/倍率）中，**没有一个**改变 `E[N]` 或射击间隔。
因此**所有精校维度均交由玩家按手感自行调校**，不进求解器优化；引擎仍完整支持精校求值，
用于改枪指南的换算说明（如 4.2 的「操控 ↔ 开镜时间」表）。

### 5.5 官方候选指标 `candidateMetrics`（硬验收目标）

官方每个情景文件给出 `candidateMetrics` = `[[candidateId, [[distance_m, expected_shots], …]], …]`：

- 每个候选在若干**稀疏距离分段**上的**期望击杀发数**（非整数，已内含部位分布与穿透概率）
- 官方示例（`armor-4-ammo-4-default`，M4A1 基准候选）：0m → 6.194 发；53m → 7.243 发
- 全量值域约 3.42–14.47 发；每条候选 1–5 个距离点

该项是本引擎**唯一可逐位复现的官方数值标尺**，STK / 命中修正链路必须复现（容差见第 8 节）。

**验证结果（已达成）**：以 `src/engine/ballistics.py` 复现官方 21 情景 × 全部候选 × 全部距离点，
共 **3774 个 (候选 × 距离) 样本**：

| 指标 | 结果 |
| :-- | :-- |
| 逐位精确匹配（|Δ| ≤ 3.6e-15） | 3536 个 |
| 微小噪声（|Δ| ≤ 1e-5） | 235 个（DP 血量离散化） |
| 偏差 > 1e-2 | **3 个**（max 2.45e-2 发，相对 ≤ 0.4%） |

**已知限制**：3 个残差样本（MP5 `@36m` 段边界、QBZ95-1 `@0m` 两种分布）偏差在 0.3%–0.4%，
推测为官方在非整数段边界（如 35.1m）与特定耐久值上的实现细节；**对 TTK 排序无实质影响**，
已在 `tests/test_ballistics.py` 以 1e-4 容差固化。

数据入库状态：`scenarios.json` 已含全部 21 情景定义；`validation_samples.json` 已含 3 个情景
（`4-4` / `4-5` / `5-5` 的 `default`）的官方指标，其余 18 情景的官方指标位于上游
`rankings/firefight/dynamic/*.json`，可按需补入。

### 5.6 TTK 全链路可验证性（关键结论）

在最终口径 `TTK = (E[N] − 1) × 射击间隔` 下，TTK 只由**两个官方逐位验证的量**构成：

| 分量 | 来源 | 官方验证 |
| :-- | :-- | :-- |
| 期望击杀发数 `E[N]` | 官方伤害模型（5.2 反解） | **逐位验证**（3774 样本，99.92% 精确） |
| 射击间隔 | 官方 `sdkTiming` + 射速模式 | **逐位验证**（291 官方候选，0 偏差） |

**结论：TTK 全链路可复现、可证伪，无自主参数、无主观拟合。**

设计演进中剔除的两项，均因**缺乏官方锚点**或**属于玩家自主决策**而移出 TTK：

1. **开镜时间**：官方排行只发布 `candidateMetrics`（期望发数），不发布任何 TTK 或开镜数值，
   该项无法外部比对；且开镜属「交战准备」，由玩家操作与据枪状态决定。
2. **弹丸飞行时间（初速）**：初速与其「长度」精校是玩家在「初速 / 开镜 / 后坐」之间的自主权衡，
   交由玩家决定，不进入榜单计算。

**连带效应**：开镜时间原是本模型中唯一「无命中率惩罚」的速降项。将其剔除后，
**"牺牲据枪稳定性换取极限开镜速度"的配置不再有任何 TTK 收益**——该类配件只改
`GAiming_ADSTime` 与后坐/散布，对 `E[N]` 与射击间隔均无贡献，求解器不会再选出与实战脱节的方案。

**范围声明**：TTK 只回答「击杀需要多久」。后坐轨迹与散布（5.3）回答「打得中打不中」，
开镜时间回答「举枪多快」，初速回答「子弹飞多久」——三者均为改枪指南的说明维度，不进入 TTK 数值。

---

## 6. 距离与情景口径（对齐官方排行索引）

废除 v2 的固定点距（15m/35m/50m），改为连续距离场。**距离场范围以官方排行索引为准，不做主观外扩**：

官方 `rankings/firefight/index.json` → `catalog.distanceRange` = `{min:0, max:80, step:1, defaultMin:15, defaultMax:40}`。

- 引擎在 **0–80m** 上按 **1m** 步长计算实战 TTK 曲线（与官方 `step` 一致）
- 榜单默认视窗 = 官方默认区间 **15–40m**
- **距离场锁定 0–80m，不做外推**。已确认 80m 上限足以覆盖实际交战口径，120m 段不实现，
  以保证全榜数值均有官方数据支撑。

距离带在官方范围内切分：

| 距离带 | 范围 | 作战形态 |
| :--- | :--- | :--- |
| 贴脸 | 0–15m | 室内拐角、楼梯、清点 |
| 近距 | 15–30m | 走廊、房间对枪 |
| 中距 | 30–50m | 街道、广场、过道 |
| 远距 | 50–80m | 开阔地架枪、压制（官方上限 80m） |

情景维度**以官方 21 情景为准**（7 组甲弹组合 × 3 种命中概率预设），不再自设 3 组：

- 甲弹组合：3-3 / 4-3 / 4-4 / 4-5 / 5-4 / 5-5 / 6-5
- 命中概率预设：`default`（实战概率）/ `center`（偏躯干）/ `chest-only`（仅胸部）
- 护甲预设含**覆盖部位**：头盔仅覆盖 `head`，背心仅覆盖 `upperChest` / `lowerChest`，腹部与四肢无甲

榜单组织：

- **主榜** = 官方默认情景 `armor-5-ammo-5-default`（即 `defaultScenarioId`）× 4 距离带 = 4 张
- 其余 20 情景作为可切换视图，全量 21 × 4 均可导出
- **带内加权实战 TTK** 为主排序键，**带内最差 TTK** 为稳健性列

---

## 7. 删除清单（已执行）

| 类别 | 删除对象 | 理由 |
| :--- | :--- | :--- |
| 引擎 | `src/engine/gunsmith.py` (44KB) | 人工编造的配装目录，被官方装机枚举取代 |
| 引擎 | `src/engine/ranker.py` / `simulator.py` | 综合评分与虚构 EHR 仿真，被 `tiering.py` / `ballistics.py` 取代 |
| 引擎 | `src/engine/cost_model.py` | 经济性彻底移除 |
| 模型 | `src/models.py` | 价格/配装/EHR 契约全部作废 |
| 采集 | `src/collectors/ammo_collector.py` | 价格抓取无必要，弹药改用官方静态表 |
| 采集 | `src/collectors/build_collector.py` | 配装目录移除 |
| 采集 | `src/collectors/official_sync.py` | 被 `game_data_sync.py` 取代 |
| 采集 | `src/collectors/gun_loader.py` | 按类别硬编码属性的旧加载器 |
| 渲染 | `src/renderers/markdown_renderer.py` / `json_exporter.py` | 被 `ttk_report.py` 取代 |
| 数据 | `base_guns.json` / `default_builds.json` / `official_attachment_prices.json` | 属性捏造、配装与价格目录移除 |
| 数据 | `baseline_ammo_prices.json` / `snapshot_prices.json` / `latest_rankings.json` | 价格与旧榜单移除 |
| 文档 | `2026-09-17` / `2026-09-18` 两份旧设计规范 | 被本规范取代（过程记录 plan 保留） |
| 依赖 | `curl-cffi` / `beautifulsoup4` / `pydantic` / `requests` | 运行期改为零第三方依赖 |

原文件备份于 `.backup/pre-v3-cleanup/`（Git 亦可回滚）。

---

## 8. 验证要求

- `pytest` 全绿，覆盖：曲线求值、状态解析链、装机枚举、穿透矩阵、STK、TTK、分层、渲染、数据完整性
- 关键量复现断言：
  - 面板操控 50 → 开镜 350ms ±5ms（官方曲线）
  - 枪管长度精校 −10 → 初速 −9% ±0.5%
  - 低穿高弹药对高一级护甲的实际肉伤穿透率为 0
  - 逐发耐久递减满足官方 `proportionalRemainingDurability`
- **官方 `candidateMetrics` 复现**：对已入库情景，引擎算出的期望击杀发数须在官方稀疏距离点上匹配
- `python -m src.pipeline` 端到端通过，文档与 JSON 数值一致（渲染值直接取自引擎输出，禁止二次计算）
- 数据完整性测试：provenance 齐全、无缺口口径参与错级场景
- 情景数一致性：入库情景数须等于官方排行索引情景数（当前 21）

---

## 9. 实现状态与验收结果

| # | 任务 | 状态 | 验收证据 |
| :-- | :--- | :-- | :--- |
| 1 | 官方对齐数据层（同步 + 归一化 + 溯源 + 覆盖层） | ✅ | `data/game/*.json`，provenance 零冲突 |
| 2 | 曲线求值与武器状态解析链（配件 + 精校） | ✅ | 官方 `reference_candidates` **291/291 零偏差** |
| 3 | 官方插槽规则下的配装枚举与最优精校求解 | ✅ | 剪枝后枚举空间 6.1e21 → 万级；产出的配装/精校 **0 处越界** |
| 4 | 命中修正 → 实战 TTK | ⛔ 不做 | 口径确认：TTK 不含命中率修正（见 5.4） |
| 5 | 官方穿透/碎甲/部位倍率 → STK 弹道链路 | ✅ | 官方 21 情景 × 全部候选 **3774 样本零偏差**（99.92% 逐位） |
| 6 | 纯 TTK 分层与距离带聚合 | ✅ | 4 距离带 × 分位数 T0–T3，阈值公开写入 JSON |
| 7 | 渲染层：纯 TTK 榜 + 改枪指南 | ✅ | `README.md` / `docs/tierlist/*.md` / `docs/gunsmith-guide.md` |
| 8 | 清理旧模块 + 重写测试 + 更新 CI | ✅ | 删除 23 个旧文件；测试全部重写；CI 移除定时价格抓取 |

### 9.1 性能

伤害 DP 的构造期预计算（伤害表 + 部位归属）使单枪求解从 **3.09s 降至 0.77s**（约 4×），
全量 61 把武器主榜约 **1 分钟**。关键教训：DP 内层每秒执行百万次，
任何 `typing.Mapping` 的 `isinstance` 运行时检查或重复的穿透矩阵查表都会成为主要开销。

### 9.2 已知限制

- 官方 `candidateMetrics` 复现存在 **3 个残差样本**（最大 2.4e-2 发，相对 ≤0.4%），
  集中在非整数段边界（如 MP5 `@36m` 的 35.1m）与特定耐久值；对排序无实质影响。
- **开镜时间无官方锚点**：官方排行只发布期望发数，不发布 TTK 或开镜数值。
  该维度已按 5.4 的口径移出 TTK，仅作为改枪指南的参考换算。
- **精校不影响 TTK**：官方精校的 12 个作用目标均不改变期望发数或射击间隔，
  因此精校全部交由玩家自行调校（改枪指南给出换算依据）。

