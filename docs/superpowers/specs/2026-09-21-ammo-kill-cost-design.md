# 弹药击杀成本展示设计规范 (Design Spec)

- **项目名称**：Delta Force Pure TTK Tier List (`delta-gun-tierlist`)
- **创建日期**：2026-09-21
- **文档版本**：v1.0.0
- **前置规范**：`2026-09-20-pure-ttk-redesign-design.md` (v3.1)
- **范围**：在纯 TTK 榜上新增「弹药 / 单发价 / 击杀成本」三列；**仅展示，不改排序与分层**

---

## 1. 背景与目标

v3.1 规范把经济性彻底移除（删除 `cost_model.py`、`ammo_collector.py`、`baseline_ammo_prices.json`、
`snapshot_prices.json`，理由为"经济性彻底移除"），榜单只回答一个问题：**击杀需要多久**。

本次增补回答第二个问题：**这次击杀要花多少钱**。两者共用同一个 `E[N]`，口径不冲突。

### 1.1 目标

- 榜单新增三列：**弹药**（该枪该情景实际使用的弹）、**单发价**（30 天成交均价）、**击杀成本**。
- 口径透明、可复算：`击杀成本 = 带内平均期望击杀发数 × 单发价`。
- 价格数据与官方战斗数据**物理隔离**，互不污染。

### 1.2 非目标（YAGNI）

| 不做 | 理由 |
| :-- | :-- |
| 改排序键 / 改分层 | 本次是"加展示列"，成本不参与任何排序 |
| 性价比榜（TTK ÷ 成本） | 未提出，且需要新的口径决策 |
| 整装总成本（枪价 + 配件价 + 备弹） | 旧 `cost_model.py` 的口径，本次只要单次击杀弹药成本 |
| 实时价格抓取 | 用户明确要 30 天均价，实时价波动大且需引入第三方依赖与网络 |
| 配件价格 | 零配件价格数据源，且不影响击杀成本口径 |

---

## 2. 口径定义

| 量 | 定义 | 来源 |
| :-- | :-- | :-- |
| **弹药** | 该枪在该情景下实际装载的弹药（口径内同等级取 `ammo_item_id` 最小者） | `LoadoutSolver.ammo_for()` → `game_data.ammo_at_level()` |
| **单发价** | 该弹药的**近 30 天成交均价**（哈夫币），非实时价 | `data/reference/ammo_prices.json`（手工维护） |
| **击杀成本** | `带内平均期望击杀发数 × 单发价` | 本系统计算 |

### 2.1 为什么按距离带各自计算

期望击杀发数 `E[N]` 随距离上升（弹道衰减导致伤害下降），远距离自然更费钱——这是真实且有价值的信息。
故每个距离带用**该带自己的**平均 `E[N]`。

### 2.2 为什么只需聚合 E[N] 的均值

单价 `p` 与距离无关，因此：

```
带内成本均值 = 均值_d( E[N](d) × p ) = p × 均值_d( E[N](d) )
```

只需在聚合层多算一个 `mean_expected_shots`，无需对每个距离点单独算成本。

### 2.3 与 TTK 口径的一致性

| 量 | 公式 | 说明 |
| :-- | :-- | :-- |
| TTK | `(E[N] − 1) × Δ` | 第一发在 t=0，不占用时间 |
| 击杀成本 | `E[N] × p` | **第一发子弹同样计费**，故不减 1 |

两者基于同一个 `E[N]`，差异只在"时间从第一发命中起算、子弹从第一发就消耗"，口径自洽。

---

## 3. 数据层

### 3.1 `data/reference/ammo_prices.json`（新增，手工维护）

与 `data/reference/moligod_weapons.json` 同级。

