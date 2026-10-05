# 数据表化架构改造契约（方案 A：单基准）

> 状态：已与维护者对齐拍板（2026-10-04）。本文件是实施的唯一契约，实现者机械执行。
> 目标：`data/tables/` 四张表成为**人工维护的真源**，引擎从表读取；`data/game/` 降级为
> 上游同步参考层；每日 CI 摘除官方数据同步（只留价格同步）。

## 0. 已拍板的决策记录

1. 四张表：枪械 / 配件 / 弹药 / 护甲，全部独立维护；初始数据从现有 `data/game/` 无损迁移。
2. 榜单情景维持 5 个（armor-4-ammo-4/5、armor-5-ammo-4/5、armor-6-ammo-5 的 default 预设）——
   对战常见搭配调研（机密局 4–5 级甲弹、绝密局 5–6 级）与此吻合。
3. 护甲取舍 = **方案 A 单基准**：护甲表收每级全部甲/盔候选（耐久+覆盖部位），每级一个
   基准件（初始=官方情景件），引擎读基准件。实测依据：同级甲弹下甲耐久 110→80 影响
   TTK 约 6%，压制局仅 1.5%——基准件机制保证未来可人工换基准重算。
4. 弹药表/护甲表/情景表**全量收录**（含低级弹、1–3 级甲、21 个情景）：官方 3774 点复现
   回归（`tests/test_official_reproduction.py`）硬依赖这些数据；"只考虑 4 级+"体现在
   出榜情景（本就只有 5 个），不体现在数据删除。
5. `mechanism.json`（官方机制曲线）与 `profiles.json`（散布/后坐/弹道档案库）**不表内化**：
   它们是官方机制的结构性固化（102 曲线 / 737 档案），人工维护价值低，冻结在 `data/game`
   作参考层，引擎继续读取。
6. TTK 零变化铁律：切换后引擎消费的一切字段值**逐位不变**——由对账测试与榜单产物
   逐位比对双重兜底。

## 1. `data/tables/` 文件布局

```
data/tables/
├─ weapons/            # 43 个文件，一枪一文件 <weapon_id>.json
│   └─ 18010000037.json   {"base": {...}, "variants": [...]}
├─ parts/              # 按槽位分文件 <slot>.json
│   └─ barrel.json        {"slot": "barrel", "parts": [...]}
├─ ammo.json           # 原 data/game/ammo.json 原样
├─ armor.json          # 原 data/game/armor.json 原样（含全部等级与候选清单）
└─ scenarios.json      # 原 data/game/scenarios.json 原样（21 情景）
```

- `ammo.json` / `armor.json` / `scenarios.json`：**字节级原样复制**（它们结构扁平，
  独立即表；后续人工编辑自然与参考层分离）。
- `weapons/` 与 `parts/`：重组（见下）。

## 2. 枪械表 schema（重组）

**base 块**：`data/game/weapons.json` 对应条目剔除 `profile_key`、`is_variant`、
`variant_item_id`、`variant_item_name` 四键后的**全部其余字段原样保留**（含未进 TTK
的字段——第一版不做字段精简，后续人工自行删减）。

**variants 块**：官方变体内嵌。实测（2026-10-04，全量 18 变体）变体条目与本体**仅
`display_name` 与 `reference_candidates` 两字段不同**。每变体写：

```json
{
  "variant_item_id": "13020000561",
  "variant_item_name": "AS Val刺客高级枪管",
  "display_name": "AS-Val-刺客高级枪管",
  "reference_candidates": [ ...变体自有值... ]
}
```

迁移工具必须对全部 18 个变体做逐字段 diff 校验：若发现上述两字段之外的差异字段，
一并写入变体块（契约的"仅两字段"是实测结论，工具以实际 diff 为准并打印报告）。

**展开规则**（引擎加载时机械执行）：

```
base 条目   = base 块 + {profile_key: "<weapon_id>:base", is_variant: false,
                          variant_item_id: null, variant_item_name: null}
变体条目   = copy(base 块) + 变体差异块覆盖
            + {profile_key: "<weapon_id>:<variant_item_id>", is_variant: true}
```

