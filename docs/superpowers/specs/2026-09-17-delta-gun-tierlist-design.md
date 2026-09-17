# 三角洲行动枪械梯度排行榜与60发备弹性价比系统设计规范 (Design Spec)

- **项目名称**：Delta Force Weapon Tier List & Cost-Effectiveness System (`delta-gun-tierlist`)
- **创建日期**：2026-09-17
- **文档版本**：v1.0.0
- **项目类型**：开源数据与自动化 Markdown 文档仓库（GitHub Actions 驱动）

---

## 1. 项目概述与核心目标

### 1.1 业务背景
《三角洲行动》（烽火地带玩法）中，护甲穿透、距离伤害衰减以及弹药/改枪经济成本是决定对局胜负与起枪收益的核心因素。玩家在不同预算和作战距离下，急需一份科学、动态、考虑 60 发备弹战术消耗成本的客观天梯指南。

### 1.2 核心目标
1. **多维度对抗场景切片**：
   - **3 种主流甲弹对局**：4套对4弹（常规主力）、4套对5弹（高穿压制）、5套对5弹（顶级对抗）。
   - **3 种典型交战距离**：近距离（15m CQB）、中距离（35m 对枪）、远距离（50m 架枪）。
2. **科学的性价比经济学模型**：
   - 统一采用 **「裸枪成本 + 实用合理改装成本 + 60发备弹消耗」** 作为标准起枪战术单元。
   - 兼顾展示「单次理论击杀弹药成本（$\text{STK} \times \text{单发价格}$）」。
3. **加权综合指数评分（0~100分）**：
   - 结合逐发破甲仿真 TTK、距离有效命中率（EHR）、操控容错率与起枪总造价，计算全枪械客观评分并划分 T0~T3 梯队。
4. **高抗脆弱性与零运维自动化**：
   - 依托 GitHub Actions 定时执行，集成三级容灾降级（在线抓取 $\rightarrow$ 历史快照 $\rightarrow$ 本地基准库），自动渲染面向玩家的 `README.md` 与分册文档，同时沉淀开放 JSON 数据。

---

## 2. 系统整体架构与目录规划

### 2.1 目录结构
```
delta-gun-tierlist/
├── .github/
│   └── workflows/
│       └── update.yml             # GitHub Actions 定时运行流水线
├── data/
│   ├── base_guns.json             # 枪械基础性能底表（源自 dfttk.com 结构化提取）
│   ├── default_builds.json        # 热门实用改装方案与改枪码底表（基准与容灾）
│   ├── baseline_ammo_prices.json  # 弹药基准官方/商人参考价底表
│   ├── snapshot_prices.json       # 上一次成功抓取的弹药与配件市场价格快照
│   └── latest_rankings.json       # 最终生成的全场景 9 维结构化天梯数据
├── src/
│   ├── __init__.py
│   ├── collectors/                # 数据采集层
│   │   ├── __init__.py
│   │   ├── ammo_collector.py      # zxfps.com 实时弹药行情抓取器
│   │   ├── build_collector.py     # 实用改枪方案与配件市价抓取/归一化器
│   │   └── gun_loader.py          # 枪械元数据与衰减曲线加载器
│   ├── engine/                    # 核心计算层
│   │   ├── __init__.py
│   │   ├── simulator.py           # 逐发破甲状态机与实战 TTK 仿真器
│   │   ├── cost_model.py          # 起枪总成本与击杀成本折算器
│   │   └── ranker.py              # 加权综合指数评分与梯队归类引擎
│   └── renderers/                 # 渲染展示层
│       ├── __init__.py
│       ├── markdown_renderer.py   # 生成 README.md 与 docs/ 分册报告
│       └── json_exporter.py       # 导出 API 规范 JSON 数据
├── docs/
│   └── tierlist/                  # 9 维细分场景矩阵文档
│       ├── 4armor_4ammo.md
│       ├── 4armor_5ammo.md
│       └── 5armor_5ammo.md
├── tests/
│   ├── test_simulator.py          # 破甲仿真器单元测试
│   ├── test_cost_model.py         # 成本模型测试
│   └── test_collectors.py         # 采集解析与容灾降级测试
├── requirements.txt               # 运行依赖
├── pyproject.toml                 # 项目元配置
└── README.md                      # 项目主入口展示页
```

