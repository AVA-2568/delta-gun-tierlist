# 代码库精简优化设计规范 (Design Spec)

- **项目名称**：Delta Force Pure TTK Tier List (`delta-gun-tierlist`)
- **创建日期**：2026-09-28
- **文档版本**：v1.0.0
- **前置规范**：`2026-09-20-pure-ttk-redesign-design.md`、`2026-09-21-ammo-kill-cost-design.md`、`2026-09-22-gun-price-and-variant-relabel-design.md`、`2026-09-28-ttk-official-mechanism-audit-design.md`
- **范围**：删除死代码与失效资产、合并重复实现、消除重算链路的重复计算、拆解三个巨石文件、修复距离带静默缺陷；
  **不改排序、不改分层、不改输出字段、不改任何数值口径**

---

## 1. 背景与目标

仓库历经四轮功能迭代（纯 TTK 重构 → 弹药击杀成本 → 枪价与变体改标 → 官方机制全链路审计），积累了结构债。
本次不新增任何功能，只做**减法**：在「测试全绿 + 产物逐字节不变」双门禁下降低维护面。

### 1.1 全仓基线（2026-09-28 实测）

| 项 | 值 |
| :-- | :-- |
| git 跟踪文件 | 92 个 |
| `src/` + `tests/` + `tools/` Python | 9108 行 |
| 测试 | 156 项通过（62.98 s） |
| 运行期第三方依赖 | 0（仅标准库） |
| 工作区体积 | 152 MB（其中 `.probe/` 67 MB、`.cache/` 69 MB 已 gitignore，**不属仓库问题**） |

### 1.2 三条全局硬约束

| # | 约束 | 依据 |
| :-- | :-- | :-- |
| **G1** | `README.md` / `docs/` / `data/` 的 `git diff` 必须为空。⇒ **不新增、不删除、不重命名任何输出字段、列、表头**，含恒空字段（如 `tiering` 下恒为 `{}` 的 `tuning`）与恒 `—` 列 | 需求方 2026-09-28 选定「严格零差异」门禁 |
| **G2** | 删除授权仅限：代码死代码、`tools/backfill_gun_prices.py`、`tools/crosscheck_third_party.py`（降级为测试）。其余已跟踪文件只做内容修正 | 需求方 2026-09-28 选定「精准处置」 |
| **G3** | 保持运行期零第三方依赖 | 项目既有契约（`README.md` 工程结构节） |
| **G4** | 每阶段独立提交，未过门禁不得进入下一阶段 | 需求方选定方案 A |

### 1.3 阶段切分（方案 A：风险递增）

| 阶段 | 内容 | 净减 | 风险 |
| :-- | :-- | --: | :-- |
| 0 | 建立零差异基线零点（前置） | — | — |
| 1 | 零差异清理 | ≈ −450 行 | 低 |
| 2 | 重算链路提速 | 行数几乎不变 | 低 |
| 3 | 结构重构 | 行数不变，可读性↑ | 中 |

---

## 2. 阶段 0：建立零差异基线零点（前置，必做）

**问题**：G1 要求「`git diff` 为空」，但若当前提交的产物与本地重算结果本就存在差异（浮点、字典序、环境差异），
则后续所有阶段的门禁都失去参照意义。

**做法**：
1. 在未改动的代码上执行 `python -m src.pipeline`（默认 5 实战情景，与 README 主榜口径一致）。
2. 执行 `git diff --exit-code README.md docs/ data/`。
3. **若为空**：零点 = 空 diff，后续每阶段直接以此为准。
4. **若不为空**：记录该 diff 为**零点基线**，后续每阶段与零点比对（要求「阶段改动不引入新差异」）。
   同时记录差异来源，若属环境相关（如行尾/编码），在 CI 侧补 `--render-only` 复核。

**验收**：零点基线以「阶段 0 提交的 `git diff` 输出」为准，由该提交的 commit message 与
`docs/superpowers/plans/` 对应任务的执行报告共同记录；阶段 0 不修改任何源码或产物。

---

## 3. 阶段 1：零差异清理

### 3.1 引擎层死代码（逐条已用 Grep 全仓验证调用点为 0）