```json
{
  "schema": "ammo-price-avg-30d",
  "currency": "哈夫币",
  "window": { "from": "2026-08-23", "to": "2026-09-21", "days": 30 },
  "updated_at": "2026-09-21",
  "note": "手工维护：price_avg_30d = 近 30 天成交均价，非实时价",
  "ammo": [
    {
      "ammo_item_id": "37100500001",
      "caliber": "5.56x45mm",
      "name": "M995",
      "penetration_level": 5,
      "price_avg_30d": null
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
| :-- | :-- | :-- |
| `schema` | str | 固定 `ammo-price-avg-30d`，用于格式识别 |
| `currency` | str | 固定 `哈夫币`；渲染层直接引用 |
| `window` | obj | 均价统计区间（`from` / `to` / `days`），供 README 标注 |
| `updated_at` | str | 本表最后一次更新日期 |
| `ammo[].ammo_item_id` | str | **主键**，与 `ammo.json` 的 `ammo_item_id` 一一对应 |
| `ammo[].caliber` / `name` / `penetration_level` | str/int | 冗余字段，仅供人工辨认，不参与匹配 |
| `ammo[].price_avg_30d` | int/null | 单发均价（哈夫币）；`null` 表示未填 |

**主键选择依据**：`name` 存在重名（`AP` 同时是 `.45ACP AP` 与 `.50AE AP`；`BP`/`BT`/`FMJ` 同样重名），
`caliber + level` 也存在一对多（5.45x39mm L4 有 `BT` / `BT +P` / `BT ST` 三款），
故**只有 `ammo_item_id` 唯一**。

### 3.2 `tools/build_ammo_price_skeleton.py`（新增）

从 `data/game/ammo.json` 生成 114 款弹药的骨架条目。

- **幂等**：已存在于表中的 `ammo_item_id` 一律**原样保留**（含已填价格），只补充缺失行；
  不做删除、不做覆盖。
- 首次运行产出全部 `price_avg_30d: null` 的骨架，供人工填价。

---

## 4. 引擎层

### 4.1 `src/engine/ammo_pricing.py`（新增）

单一职责：**加载价格表 + 按主键查价**。不含任何计算。

```python
@dataclass(frozen=True)
class AmmoPriceTable:
    currency: str
    window: Mapping[str, Any]
    updated_at: str
    prices: Mapping[str, int]              # ammo_item_id -> price_avg_30d

    def price_for(self, ammo_item_id: str) -> Optional[int]:
        """缺价或未知 id 返回 None。"""

    @property
    def is_empty(self) -> bool: ...


def load_ammo_prices(path: str) -> AmmoPriceTable:
    """文件缺失 / 解析失败 / schema 不符 → 返回空表（不抛异常）。"""
