# ADR-0007：FireInterval/FireCD 的修饰语义（何时是冗余声明）

- 状态：已接受
- 日期：2026-10-18
- 决策人：YH
- 影响面：`src/engine/weapon_state.py`、`src/engine/modifiers.py`、`tests/test_loadout.py`

## 背景

原实现把 `FireInterval` / `FireCD` 一律当作「与射击节拍同源的冗余声明」，
只登记不应用。该假设对多数枪管成立，但对三类 S10/S11 改件是错的：

| 改件 | 效果 | 原实现 | 官方/实测 |
| :-- | :-- | --: | --: |
| M700 HVK 旋风枪身系统 | `FireInterval Initial 0.45` | 48 rpm | 133 rpm |
| M700 HVK 旋风强化导气 | `FireInterval Addend -0.30715` | 48 rpm | 420 rpm |
| 93R HVK 鼬鼠冲锋枪套件 | `FireRateMode 0` + `FireInterval Mult_C 0.559` | 375 rpm | 671 rpm |
| AS-Val 刺客高级枪管 | `FireRateMode 1` + `FireInterval Mult_A 0.62` | 680 rpm | 680 rpm（冗余，不得叠加） |

## 决策

按「是否改写射击模式」分流：

1. **无 `FireRateMode` 改写**：`FireInterval` 就是射速机制本身。
   顺序为 `Initial` 覆盖 → `Addend` 求和 → `Mult_A`/`Mult_C` 连乘。
2. **有 `FireRateMode` 改写**：基础间隔由 `sdkTiming` 按新模式重算；
   `FireInterval` 的 `Initial` / `Addend` / `Mult_A` 视为冗余声明，**不叠加**；
   但 `Mult_C`（纯倍率）仍生效——93R 鼬鼠套件用 0.559 把 375 rpm 拉到 671 rpm。
3. `ModifierLayer` 增加与 `scales` 并行的 `mult_c` 映射，仅供需要区分
   `Mult_A`（增量倍率）与 `Mult_C`（纯倍率）的派生量使用；其余目标行为不变。

## 后果

- M700 S11 套件（133 / 420 rpm）、93R 鼬鼠套件（671 rpm）进入正确 TTK 区间。
- AS-Val 刺客枪管保持 680 rpm，不因新增逻辑回归。
- 新增 3 条测试钉死三种语义；全量重算后相关武器排名变化属预期。

## 否决的方案

| 方案 | 否决理由 |
| :-- | :-- |
| 继续一律忽略 FireInterval | M700 / 93R 的 S10/S11 套件射速完全错误 |
| 一律叠加 FireInterval | AS-Val 刺客枪管会从 680 掉到 420 rpm，回归既有正确结果 |