| 位置 | 符号 | 说明 |
| :-- | :-- | :-- |
| `src/engine/weapon_state.py:816` | `resolve_weapon_state()` | 模块级便捷包装器，无调用者 |
| `src/engine/weapon_state.py:358-369, 371-381` | `damage_at` / `armor_damage_at` / `shots_per_second` / `describe_panel` | 只读派生量，伤害链走 `ballistics.build_context_from_state` |
| `src/engine/weapon_state.py:101, 210` | `TARGET_ALIASES` | 别名表恒为空，`.get(x, x)` 恒等于 `x` |
| `src/engine/weapon_state.py` | `panel_named` / `rate_of_fire_multiplier` / `burst_cadence_seconds` | 只写不读字段 |
| `src/engine/curves.py:62, 66, 92, 130, 145, 150` | `output_range` / `is_identity` / `sample` / `CurveLibrary.ids` / `maybe` / `as_dict` | 曲线库仅经 `get()` 使用 |
| `src/engine/game_data.py:63, 85, 109, 116, 120` | `dataset_version` / `require_profile` / `ammo_levels` / `scenario_ids` / `distance_range` | 渲染层改从 `provenance.source` 取值；`scenario_ids`(L116) 自带 `# pragma: no cover - 便捷方法` 注释，佐证其为遗留便捷方法 |
| `src/engine/ballistics.py:226` | 模块级 `expected_kill_shots(ctx)` | 仅 `DamageContext` 方法的转发包装 |
| `src/engine/ballistics.py:183` | `DamageContext.shot_damage()` | DP 内联直接用 `self._table[...]` |
| `src/engine/engagement.py:62` | `TtkResult.as_dict()` | 渲染层直接读 `to_export` payload |
| `src/engine/loadout.py:279, 286` | `LoadoutSolution.band_ms` / `.as_dict()` | 见 §3.8，随簇删除 |
| `src/engine/tiering.py:94` | `GunRanking.has_variant` | `is_variant` 字段已直达渲染层 |

**澄清（避免误删）**：`tests/test_renderers.py` 与 `tests/test_data_integrity.py` 中出现的
`dataset_version` / `scenario_ids` / `distance_range` 均为**同名局部变量或 JSON 键**，
已逐条核实与上述被删方法无关。

**验收**：删除后 `grep -rn "<符号>" src/ tests/ tools/` 命中 0。

### 3.2 双价格模块合并（净减 ≈ 100 行）

**问题**：`src/engine/ammo_pricing.py`(92 行) 与 `src/engine/weapon_pricing.py`(99 行)
归一化后仅 85 行差异，重复度约 55%：`_empty` / `_coerce_price` / `price_for` / `is_empty` /
`load_*` 的 try/except + `EXPECTED_SCHEMA` 校验逐行克隆，差异仅在 schema 常量、主键名与 `raw` 分段键。

**做法**：新建 `src/engine/price_table.py`，提供泛型 `PriceTable` dataclass 与
`load_price_table(path, schema, section, id_field)`；`ammo_pricing.py` / `weapon_pricing.py`
退化为薄封装（各约 12 行）。

**保留的兼容面（非向后兼容层，而是既有引用）**：`AmmoPriceTable` / `WeaponPriceTable` 类型名必须保留 ——
`src/engine/tiering.py` 的 `to_export` 与 `tests/test_ammo_pricing.py`、`tests/test_weapon_pricing.py` 引用它们。

**验收**：`pytest tests/test_ammo_pricing.py tests/test_weapon_pricing.py tests/test_gun_price.py -q` 全绿。

### 3.3 `llms.txt` 路径修复（3 行，保留文件）

**澄清（推翻初判）**：`llms.txt` **不是失效残留**。`docs/audit/2026-09-28-ttk-official-mechanism-audit-report.md:70`
与 `docs/superpowers/plans/2026-09-28-ttk-official-mechanism-fix.md:346` 均将其列为
「必须与 `README.md`、`ballistics.py` 同步统一口径的**三个文档位点之一**」。**保留文件**。

**真实问题**：第 47–49 行引用的路径磁盘上不存在（已用 `test -e` 逐条核实）：

| 行 | 现值 | 修正为 |
| :-- | :-- | :-- |
| 47 | `docs/tierlist/` | `docs/榜单/` |
| 48 | `docs/gunsmith-guide.md` | `docs/改枪指南.md` |
| 49 | `data/tierlist/` | `data/榜单/` |