```

行为约定：

| 情况 | 行为 |
| :-- | :-- |
| 文件不存在 | 返回空表（`prices` 为空），榜单其余部分完全不变 |
| JSON 解析失败 | 返回空表，并记录 warning 日志 |
| 某条 `price_avg_30d` 为 `null` / 非正整数 | 该 id 不进入 `prices`（等价于缺价） |
| 表中含 `ammo.json` 里不存在的 `ammo_item_id` | 保留在 `prices` 中但不被任何武器引用，无副作用 |

### 4.2 `src/engine/engagement.py` · `band_summary` 扩展

返回值增加一个字段：

```
{ 距离带名: { "min_ms": ..., "max_ms": ..., "mean_ms": ..., "mean_expected_shots": ... } }
```

- `mean_expected_shots` = 该带内各距离点 `TtkResult.expected_shots` 的算术平均。
- **只增字段，不改既有字段语义**，向后兼容（现有消费者只读 `min/max/mean_ms`）。

---

## 5. 装配层

### 5.1 `src/engine/tiering.py` · `rank_weapons_for_scenario`

新增参数 `price_table: Optional[AmmoPriceTable] = None`。

对每把枪：

1. `ammo = solver.ammo_for(profile_key)` → 取 `ammo_item_id` / `name` / `caliber`
2. `price = price_table.price_for(ammo_item_id) if price_table else None`
3. 每距离带：`kill_cost = round(mean_expected_shots × price) if price is not None else None`

数据结构扩展：

| 结构 | 新增字段 |
| :-- | :-- |
| `BandResult` | `mean_expected_shots: float`、`kill_cost: Optional[int]` |
| `GunRanking` | `ammo_item_id: str`、`ammo_name: str`、`ammo_caliber: str`、`ammo_price_avg_30d: Optional[int]` |

### 5.2 `src/engine/tiering.py` · `to_export`

payload 新增：

```jsonc
{
  "ammo_price_meta": {                    // 顶层
    "currency": "哈夫币",
    "window": { "from": "2026-08-23", "to": "2026-09-21", "days": 30 },
    "updated_at": "2026-09-21",
    "available": true                     // 价格表是否非空
  },
  "weapons": [
    {
      "ammo": { "ammo_item_id": "37100500001", "name": "M995", "caliber": "5.56x45mm",
                "price_avg_30d": 4579 },
      "bands": {
        "贴脸": { "rank": 1, "tier": "T0", "mean_ms": 286.92, "worst_ms": 286.92,
                  "best_ms": 286.92, "mean_expected_shots": 5.5430, "kill_cost": 25381 }
      }
    }
  ]
}
```

### 5.3 `src/pipeline.py` · `run_pipeline`

- 启动时 `price_table = load_ammo_prices("data/reference/ammo_prices.json")`，透传给
  `rank_weapons_for_scenario`。
- 将 `payload["ammo_price_meta"]` 传给渲染层，用于 README / 情景文档的时效标注。

---

## 6. 渲染层

`src/renderers/ttk_report.py` 表头变更（三列插在「期望击杀发数@0m」与「射速」之间）：

```
| # | 层级 | 武器 | 平均 TTK | 最差 TTK | 期望击杀发数@0m | 弹药 | 单发价 | 击杀成本 | 射速 | 优势射程 | 最优配装 |
```

格式规则（**渲染层零计算，只格式化**）：

| 列 | 取值 | 格式 |
| :-- | :-- | :-- |
| 弹药 | `weapons[].ammo` | `caliber + " " + name`；`caliber` 为空则只输出 `name` |
| 单发价 | `weapons[].ammo.price_avg_30d` | `4,579 哈夫币`（千分位整数）；`None` → `—` |
| 击杀成本 | `bands[带].kill_cost` | `25,386 哈夫币`（千分位整数）；`None` → `—` |

时效标注：

- `render_readme` / `render_scenario_markdown` 在「数据说明」段增加一行：
  `- 价格数据：手工维护 30 天均价（{window.from} ~ {window.to}），截至 {updated_at}`
- `ammo_price_meta.available == false` 时，该行改为：
  `- 价格数据：未配置（data/reference/ammo_prices.json 缺失或为空），成本列显示 —`

---

## 7. 边界处理

| 边界 | 行为 |
| :-- | :-- |
| 价格表文件不存在 | 加载为空表；三列全 `—`；**TTK / 期望发数 / 分层数值不变**，仅新增三列显示 `—` |
| 价格表为空（`ammo` 为空数组） | 同上 |
| 单款弹 `price_avg_30d` 为 `null` | 仅该行成本/单价列显示 `—` |
| 价格表含未知 `ammo_item_id` | 忽略，不报错 |
| 弹药 `caliber` 为空（12 款，含箭矢） | 弹药列只显示型号 |
| 武器在该情景无可用弹药 | 该枪已被既有口径排除（`excluded`），不进入渲染 |

---

## 8. 测试要求

新增测试：

| 模块 | 用例 |
| :-- | :-- |
| `ammo_pricing` | 正常加载、按 id 查价、缺文件返回空表、`null` 价格不入表、未知 id 返回 `None` |
| `band_summary` | `mean_expected_shots` 等于带内各点 `expected_shots` 的算术平均 |
| `tiering` | 成本 = `round(mean_expected_shots × price)`；缺价时 `kill_cost is None` |
| `to_export` | payload 含 `ammo_price_meta` 与 `weapons[].ammo`、`bands[].kill_cost` |
| `render_band_table` | 三列出现在表头；缺价渲染 `—`；空 `caliber` 只显示型号 |

回归要求：

- 既有 **66 项测试全绿**。
- `python -m src.pipeline` 端到端通过；**未配置价格表时，产物中所有 TTK / 期望发数 / 分层字段与既有数值
  逐位一致**（价格相关字段为 `null` 或 `—`），证明新增功能对战斗链路零侵入。

---

## 9. 实现顺序

| # | 步骤 | 依赖 |
| :-- | :-- | :-- |
| 1 | `ammo_pricing.py` + 单测 | — |
| 2 | `band_summary` 扩展 + 单测 | — |
| 3 | `tiering` 装配（BandResult / GunRanking / to_export）+ 单测 | 1, 2 |
| 4 | `build_ammo_price_skeleton.py` + 生成骨架表 | 1 |
| 5 | 渲染层三列 + 时效标注 + 单测 | 3 |
| 6 | `pipeline` 注入 + 端到端回归 | 3, 5 |