（`weapon_id` 已在 base 块内；变体条目继承。）

**对账口径**：展开后的 61 条目与 `data/game/weapons.json` 的 61 条目按
`profile_key` 配对，**逐键逐值相等**（含嵌套结构与浮点）。

## 3. 配件表 schema（重组）

按 `slot` 分组写 `data/tables/parts/<slot>.json`，每文件
`{"slot": "<slot>", "parts": [该槽位全部配件条目，字段原样]}`，条目按 `item_id` 排序。
槽位集合以实际数据为准（barrel / muzzle / foregrip / rearGrip / stock / magazine 等），
迁移时打印槽位 × 数量分布。

**对账口径**：全部文件合并回 `{item_id: 条目}` 后与 `data/game/parts.json` 的
824 条逐键逐值相等。

## 4. 引擎切换（src/engine/game_data.py）

`GameData` 各域数据来源：

| 域 | 新来源 | 说明 |
| :-- | :-- | :-- |
| weapons | `data/tables/weapons/` 按第 2 节展开 | 61 条目，顺序：weapon_id 升序、base 先于变体（与原文件一致即可，索引按 profile_key 建立不受顺序影响） |
| parts | `data/tables/parts/` 合并 | 824 条 |
| ammo | `data/tables/ammo.json` | 113 条原样 |
| armor | `data/tables/armor.json` | 原样 |
| scenarios_raw | `data/tables/scenarios.json` | 原样 |
| profiles | `data/game/profiles.json`（不变） | 官方档案库，参考层 |
| mechanism | `data/game/mechanism.json`（不变） | 官方机制曲线，参考层 |
| validation_samples | `data/game/validation_samples.json`（不变） | 官方复现锚点 |
| provenance | `data/game/provenance.json`（不变） | 溯源 |

- 表目录常量 `TABLES_DIR = data/tables`；`data_dir` 参数语义变为参考层目录（保留
  现有签名兼容，测试与工具可传自定义路径）。
- 缺表报错信息指向 `python tools/migrate_tables.py`（不再是 game_data_sync）。

## 5. 迁移工具（tools/migrate_tables.py）

- `python tools/migrate_tables.py`：按契约生成 `data/tables/`，幂等可重跑；
  打印变体 diff 校验报告与槽位分布。
- `--check`：校验已生成表按展开规则还原后与 `data/game/` 一致（weapons/parts 逐键
  逐值；ammo/armor/scenarios 逐字节），不一致退出码 1。

## 6. 对账工具（tools/tables_diff.py）

人工表（真源）vs `data/game/`（上游参考层）差异报告，供审阅上游更新后人工合入：

- weapons/parts：按展开规则对齐后逐字段 diff，输出「哪把枪/哪个配件的哪个字段、
  两侧各是什么值」；
- ammo/armor/scenarios：条目级 diff（按 id/等级/情景 id 配对）；
- 有差异退出码 1，零差异退出码 0。当前必须零差异（表刚从参考层迁移）。

## 7. CI 调整（.github/workflows/update.yml）

摘除「Sync Official Game Data」步骤（官方数据域已转 data/tables 独立维护）；其余步骤
（Sync Market Prices (orzice)、Rebuild Tier List、Export Data Tables、Record Official
Reproduction Residual、Commit/Push）不动。摘除处留一行注释指向本契约与 tables_diff。

## 8. 验收标准（gate）

1. `python -m pytest -q` 全绿（含新增 `tests/test_tables.py`：第 2/3 节对账口径 +
   GameData 各域来源断言）。
2. `python -m src.pipeline --beam-width 8` 重算后，`git diff --stat HEAD -- data/榜单
   docs/榜单 data/export README.md docs/改枪指南.md` 输出为空（榜单产物逐位一致，
   TTK 零变化）。
3. `python tools/tables_diff.py` 零差异退出 0。