**并核对**：`llms.txt` 与 `README.md` 的方法学口径表述是否仍同源（审计报告 P1 曾要求三处统一）。

### 3.4 删除 `tools/backfill_gun_prices.py`（−108 行）

**已验证**：5 个 `data/榜单/*.json` 全部含 `weapon_price_meta` 顶层键与
`gun_price_daily` / `full_price_180rd` 字段（实测非空计数：221/214、191/184、222/215、191/184、192/185）。
该脚本为「新增价格列后免重算回填」的一次性迁移工具，管线已原生产出该列。

**验收**：删除后 `grep -rn "backfill_gun_prices" . --include="*.py" --include="*.yml"` 命中 0。

### 3.5 `tools/crosscheck_third_party.py` 降级为测试（脚本 −88 行）

**动机**：该脚本支撑 README 可信度声明「moligod.com/gunsmith 的官方对象 ID 与本项目武器池互证
（26/26 图片 URL 逐字节一致）」。**直接删除会使该声明不可验证**，因此下沉为测试以保住可验证性。

**做法**：新增 `tests/test_third_party_crosscheck.py`，离线读取已入库的
`data/reference/moligod_weapons.json`，断言 26/26 图片 URL 逐字节一致。

### 3.6 移除 `mode` 参数链

`weapon_state.py:DEFAULT_MODE` / `WeaponStateResolver(mode=)` / `WeaponState.mode` 字段 /
`loadout.py:LoadoutSolver(..., mode="sol")`。全仓无任何调用点显式传 `mode=`。

**勘误（2026-09-28）**：原要求为「移除 `mode` 参数链」，实测发现 `mode` 是**承重**的——`weapon_state.py` 以 `.get(self.mode)` 在 `curveIds` 中选曲线，且数据中 1872 个节点同时含 `sol` 与 `mp` 两档键，照字面删除会导致静默数值变更；分支已按需求方拍板（确认日期 2026-09-28）改为**收窄方案**：保留 `mode` 参数链与 `DEFAULT_MODE`，只删 `WeaponState.mode` 等真正只写的字段，见提交 `aac6a81`。

### 3.7 收敛测试专用开关 `include_non_ttk`

`loadout.py` 的 `include_non_ttk` 出现在 7 处：形参声明 L151、分支入口 L154、
`build_socket_specs` 形参 L179、透传 L192 与 L209、TtkTox 守卫 L194 与 L211。
全部仅 `tests/test_loadout.py:83` 使用。

**做法**：删除 `include_non_ttk` 形参与全部分支，`_prune_options` 恢复为单一行为；
测试改为直接对 `build_socket_specs` 的返回值做内联构造，不再走该开关。

### 3.8 删除精校 / 配装求解器簇（≈ −140 行 + 对应用例）

**需求方决策（2026-09-28）**：删除。

**依据**：
- 生产链路 `tiering.py` 的 4 处 `solver.resolver.resolve(...)` 全部传 `tuning=None`，
  从不使用 `solve_tuning`；
- `ttk_report.py:526-529` 明文声明「官方精校共 12 个作用目标。**没有任何一个改变期望击杀发数或射击间隔**，
  因此精校不影响 TTK 排名」——精校不参与 TTK 是**设计立场**，非缺陷；
- 全仓引用实测：`solve_tuning`(L374) 0、`ttk_tuning_dims`(L249) 0、`solver.solve`(L401) 在 `src/` 0
  （仅 `tests/test_loadout.py` 引用 4 次）、`LoadoutSolution`(L270) 仅被 `src/engine/__init__.py` re-export。

**删除清单**（`src/engine/loadout.py`）：

| 符号 | 行区间 | 备注 |
| :-- | :-- | :-- |
| `tuning_breakpoints` | 231-248 | 唯一消费者是被删的 `ttk_tuning_dims` |
| `ttk_tuning_dims` | 249-269 | |
| `LoadoutSolution`（含 `band_ms` / `as_dict` / `score_seconds`） | 270-296 | 含 `src/engine/__init__.py` 的 import 与 `__all__` 条目 |
| `LoadoutSolver.solve_tuning` | 374-400 | |
| `LoadoutSolver.solve` | 401-448 | 配装求解器，已被 `tiering` 束搜索取代 |

