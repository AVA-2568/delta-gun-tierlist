# 起枪成本展示与枪价表设计规范 (Design Spec)

- **项目名称**：Delta Force Pure TTK Tier List (`delta-gun-tierlist`)
- **创建日期**：2026-09-22
- **文档版本**：v1.0.0
- **前置规范**：`2026-09-20-pure-ttk-redesign-design.md` (v3.1)、`2026-09-21-ammo-kill-cost-design.md`
- **范围**：榜单新增「裸枪价格 / 裸枪+180发备弹」两列；新增枪价表与每日同步；
  **仅展示，不改排序与分层**；同步修正「官方预装态」的表述口径

---

## 1. 背景与目标

弹药击杀成本上线后（2026-09-21 规范），需求方提出第二个经济问题：
**起一把枪要花多少钱**。本次增补回答它，与 TTK / 击杀成本共用同一批起枪状态行。

### 1.1 口径（与需求方 2026-09-22 逐条确认）

| 量 | 定义 | 来源 |
| :-- | :-- | :-- |
| **裸枪价格** | 本体枪交易行当日价。**变体/改装状态与本体同价**——官方变体只是本体预装了官方改件（改件在交易行按 `attachment` 分类出售），不存在独立的"变体枪"商品；配件价不计入 | `data/reference/weapon_prices.json` |
| **裸枪+180发备弹** | `裸枪价 + 180 × 该行所配弹药单发价`（预估）。**按行所配弹药计价**，不是全枪统一价——配件会改伤害/射速，但那些差异体现在各行 TTK 与击杀成本里 | 本系统计算 |
| ** ammunition 单发价** | 交易行当日价 | `data/reference/ammo_prices.json`（既有） |

- `SPARE_AMMO_ROUNDS = 180`（tiering 常量，payload 经 `weapon_price_meta.spare_ammo_rounds` 下发）。
- 计算入口 `compute_full_price(gun_price, ammo_price, rounds)`：整数运算，任一缺价返回 `None`。
- **对战斗链路零侵入**：有无枪价表，TTK / 期望发数 / 分层逐位不变（测试覆盖）。

### 1.2 「官方预装态」表述修正（遗留问题清理）

旧表述把官方变体作为独立枪行列出（武器列 = 变体名，副标签"变体 · 出厂预装态"），
读起来像另一把枪。**数据层不变**（`entry_kind="variant"` 的行继续保底入榜、参与排名分层，
防止束搜索剪枝丢失官方预装状态），仅渲染层与文案对齐：

- 武器列一律显示**本体名**（`base_name`）；
- 预装来源只在配置列标注（`出厂预装：<预装件名>`）；
- README 口径表改为「本体+官方预装件（官方变体出厂态）」。

---

## 2. 数据层

### 2.1 `data/reference/weapon_prices.json`（新增，自动维护）

与 `ammo_prices.json` 同构（schema `weapon-price-daily`），条目键为 `weapon_id`
（**仅本体**，`is_variant=false` 的官方目录条目）：

```jsonc
{
  "schema": "weapon-price-daily",
  "currency": "哈夫币",
  "window": {"from": "2026-09-22", "to": "2026-09-22", "days": 1},
  "updated_at": "2026-09-22",
  "source": "onebiji 市场周期律 · 市场全览 · 交易行本体裸枪当日价（primary_class=weapon）…",
  "note": "…变体 = 本体 + 官方预装件，共用本体价（配件价不计入）…",
  "weapons": [
    {"weapon_id": "18010000001", "name": "M4A1", "category": "突击步枪",
     "caliber": "5.56x45mm", "price_daily": 87336}
  ]
}
```

### 2.2 采集层

| 模块 | 职责 |
| :-- | :-- |
| `src/collectors/weapon_price_sync.py` | onebiji 市场全览 `primary_class="weapon"` → 本体当日价；骨架来自官方目录；幂等写盘 |
| `src/collectors/zxfps_price_sync.py` | **缺价回填源**：zxfps 三角洲工具站 `/api/sjz/item_list`（签名机制见 §5），仅补主源缺失条目 |
| `src/collectors/ammo_price_sync.py` | 既有主源同步，**新增同样的 zxfps 缺价回填**（APC/+P/SUB 等主源未收录弹） |