---

## 3. 数据模型定义 (Data Schemas)

系统使用 Pydantic 进行全量数据契约约束与验证。

### 3.1 枪械基础模型 (`GunMeta`)
```python
from pydantic import BaseModel, Field
from typing import List, Dict

class DamageDropoff(BaseModel):
    max_distance: float       # 衰减起始/截止距离（米）
    chest_damage: float       # 胸部基础肉伤
    armor_damage: float       # 护甲耐久削减值

class GunMeta(BaseModel):
    id: str                   # 枪械唯一标识（如 "m4a1", "vector", "svd"）
    name: str                 # 枪械中文名称
    category: str             # 类别：突击步枪 / 冲锋枪 / 精确射手步枪 / 机枪
    caliber: str              # 弹药口径（如 "5.56x45mm", "9x19mm", "7.62x51mm"）
    rpm: int                  # 射速（发/分钟）
    bullet_velocity: float    # 子弹初速 (m/s)
    base_price: int           # 裸枪指导参考价（哈夫币）
    default_mag_size: int     # 默认/实用弹匣容量
    ads_time_ms: int          # 开镜时间 (毫秒)
    recoil_control: float     # 垂直/水平后坐控制综合评分 (0~100)
    stability: float          # 瞄准走火稳定度 (0~100)
    dropoffs: List[DamageDropoff] # 距离衰减区间表
```

### 3.2 弹药价格模型 (`AmmoPrice`)
```python
class AmmoPrice(BaseModel):
    caliber: str              # 口径
    level: int                # 弹药等级 (4 或 5)
    name: str                 # 弹药完整名称
    penetration: int          # 穿透等级数值 (如 40, 50)
    price_per_round: int      # 市场单发价格 (哈夫币)
    source: str               # 数据源标识 ("zxfps_live", "snapshot", "baseline")
    updated_at: str           # ISO-8601 时间戳
```

### 3.3 改装方案模型 (`WeaponBuild`)
```python
class WeaponBuild(BaseModel):
    gun_id: str
    build_name: str           # 方案名称（如 "高性价比实用战备改"）
    build_code: str           # 游戏内改枪码（供玩家直接导入）
    mod_cost: int             # 改装配件总造价（哈夫币）
    ads_modifier_ms: int      # 改装对开镜时间的影响
    recoil_bonus: float       # 改装后坐优化增益
```

### 3.4 最终评级条目 (`TierEntry`)
```python
class TierEntry(BaseModel):
    gun_id: str
    gun_name: str
    category: str
    distance_m: int           # 15, 35, 50
    armor_level: int          # 4 或 5
    ammo_level: int           # 4 或 5
    stk: int                  # 击杀所需发数 (Shots to Kill)
    practical_ttk_ms: float   # 经距离与操控修正后的实战击杀时间 (ms)
    ammo_60_cost: int         # 60发备弹成本 (哈夫币)
    total_loadout_cost: int   # 裸枪+改装+60发备弹总成本 (哈夫币)
    single_kill_cost: int     # 单次击杀消耗弹药成本 (哈夫币)
    combat_score: float       # 战力效能分 (0~100)
    handling_score: float     # 操控容错分 (0~100)
    cost_score: float         # 经济性价比分 (0~100)
    composite_score: float    # 加权综合得分 (0~100)
    tier: str                 # "T0", "T1", "T2", "T3"
    build_code: str           # 推荐实用改枪码
    tags: List[str]           # 特性标签，如 ["近战撕裂", "高容错", "平民首选"]
```

---

## 4. 数据采集与三级容灾降级体系

为解决 GitHub Actions 海外数据中心 IP 容易遭遇国内数据站（`zxfps.com` 等）WAF 人机验证或 403 阻断的问题，流水线采用严格的三级降级策略：