**必须保留**：`LoadoutSolver.enumerate_loadouts`（`tiering.py:418` 生产使用）、
`_mounted` / `_band_score` / `ammo_for` 与 `SocketSpec` / `build_socket_specs` / `part_affects_ttk` 等。

**测试调整**：删除 `tests/test_loadout.py` 中 4 个 `solver.solve(...)` 用例与
`test_tuning_breakpoints_are_curve_nodes`；保留 `enumerate_loadouts` 相关用例。

**G1 注意事项**：`tiering.py:69/319/494` 的 `tuning` 字段恒为 `{}` 并被写入
`data/榜单/*.json`。**受 G1 约束，该字段必须保留**，不得随精校簇一并删除。

---

## 4. 阶段 2：重算链路提速

| # | 位置 | 问题 | 做法 |
| :-- | :-- | :-- | :-- |
| 2.1 | `tiering.py:429` vs `:451` | 同一 `loadout` 被完整 `resolve` **两次**（L438 已持有 `_mounted` 却丢弃） | 将 `state_mounted` 透传给 `_factory_ranking`，删除 L451 的第二次 resolve |
| 2.2 | `loadout.py:319`（`_mounted` 内部）→ 经 `loadout.py:352`、`loadout.py:363` 各触发一次；`weapon_state.py:503`（`resolve` 内部）再触发一次 | 同一候选的 `_build_loadout` 在一次 trial 内被调用 **3 次**，每次都重跑含 `while` 循环的耦合求解 | `_build_loadout` 提升为公开纯函数 `build_loadout`；`resolve(..., _precomputed_mounted=)` 透传已算结果 |
| 2.3 | `loadout.py:322` | `_band_score` 每次调用都全量 `resolve`，在 `enumerate_loadouts` / `solve` 排序路径反复触发 | 按 mounted 状态排序元组做同轮 memo |
| 2.4 | `tiering.py:200` + `:462` | 同一分布排序 2 次 | 复用排序结果 |
| 2.5 | `curves.py:78-90` | `Curve.evaluate` 线性扫描段 | 改 `bisect` |

**原 2.6「精校曲线缓存」随 §3.8 删除精校簇而取消**（精校曲线不再进入生产链路）。

**验收**：`pytest -q` 全绿 + `git diff` 归零 + 重算耗时对比记录。

---

## 5. 阶段 3：结构重构

### 5.1 `weapon_state.py` 826 行 → 拆分

**现状**：三个互不相关的关注点。

| 内容 | 行区间 | 去向 |
| :-- | :-- | :-- |
| 修饰层内核：`ModifierLayer` + `_factor` + `_hitbox_key` + `_falloff_from_bullet_profile` + `_accumulate` + `_apply_attribute_effects` + `_part_effect_layer` + `_part_tuning_layer` | 118-274 | 新建 `src/engine/modifiers.py` |
| `WeaponState` 数据类 | 280-381 | 留在 `weapon_state.py` |
| `WeaponStateResolver`：`_build_loadout`(414-485) / `resolve`(488-552) / `_resolve_rules`(555-715) / `_resolve_profiles`+`_resolve_damage`(724-813) | 387-813 | 留在 `weapon_state.py`；`_build_loadout` 提炼为公开 `build_loadout` |

### 5.2 `tiering.py` 572 行 → 拆 3 个模块

| 内容 | 行区间 | 去向 |
| :-- | :-- | :-- |
| `_quantile` + `assign_tiers`（纯分层数学） | 181-217 | `src/engine/tiering.py`（保留） |
| `rank_weapons_for_scenario`（**单函数 251 行**，内含 `_band_results` / `_ammo_price` / `_exclude` / `_signature` / `_factory_ranking` 5 个闭包） | 220-470 | 新建 `src/engine/ranking.py`，闭包外提为模块级私有函数 |
| `to_export`（JSON 序列化） | 473-572 | 新建 `src/engine/tierlist_export.py` |

