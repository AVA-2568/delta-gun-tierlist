# ADR-0004：data/tables 为唯一运行期真源

- 状态：已接受
- 日期：2026-10-18
- 决策人：YH
- 影响面：`src/engine/game_data.py`、`src/collectors/orzice_price_sync.py`、`tests/test_tables.py`、`tools/migrate_tables.py`

## 背景

当前存在三条数据路径：

1. `data/game/`：`game_data_sync` 从 dfttk 下载并归一化；CI 已不再每日运行。
2. `data/tables/`：契约（2026-10-04）规定为人工维护真源，引擎只读它。
3. `data/overrides/manual_corrections.json`：同步时覆盖 `data/game` 字段，是第二条人工修正通道。

由此产生三个冲突：

- `tests/test_tables.py` 永久断言 `tables` 与 `game` 逐键相等（仅放行 `legs-only`）。
  官方平衡性更新后，按契约把差异合入 `tables`，测试立即变红。
- `orzice_price_sync` 读 `data/game/` 的 weapons/ammo/parts 建价格表骨架；
  只改 `tables` 时，新条目不会进入价格表，最终因缺价被排除出榜。
- `CURRENT_SEASON` 在 `src/engine/ranking.py` 与 `src/collectors/orzice_price_sync.py`
  各硬编码一份，赛季切换存在漏改风险。

## 决策

1. **`data/tables/` 是唯一运行期真源**。引擎与价格同步都只读它。
2. **`data/game/` 降为只读审计快照**。仅保留：
   - 运行期仍需的结构性参考：`profiles.json`、`mechanism.json`、
     `validation_samples.json`、`provenance.json`；
   - 供 `tools/migrate_tables.py` / `tools/tables_diff.py` 对账使用的
     `weapons.json`、`parts.json`、`ammo.json`、`armor.json`、`scenarios.json`。
   快照的同步时间以 `data/game/provenance.json` 的 `source.synced_at` 为准；
   任何运行期代码不得读取这五个文件。
3. **对账断言降级**：`tests/test_tables.py` 保留来源断言、结构/计数/范围断言；
   与 `data/game/` 的逐键相等检查只保留在 `tools/migrate_tables.py --check`
   作为迁移验收，不再作为常驻测试。正确性硬门槛由
   `tests/test_official_reproduction.py`（3774 点官方复现）承担。
4. **单一修正通道**：运行期修正直接改 `data/tables/`；`overrides` 只服务于
   「刷新审计快照」这一动作，不影响榜单。
5. **`CURRENT_SEASON` 单一来源**：新增 `src/season.py`，`ranking` 与
   `orzice_price_sync` 均从该模块导入。

## 后果

- `GameData` 增加可选 `tables_dir` 参数，默认仍为仓库 `data/tables/`；
  价格同步改用 `GameData` 读取目录，不再手写 `data/game/*.json` 路径。
- 新增测试：价格同步使用的武器/弹药/配件集合必须等于 `GameData` 的对应集合，
  防止骨架再次漂移。
- `data/game/` 五个快照文件（约 2.6 MB）保留，但不再参与运行期。
  后续如确认无对账需求，可单独提案删除。
- 常驻测试不再因合法的人工改表而失败；改表后的正确性由官方复现测试兜底。

## 否决的方案

| 方案 | 否决理由 |
| :-- | :-- |
| `game` + `overrides` 为真源，`tables` 变生成产物 | 需要把 overrides 扩展到配件/情景，并为每次人工编辑重跑迁移；机器多于收益 |
| 维持双写 | 每次更新改两份，且两条修正通道并存，长期必然漂移 |