主源优先、回填只补缺：`价格 = onebiji ?? zxfps`；两表 `source` 字段标注回填来源。
回填失败（限流/网络）不影响主源数据（缺价保持 `null`，渲染 `—`）。

---

## 3. 引擎层

| 位置 | 变更 |
| :-- | :-- |
| `src/engine/weapon_pricing.py`（新增） | `WeaponPriceTable` + `load_weapon_prices()`，与 `ammo_pricing` 同构（文件缺失/schema 不符 → 空表不抛异常） |
| `src/engine/tiering.py` | `SPARE_AMMO_ROUNDS=180`；`compute_full_price()`；`GunRanking.gun_price_daily` / `full_price_180rd`；`rank_weapons_for_scenario(..., weapon_price_table=)` 按组内 `weapon_id` 查价，**本体/预装态/改装态同价**；`to_export(..., weapon_price_table=)` 输出 `weapon_price_meta`（含 `spare_ammo_rounds`）与每行两字段 |

---

## 4. 装配与渲染

- `src/pipeline.py`：加载枪价表并透传（`WEAPON_PRICE_TABLE` 常量）。
- `src/renderers/ttk_report.py`：
  - 完整榜：`| … | 击杀成本 | 裸枪价格 | 裸枪+180发备弹 | 射速 | …`（列头备弹数取自 payload，缺键回退 180）；
  - README 速览：`| … | 击杀成本 | 裸枪价格 | 裸枪+180发备弹 | 起枪配置 |`；
  - 价格说明行拆两条（弹药 / 枪械），缺表时各自提示；README 新增「起枪成本」口径行。
- 存量数据：`tools/backfill_gun_prices.py` 向已有 `data/榜单/*.json` 注入字段
  （复用 `compute_full_price`，幂等；CI 全量重算后逐位一致）。

---

## 5. zxfps 回填源的接口与签名

- 列表：`GET /api/sjz/item_list?a=<gun|ammo|…>&top=1-2&p=<页>&grade=-1`，每页 10 条。
- 条目 `pic`（`…/object/<objectID>.png`）内嵌**官方 objectID**，与目录精确对齐。
- 签名（站点公开 JS，token.js + CryptoJS；已用 Node 实测钩子逐位核对）：

```
h1    = md5(参数串 + 时间戳)
token = md5(时间戳 + h1 + 盐串)      # 盐串 = 站点 JS 内嵌警示文案，逐字符复制
请求  = ?参数&token=<token>&timestamp=<页面内嵌 var TimeUnix>
```

- 限流：openresty 对连发请求返回 403 空响应。策略：页间间隔 2s、
  403 退避重试、整轮失败换新会话重来（≤3 轮）、目标全命中即早退。
- 请求量：每日 CI 一次、只补缺价条目，总量 ~20 请求以内。

---

## 6. 边界处理

| 边界 | 行为 |
| :-- | :-- |
| 枪价表缺失/为空/格式错 | 空表；两列显示 `—`；战斗数值不变 |
| 某枪无任何报价（两源都没有） | `null` → `—`（缺价不猜测，不兜底） |
| 行所配弹药缺价 | `full_price_180rd = None`（裸枪价仍显示） |
| 旧 payload 缺新键 | 渲染层 `.get()` 链式读取 → `—`，不抛异常 |
| zxfps 限流/不可用 | 主源数据照常落盘，缺失条目留待次日 |

## 7. 测试要求（已全部落地）

- `weapon_pricing`：加载/查价/缺文件/GBK/schema 错 → 空表（镜像弹药测试）。
- `weapon_price_sync`：解析（只收 `weapon` 分类、t_ 块与 attachment 不混入）、
  幂等、回填成功/失败/禁用三态。
- `ammo_price_sync`：回填成功/失败；既有用例注入空回填防联网。
- `zxfps_price_sync`：签名已知向量（Node 钩子实测值）、objectID 提取、
  早退/耗尽/零负价/空目标。
- `gun_price`（引擎装配）：公式、缺价传播、预装态与本体同价、`to_export` 字段、
  **战斗链路零侵入回归**。
- `renderers`：两列位置与金额、变体行显示本体名、README 说明与口径行。
- 回归：全量 154 项测试通过；`--render-only` 本地重渲染一致。