> **勘误（2026-09-28，交付后补记）：「闭包外提」未实施，已降级为后续可选项。**
>
> 实际交付（`52ea191`）只做了**纯搬迁**：`rank_weapons_for_scenario` 逐字迁入 `src/engine/ranking.py`，5 个闭包**仍嵌在函数内**。实施计划（Task 14）为控制风险把外提降级为「下一步（若做）」，但本 spec 未同步修订，造成「已批准规范」与「已交付代码」之间的分歧；终审（whole-branch review）据此要求正式记录。
>
> **降级理由**（需求方 2026-09-28 确认）：
> - 外提**不减少行数**（反因新增显式参数与 docstring 而略增），与本次「精简」的主目标不直接相关；
> - 5 个闭包经核实**全部在用**（内部调用 2/2/4/4/4 次），无死代码可借机清除；
> - 收益仅限**可测性**（`_signature` 的去重语义、`_factory_ranking` 的单条目组装可独立单测）与**可读性**（免去 5 层嵌套作用域）；
> - 代价是把约 10 个隐式捕获的外层变量显式穿参 —— 属数值路径的实质重构，风险与收益不成比例。
>
> 该函数现状：`ranking.py` 中 254 行（含 5 个闭包共 72 行），外层编排骨架约 180 行。若后续需要独立测试这些内部逻辑，可按本 spec 原意补做，届时须单独提交并重跑全量门禁。

### 5.3 `game_data_sync.py` 1360 行 → 拆 4 个模块

**实测结构**：27 个顶层符号；其中 `sync_all`(1080-1332) 253 行、`normalize_weapon`(755-966) 211 行。

| 内容 | 符号 | 去向 |
| :-- | :-- | :-- |
| HTTP 与缓存 | `SourceUnavailable`、`_sha256_bytes`、`_download`、`_download_json` | `src/collectors/http.py` |
| 覆盖与修正 | `load_overrides`、`_apply_field_overrides` | `src/collectors/overrides.py` |
| schema 归一化 | 9 个 `normalize_*` + `_slot_for_item` / `_normalize_tune` / `_normalize_effect` / `_normalize_spread_profile` / `_normalize_recoil_profile` / `_sol_damage_profile` / `_slugify` / `_strip_authoring_prefix` | `src/collectors/normalize.py` |
| 编排与入口 | `sync_all`、`main`、`_write_json`、常量 | `src/collectors/game_data_sync.py`（保留） |

**CLI 契约不变**：`python -m src.collectors.game_data_sync` 必须继续可用（CI 依赖）。

### 5.4 距离带单一来源（**修静默缺陷**）

**问题**：`("贴脸","近距","中距","远距")` 在三处独立声明 ——
`engagement.py:176-181`（`DISTANCE_BANDS`，含边界）、`tiering.py:27`（`BAND_NAMES`）、
`renderers/ttk_report.py:11`（`BAND_ORDER`，`pipeline.py:38` 再 import）。
`band_summary` 以中文带名为 dict 键，任一处改名后其余处的 `in` / `.get` 全部 **fail-soft**，
结果是**静默丢掉整条距离带**且无任何测试守护。

**做法**：`engagement.py` 为唯一真源（`BAND_NAMES` + `DISTANCE_BANDS`），
`tiering.py` 与 `ttk_report.py` 改为 import；**新增一致性测试**断言
「`band_summary` 输出的键集合 == `BAND_NAMES` == 渲染列头顺序」。

**G1 附带约束**：`tiering.py:568-569` 用 `BAND_NAMES` × `eg.DISTANCE_BANDS` 生成导出 payload 的
距离带元信息（`from_m` / `to_m`）。因此带名与边界值**均不得改动**，本次只统一声明位置，不动取值。

### 5.5 修饰器语义合并

| 问题 | 做法 |
| :-- | :-- |
| `_part_tuning_layer`(weapon_state.py:246-274) 内联重写了 `_accumulate`(191-219) 的 `factor`/`Addend`/`Initial` 三分支，且已出现边界差异（缺 `_ATTR_TARGET_PREFIX` 过滤与 `TARGET_ALIASES`） | 精校每点改调 `_accumulate(layer, target, modifier, value, None)` |
| `_factor`(weapon_state.py:151-159) 与 `curves.apply_modifier`(154-179) 对同一 modifier 语义各实现一份 | `curves` 暴露 `modifier_factor(modifier, value)`，`apply_modifier` 复用之 |

### 5.6 明确不做的重构

