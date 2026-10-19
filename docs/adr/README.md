# 架构决策记录（ADR）

本目录记录已拍板的架构与口径决策。新增决策必须编号递增，并在 `docs/glossary.md`
同步术语；被取代的 ADR 保留原文，状态改为「已被 ADR-XXXX 取代」。

| 编号 | 标题 | 状态 | 日期 |
| :-- | :-- | :-- | :-- |
| [0001](0001-ttk-definition.md) | TTK 口径以引擎为准（含扳机延迟与弹丸飞行时间） | 已接受 | 2026-10-18 |
| [0002](0002-band-display-rule.md) | 距离榜展示规则（T0 全列 + T1 前 100） | 已接受 | 2026-10-18 |
| [0003](0003-rank-contiguity.md) | 展示行排名连续性 | 已接受 | 2026-10-18 |
| [0004](0004-data-source-of-truth.md) | data/tables 为唯一运行期真源 | 已接受 | 2026-10-18 |
| [0005](0005-drop-all-scenarios.md) | 删除 --all，仓库只发布 6 个默认情景 | 已接受 | 2026-10-18 |
| [0006](0006-loadout-enumeration-completeness.md) | 配装枚举覆盖单选项插槽与解锁型提供者 | 已接受 | 2026-10-18 |
| [0007](0007-fire-interval-semantics.md) | FireInterval/FireCD 的修饰语义 | 已接受 | 2026-10-18 |
| [0008](0008-volume-aim-hit-distribution.md) | 实战情景改用体积预瞄命中分布（volume-aim） | 已接受 | 2026-10-19 |
| [0009](0009-slot-occupancy-exclusivity.md) | 配装遵守官方额外占用槽位（extra_occupancy） | 已接受 | 2026-10-19 |