```
Level 0: 在线实时爬虫 (Live Fetch via curl_cffi / JA3)
   │
   ├── [成功 & Pydantic 校验通过] ──► 刷新 data/snapshot_prices.json ──► 正常流
   │
   └── [网络失败 / HTTP 403/429 / 校验异常]
          │
          ▼ 触发熔断
Level 1: 历史快照降级 (Fallback to data/snapshot_prices.json)
   │
   ├── [快照可用] ──► 打上 [Snapshot Cache] 标记 ──► 进入计算
   │
   └── [快照损坏或缺失]
          │
          ▼ 触发深度兜底
Level 2: 本地固化基准库 (Fallback to data/baseline_ammo_prices.json)
          └──► 打上 [Baseline Fallback] 标记 ──► 生成警告横幅并继续构建
```

### 配件防溢价过滤器 (Overprice Normalizer)
针对爬取的改枪方案中可能存在的冷门稀有高溢价配件（如天价握把、稀有枪托），系统内置配件平替字典。当某配件价格高于同类基准 3 倍且后坐控制提升 $< 3\%$ 时，自动替换为平民实用件，确保“合理改装”的现实参考意义。

---

## 5. 核心战斗仿真与实战 TTK 模型

废弃静态简单 DPS 除法，采用**离散逐发状态机仿真器（Bullet-by-Bullet Simulator）**。

### 5.1 破甲机制与状态转移
设护甲最大耐久为 $D_{\max}$，实时耐久为 $D_t$，胸部基础 HP 为 100：
1. **未击穿（跳弹/护甲吸收）**：
   - 护甲耐久削减：$\Delta D = \text{ammo.armor\_dmg} \times \text{armor.blunt\_loss\_factor}$
   - 传导钝伤：$\Delta \text{HP} = \text{ammo.flesh\_dmg} \times \text{armor.blunt\_ratio}$ (通常为 10%~20%)
2. **完全穿透**：
   - 扣除全额肉体伤害：$\Delta \text{HP} = \text{ammo.flesh\_dmg} \times \text{armor.pen\_ratio}$
   - 护甲磨损：$\Delta D = \text{ammo.armor\_dmg} \times \text{armor.pen\_loss\_factor}$
3. **穿透概率突变函数**：
   - 随着 $\frac{D_t}{D_{\max}}$ 降低至临界阈值（35%以下），击穿率呈 S 型 Logistic 曲线跃升，直至 100% 击穿。
4. **击杀弹数（STK）**：累积伤害使 HP 降为 0 时的总发射发数。

### 5.2 有效命中率（Effective Hit Rate, EHR）距离衰减模型
在 35m 与 50m，考虑弹道散布与初速对实战命中的衰减：
$$\text{EHR}(d) = \min\left(1.0, \, \alpha(d) \cdot \left[ 0.4 + 0.35 \times \frac{\text{recoil\_control}}{100} + 0.25 \times \frac{\text{stability}}{100} \right] \cdot \sqrt{\frac{\text{velocity}}{600}} \right)$$
- **15m**：$\alpha(15) = 1.0$，EHR 在 0.95~1.0 之间。
- **35m**：$\alpha(35) = 0.85$。冲锋枪因初速低、散布大，EHR 显著下跌（约 0.45~0.60），突击步枪维持 0.75~0.85。
- **50m**：$\alpha(50) = 0.65$。冲锋枪受到惩罚，精确射手步枪与大口径步枪体现出距离优势。

### 5.3 实战 TTK 计算
$$\text{TTK}_{\text{practical}} = \text{ADS\_Time} \times k_{\text{ads}} + \frac{(\text{STK} - 1) \times \frac{60.0}{\text{RPM}}}{\text{EHR}(d)}$$
*注：$k_{\text{ads}}$ 在 15m 取 0.5（部分腰射预瞄），在 35m/50m 取 0.8。*

---

## 6. 经济学与加权综合指数评分公式

### 6.1 成本构成
$$\text{Cost}_{\text{loadout}} = \text{Cost}_{\text{base\_gun}} + \text{Cost}_{\text{practical\_mod}} + 60 \times \text{Price}_{\text{ammo}}$$
$$\text{Cost}_{\text{single\_kill}} = \text{STK} \times \text{Price}_{\text{ammo}}$$

### 6.2 三维分项归一化评分 (0~100)
1. **战力效能分 ($S_{\text{combat}}$)**：
   $$S_{\text{combat}} = \max\left(0, \, 100 - \frac{\text{TTK}_{\text{practical}} - \text{TTK}_{\min}}{\text{TTK}_{\max} - \text{TTK}_{\min}} \times 100\right)$$