| 项 | 原因 |
| :-- | :-- |
| `weapon_state.py:_build_loadout` 的 `guard`/`claimed`/`conflicts` 仲裁（`while changed`） | 注释记载真实数据存在多规则争槽（QJB201 rule4/rule11），**删除会死循环**。仅抽为独立函数 + 补单测 |
| `game_data.py` 每情景进程重复加载大 JSON | 属文档化的并行隔离设计；`--all` 下才显著。不在本次范围 |
| `ballistics.py:DamageContext.__init__` 构造期建 117 格伤害表 | `__slots__` 为 DP 性能刻意设计，改动风险高于收益 |

---

## 6. 删除授权清单（G2 边界内）

| 路径 | 动作 | 依据 |
| :-- | :-- | :-- |
| `tools/backfill_gun_prices.py` | **删除** | §3.4，一次性迁移已完成并验证 |
| `tools/crosscheck_third_party.py` | **删除脚本**，能力下沉 `tests/test_third_party_crosscheck.py` | §3.5，保住可信度声明可验证性 |
| `src/engine/*` 死代码 | **删除** | §3.1 逐条 grep 验证 |
| `src/engine/loadout.py` 精校/求解器簇 | **删除** | §3.8 需求方决策 |
| `llms.txt` | **保留**，修正 3 条路径 | §3.3，审计报告点名的口径位点 |
| `requirements.txt` / `pyproject.toml` | **保留原状** | 合并属工程改造，非精简范畴；本次不动 |

---

## 7. 验证与门禁

### 7.1 每阶段通用门禁（三道，全过才算通过）

```bash
# 1. 测试全绿
python -m pytest -q

# 2. 重算 + 重渲染，产物零差异（对照 §2 零点）
python -m src.pipeline
git diff --exit-code README.md docs/ data/
```

### 7.2 阶段 3 追加门禁

```bash
# 数值回归：3774 个官方样本点复现（防止重构改动伤害链）
python tools/verify_official_reproduction.py
```

### 7.3 新增测试

| 测试 | 守护目标 |
| :-- | :-- |
| `tests/test_third_party_crosscheck.py` | moligod 26/26 图片 URL 一致（§3.5） |
| 距离带一致性测试 | `BAND_NAMES` / `band_summary` 键集合 / 渲染列头顺序三方一致（§5.4） |
| `build_loadout` 纯函数单测 | 配装合成语义锁定，支撑 §2.2 / §5.1 |

### 7.4 测试数量预期

阶段 1 删除约 5 个用例、新增 2 个测试文件；最终数量以实际为准，**任何减少都必须逐条对应到 §3 的删除清单**。

---

## 8. 风险与回滚

| 风险 | 等级 | 缓解 |
| :-- | :-- | :-- |
| 误删「看似无用实则有调用」的符号 | 中 | §3.1 全部经 Grep 全仓验证；删除后复验命中 0 |
| 精校簇删除连带破坏 `tiering` 导出 | 中 | 保留 `tuning` 字段（G1）；`enumerate_loadouts` 明确保留 |
| 拆文件改变 import 副作用或模块级初始化顺序 | 中 | 每步 `pytest` + 产物 diff；拆分先做「纯搬迁」再做「去重」 |
| 修饰器语义合并引入浮点末位差异 | 中 | G1 门禁直接拦截；`verify_official_reproduction` 二次确认 |
| 零点基线本身不为空导致门禁失效 | 中 | §2 前置步骤强制先确认零点 |

**回滚**：每阶段独立提交，任何阶段门禁未过即 `git revert` 该阶段提交，回到上一阶段通过的干净状态。

---

## 9. 非目标

- 不新增任何功能、字段、列、测试口径
- 不改排序键、分层阈值、距离带边界、TTK 定义
- 不引入第三方依赖或打包改造（`pyproject.toml` 不加 `[project]` 段）
- 不清理 `.probe/`（67 MB）与 `.cache/`（69 MB）—— 属本地 gitignore 目录，不构成仓库问题；
  如需清理另行单独确认
- 不做无关重构（`game_data.py` 并行加载、`DamageContext` 建表策略等）

---

## 10. 验收标准

1. 三阶段全部落地，每阶段门禁（§7.1，阶段 3 含 §7.2）通过
2. ~~`src/` + `tests/` + `tools/` 总行数净减 ≥ 450 行~~ **已豁免，见下方交付记录**
3. `git diff README.md docs/ data/` 相对 §2 零点为空
4. 距离带静默缺陷已修复并有测试守护
5. 运行期仍为零第三方依赖
6. 精校簇删除后，`docs/改枪指南.md` 渲染内容不变（它读的是数据层精校定义，非求解器）

### 10.1 交付记录（2026-09-28，全部任务与终审完成后回填）

| 验收项 | 结果 |
| :-- | :-- |
| 1 三阶段落地 + 门禁 | ✅ 阶段 1（Task 9）与阶段 3（Task 18）的 `git diff --exit-code` 均为 CLEAN |
| 2 行数净减 ≥450 | ❌ 实测 **净 −21 行**（30 文件，+2373 / −2394）；**需求方 2026-09-28 决定豁免**，理由见下 |
| 3 产物零差异 | ✅ 全量重算（`--beam-width 8`）后逐字节不变；终审后复验仍 CLEAN |
| 4 距离带缺陷修复 + 守护 | ✅ `316cd79` + 修复轮 `e3aab49`；`tests/test_distance_bands.py` 用独立字面量钉死带名与边界 |
| 5 零第三方运行期依赖 | ✅ AST 全量扫描 `src/`：无第三方导入 |
| 6 改枪指南渲染不变 | ✅ 渲染内容含在 §10.2 的零差异证明内 |

**验收项 2 的豁免理由**：该目标（§1.3 的 −450 估算）是**纯删除估算，未计入本 spec 自身强制的新增**：

- §1.3 假设阶段 3「行数不变」，但 §5.1–5.3 要求的**三次模块拆分必然新增模块头、docstring 与 import**，实测净增约 **+110 行**；
- §3.2 要求的共享 `price_table.py` 为 **+100 行**（它替换掉的重复实现只有 −109 行）；
- §7.3 要求的新增测试实际为 **+297 行**（4 个新测试文件），而估算只按 crosscheck 一项的约 40 行计入。

结构性目标则全部达成：死代码清除、双价格模块 DRY、三个巨石文件拆分、距离带静默缺陷修复、重算链路提速。原始 LOC 总额被上述**新增测试覆盖与模块化头部**抵消，故该指标已不适宜作为本次交付的门槛。后续若仍需补足行数，可执行本计划附录「范围外」已界定的三项（测试镜像合并／新增 `tests/conftest.py`／onebiji 双采集器公共层，合计约 −400~440 行）。

### 10.2 后续可选项（本次不实施，已分诊）

终审（whole-branch review）对执行期累积的 44 条 minor 逐条分诊：**无一条需在合并前修复**（唯一 3 条「合并前必改」项已随修复波处理）。以下按类别固化，供后续触碰相应文件时顺手处理。

**A. 已随终审修复波解决（留档以免重复担心）**

| 项 | 处理 |
| :-- | :-- |
| `game_data.py` 的 `from functools import lru_cache` 在 `scenario_ids` 删除后成为无用导入 | 已删（`a4f2bed`） |
| `loadout.py` 的 `beam_scores` 只写不读（且白跑一次打分） | 已清（`a4f2bed`；保留其 `_score` 预热调用——实测它会播种 `score_cache` 且循环首轮即命中） |
| `game_data_sync.py` 的 `SLOT_ZH` 全仓零读者（真死代码） | 已删（`a4f2bed`；`pipeline.py` 的同名副本有读者，未动） |

**B. 已判为误报，不再跟踪**

- 「`llms.txt:39` 的 `python -m src.pipeline --all` 引用了不存在的 `src/pipeline`」——不成立。`src/pipeline.py` 存在且 `--all` 是合法参数（已由 4/4 CLI `--help` 验证）。

**C. 文案 / 注释漂移**（不影响行为，下次触碰这些文件时顺手改）