2. **操控容错分 ($S_{\text{handling}}$)**：
   $$S_{\text{handling}} = 0.4 \times \text{recoil\_control} + 0.3 \times \text{stability} + 0.3 \times \min\left(100, \, \frac{\text{RPM}}{10}\right)$$
3. **经济性价比分 ($S_{\text{cost}}$)**：
   $$S_{\text{cost}} = \max\left(0, \, 100 - \frac{\text{Cost}_{\text{loadout}} - \text{Cost}_{\min}}{\text{Cost}_{\max} - \text{Cost}_{\min}} \times 100\right)$$

### 6.3 综合评分与梯队阈值
$$\text{Composite\_Score} = 0.50 \times S_{\text{combat}} + 0.20 \times S_{\text{handling}} + 0.30 \times S_{\text{cost}}$$

- **T0（版本必选 / 极高性价比）**：$\ge 88$
- **T1（主力优选 / 稳健实惠）**：$[78, 88)$
- **T2（平民可用 / 过渡备选）**：$[65, 78)$
- **T3（特殊玩具 / 极低性价比）**：$< 65$

---

## 7. 渲染层与交付物规范

### 7.1 主页 `README.md`
- **头部状态看板**：展示更新时间戳、当前行情数据源状态徽章（`Live` / `Snapshot`）、监控枪械总数。
- **三巨头 T0 速查卡片**：
  - 4套4弹（中产首选）T0 推荐清单 + 改枪码 + 单枪总造价。
  - 4套5弹（穿甲利刃）T0 推荐清单 + 改枪码 + 单枪总造价。
  - 5套5弹（顶级交锋）T0 推荐清单 + 改枪码 + 单枪总造价。
- **精选推荐矩阵总览表**：包含枪械名称、口径、15m/35m/50m 对应梯队、60发备弹总成本、推荐改枪码。

### 7.2 分册文档 `docs/tierlist/*.md`
包含 3 个专项分册文件：
- `4armor_4ammo.md`
- `4armor_5ammo.md`
- `5armor_5ammo.md`
每个分册按 15m、35m、50m 设立二级小节，列出完整天梯排名表（含 STK、实战 TTK、单次击杀弹药成本、配件清单）。

### 7.3 开源数据 `data/latest_rankings.json`
提供完整的机器可读数据输出，遵循 OpenAPI 兼容的 JSON Schema。

---

## 8. GitHub Actions 自动化与工程治理规范

### 8.1 工作流策略 (`.github/workflows/update.yml`)
1. **触发时机**：
   - Cron 定时调度（每 12 小时一次：`0 0,12 * * *`）。
   - `workflow_dispatch` 手动触发。
2. **权限最小化收敛**：
   - 顶级权限 `permissions: contents: read`。
   - 仅在提交步骤临时需要 `contents: write`。
3. **语义级防污染提交（Semantic Diff Protection）**：
   - 计算完成后对比本次结果与 `data/latest_rankings.json`。
   - 仅在**任一枪械梯队变化（如 T1 升 T0）**或**综合分值波动绝对值 $\ge 3.0$** 时才执行 `git commit`。
   - 提交信息附带 `[skip ci]`，防止循环触发工作流。

---

## 9. 测试与验收标准

1. **破甲仿真测试 (`tests/test_simulator.py`)**：
   - 验证 4 级弹面对 4 级甲时 STK 应在 4~6 发合理区间；面对 5 级甲 STK 显著拉长至 8~12 发。
   - 验证 5 级弹击穿 4 级甲的极速穿透特征（STK 3~4 发）。
2. **距离衰减与 EHR 测试 (`tests/test_simulator.py`)**：
   - 验证高射速冲锋枪在 50m 距离的实战 TTK 大于射手步枪，防止模型逻辑倒挂。
3. **成本与容灾测试 (`tests/test_cost_model.py`, `tests/test_collectors.py`)**：
   - 验证断网或 403 异常时，系统能无缝加载 `snapshot_prices.json` 和 `baseline_ammo_prices.json` 完成全量天梯生成。
4. **Markdown 渲染测试 (`tests/test_renderers.py`)**：
   - 验证生成的 README.md 与 docs 目录不存在空表格、坏链或语法中断。