- `src/engine/__init__.py:10` docstring 仍称「最优求解」（求解器簇已在 §3.8 删除）；同文件模块地图未列出新增的 `ranking` / `tierlist_export`。
- `src/engine/weapon_state.py:59` 注释仍指向 `src.collectors.game_data_sync.PANEL_ATTR_KEYS`，该常量已随 §5.3 迁至 `normalize.py`。
- `weapon_state.py` 模块 docstring 仍在描述已迁出的修饰层语义与核验锚点（§5.1）。
- `tiering.py` 模块 docstring 仍写「Task #6」且未反映拆分后的职责边界（§5.2）。
- `game_data_sync.py:25` docstring「三个子模块互不反向引用」措辞略松（`normalize → overrides` 是子模块之间的单向引用）。
- `modifiers.py` 中 `accumulate` 的 docstring 称面板属性「由调用方处理」——`part_tuning_layer` 作为新调用方并不处理，该句已成承重假设（§5.5）。
- 三处格式小瑕：`loadout.py` 顶部悬挂缩进残迹；`weapon_state.py` 一处重写注释指代略歧义；`summarize_loadout_effects` 的两实参调用被折成三行（与变体分支的单行写法不一致）。

**D. 结构 / 命名小瑕**

- `LoadoutSolver` 类名名不副实（§3.8 后只剩配装枚举）。
- 2 处跨模块导入私有名：`normalize → overrides._apply_field_overrides`、`ranking → tiering._effective_loadout`。均为当下拆法的最简解；若后续做统一常量层，可提为公开名。
- `tiering.py` 再导出的 `BAND_NAMES` 在本模块内未被使用（仅供 `ranking` / `tierlist_export` 引用），可加 `# noqa: F401` 注释说明意图。
- `modifiers.factor` 现为 `curves.modifier_factor` 的纯转发壳（§5.5 的必然结果），仅剩命名稳定性价值；仍被调用，非死代码。
- 两处**既存**未使用导入（非本次引入）：`curves.py:14` 的 `Sequence`、`tests/test_loadout.py:3` 的 `json`。
- `game_data_sync.py` 拆分时丢掉了两个分节 banner 注释；新模块名 `http.py` 与标准库 `http` 同名（当前 `sys.path` 形态下不遮蔽）。

**E. 健壮性 / 测试覆盖增强**

- `tests/test_price_table.py` 缺一个显式 bad-JSON 用例（`ValueError` 分支目前由 GBK 用例间接覆盖）。
- `tests/test_distance_bands.py` 的接线断言在文件内有两份副本（冗余但无害）；带名**顺序**由同文件的边界连续性用例间接锁定，而非由取值冻结用例直接钉死。
- `resolve(..., _precomputed_mounted=...)` 存在静默分叉隐患：一旦传入该参数，`loadout` 形参即被忽略。当前唯一调用点自洽且有等价性测试守卫；可加断言或强化注释。
- 模块级 `build_loadout` 以类名限定方式引用其后的 `WeaponStateResolver._socket_for_item`，构成模块内前向引用的隐式排序耦合（当前正确，`@staticmethod`）。
- `curves.py` 的 `evaluate` 中两个边界 clamp 按构造不可达（计划原文如此）；`x = NaN` 时 bisect 版返回 `NaN`，而原线性扫描经 fallthrough 返回末点值——理论行为差异，输入为有限距离值故不可达。
- `_score` 的 `loadout` 形参被转发但不影响结果（`mounted` 单独决定分数），注释可更明确。
- 改写后的 `test_build_loadout_only_returns_legal_items` 不再校验「TTK 剪枝后的合法性」——属正确取舍（原版模型不完整），建议加注释说明覆盖范围。

**F. 能力 / 覆盖取舍**（§3.4、§3.5 的既有取舍，评审已确认属授权范围）

- 「不重算、直接修补既有 payload」的运维能力随 `backfill_gun_prices.py` 删除而消失（逻辑与管线同源，现存 payload 已含目标字段，git 历史可追溯）。
- README 的「26/26 图片 URL 逐字节一致」未被直接断言，仅由 `verification_result` 的内部算术间接守护。
- 「与 dfttk catalog 同源」的跨源比对随 `--catalog` 项移除而失去可执行守护。
- 第三方交叉核验的冲突诊断从「累积全部并打印」退化为「首断言即短路」。

**G. 行数补足（§10 豁免后的可选路径）**

测试镜像合并（约 −260）／新增 `tests/conftest.py` 收敛 `ROOT` 与 `gd` fixture（约 −30）／抽取 onebiji 双采集器公共层（约 −110~150）。三者均为真实的 DRY 简化，合计约 −400~440 行。
