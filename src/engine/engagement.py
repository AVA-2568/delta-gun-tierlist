"""实战 TTK 组装：``WeaponState`` + 弹药 + 护甲 + 情景 + 距离 → 击杀时间（秒）。

TTK 定义（已确认口径）：

    实战 TTK = 首发扳机延迟 + 第 E 发击发时刻 + 弹丸飞行时间

与官方 dfttk 默认口径完全对齐：
- 首发扳机延迟：``fire_delay_seconds``（大部分武器为 0，个别蓄力/转管武器存在开火延迟）。
- 击发时刻：单发/全自动等价于 ``(E - 1) × 射击间隔``；连发武器按官方 ``sdkTiming`` 节拍的精确射击时间线计算。对于多弹丸武器（霰弹枪），E 为实际扣动扳机发数（``trigger_pulls = shots / effective_projectiles``，独头弹有效弹丸为 1，鹿弹/箭形弹按武器弹丸数计算）。
- 弹丸飞行时间：``距离 / 原始初速``，使用**不含精校修正**的原始初速。

口径边界：

| 项 | 处理 | 理由 |
| :-- | :-- | :-- |
| 弹丸飞行时间（初速） | 计入 TTK | 对齐官方 dfttk 默认口径（采用不含精校修正的原始初速） |
| 开镜时间 | 参考列输出 | 开镜由玩家操作/据枪状态决定，不计入击杀耗时 |
| 换弹 | 忽略 | 官方击杀假设 ``singleMagazineNoReload``（单弹匣不换弹） |
| 命中率修正（后坐/散布） | 忽略 | 「打得中打不中」属另一维度，见改枪指南 |

因此 TTK 只由官方验证过的量构成——``E[N]``（3774 个样本点全量复现官方
``candidateMetrics``：逐位一致 1435、|Δ|≤1e-9 1574、|Δ|>1e-2 仅 3 个残余偏差点，经白盒
对拍证明为官方上游数据自相矛盾，详见 ``data/game/provenance.json`` 的
``integrity.official_reproduction_residual``）、精确射击时间线（291 个官方候选取整后与官方
整数 rpm 全对）与武器原始初速——**全链路可复现、可证伪，无自主参数**。

推论：官方精校的全部作用目标（开镜、后坐、散布、初速、镜距/倍率）均不改变命中发数或射击节拍，初速精校不影响官方 TTK 原始初速口径，全部维度交由玩家按手感自行调校。

距离场锁定 **0–80m**（官方排行 `distanceRange`），不做外推。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.engine.ballistics import DamageContext, build_context_from_state

DISTANCE_MIN = 0.0
DISTANCE_MAX = 80.0


class ScenarioError(KeyError):
    """情景或护甲等级缺失。"""


@dataclass(frozen=True)
class TtkResult:
    """单点 TTK 结果（全部为可复算的中间量）。"""

    distance_m: float
    ttk_seconds: float
    expected_shots: float
    ads_seconds: float
    flight_seconds: float
    fire_interval_seconds: float
    rpm: float
    falloff: float
    effective_range_m: float
    muzzle_velocity_mps: float

    @property
    def ttk_milliseconds(self) -> float:
        return self.ttk_seconds * 1000.0


# --------------------------------------------------------------------------- #
# 情景
# --------------------------------------------------------------------------- #
def resolve_scenario(game_data: Any, scenario_id: str) -> Dict[str, Any]:
    """按 id 取情景定义（``data/tables/scenarios.json`` 收录官方 21 情景）。"""
    for scenario in game_data.scenarios_raw.get("scenarios", []):
        if scenario["scenario_id"] == scenario_id:
            return scenario
    raise ScenarioError(f"未收录的情景：{scenario_id}")


def scenario_armor(game_data: Any, scenario: Mapping[str, Any]) -> Dict[str, Any]:
    """取情景对应的护甲定义，并用情景声明的耐久覆盖（官方 preset 可低于 max）。"""
    level = str(scenario["armor_level"])
    base = game_data.defense(int(level))
    if base is None:
        raise ScenarioError(f"未收录的护甲等级：{level}")
    helmet = dict(base["helmet"])
    armor = dict(base["armor"])
    helmet["max_durability"] = float(scenario.get("helmet_durability") or helmet["max_durability"])
    armor["max_durability"] = float(scenario.get("armor_durability") or armor["max_durability"])
    return {"helmet": helmet, "armor": armor}


def pick_ammo(game_data: Any, profile_key: str, ammo_level: int) -> Dict[str, Any]:
    """按情景弹药等级为该枪选弹（同级多弹取 ``ammo_item_id`` 最小者，规则同官方池）。"""
    weapon = game_data.get_weapon(profile_key)
    record = game_data.ammo_at_level(weapon, int(ammo_level))
    if record is None:
        raise ScenarioError(f"{profile_key} 无 {ammo_level} 级弹药")
    return record


# --------------------------------------------------------------------------- #
# TTK
# --------------------------------------------------------------------------- #
def damage_context(
    state: Any,
    ammo_record: Mapping[str, Any],
    armor_definition: Mapping[str, Any],
    hit_probabilities: Mapping[str, float],
    distance_m: float,
) -> DamageContext:
    return build_context_from_state(
        state=state,
        ammo_record=ammo_record,
        armor_definition=armor_definition,
        hit_probabilities=hit_probabilities,
        distance_m=distance_m,
        armor_level=int(armor_definition["armor"]["level"]),
    )


def ttk_at(
    state: Any,
    ammo_record: Mapping[str, Any],
    armor_definition: Mapping[str, Any],
    hit_probabilities: Mapping[str, float],
    distance_m: float,
) -> TtkResult:
    """单点实战 TTK（秒）：``首发扳机延迟 + 第 E 发击发时刻 + 弹丸飞行时间``。

    对齐官方 dfttk 默认口径：
    - 击发时刻：单发/全自动为 ``(E - 1) × 间隔``，连发武器按官方 sdkTiming 节拍的精确射击时间线；
      多弹丸武器按扣动扳机发数（弹丸数 / 有效弹丸数）计算。
    - 飞行时间：使用不含精校修正的原始初速。
    - 开镜时间作为参考量返回，不叠加进 TTK。
    """
    ctx = damage_context(state, ammo_record, armor_definition, hit_probabilities, distance_m)
    shots = ctx.expected_kill_shots()
    ammo_name = str(ammo_record.get("name") or "")
    projectile_count = int(getattr(state, "projectile_count", 1) or 1)
    effective_projectiles = 1 if "独头" in ammo_name else max(1, projectile_count)
    trigger_pulls = shots / effective_projectiles

    interval = float(state.fire_interval_seconds)
    velocity = float(state.original_muzzle_velocity_mps)
    # TTK = 首发扳机延迟 + 第 E 发击发时刻 + 弹丸飞行时间，与 dfttk 默认口径一致：
    # 击发时刻全自动/单发等价 (E-1)×间隔，连发按官方 sdkTiming 节拍的精确射击时间线；
    # 飞行时间用**不含精校修正**的原始初速。
    flight = (float(distance_m) / velocity) if velocity > 0 else 0.0
    ttk = max(0.0, state.fire_delay_seconds + state.shots_to_fire_seconds(trigger_pulls) + flight)
    return TtkResult(
        distance_m=float(distance_m),
        ttk_seconds=ttk,
        expected_shots=trigger_pulls,
        ads_seconds=float(state.ads_milliseconds()) / 1000.0,
        flight_seconds=(float(distance_m) / velocity) if velocity > 0 else 0.0,
        fire_interval_seconds=interval,
        rpm=float(state.rpm),
        falloff=float(state.falloff_rate(distance_m)),
        effective_range_m=float(state.effective_range_m),
        muzzle_velocity_mps=velocity,
    )


def ttk_curve(
    state: Any,
    ammo_record: Mapping[str, Any],
    armor_definition: Mapping[str, Any],
    hit_probabilities: Mapping[str, float],
    distances: Optional[Sequence[float]] = None,
) -> List[TtkResult]:
    """在 0–80m 上按 1m 步长（默认）计算 TTK 曲线。"""
    if distances is None:
        distances = [float(d) for d in range(int(DISTANCE_MIN), int(DISTANCE_MAX) + 1)]
    return [
        ttk_at(state, ammo_record, armor_definition, hit_probabilities, float(d)) for d in distances
    ]


# 距离带（设计规范 6 节）。带语义互斥：首带 [lo, hi]（含 0 m），其余 (lo, hi]——
# 端点 15/30/50 m 只归属一个带，与衰减段 ``(from_m, to_m]`` 同一口径。
DISTANCE_BANDS: Dict[str, tuple] = {
    "贴脸": (0.0, 15.0),
    "近距": (15.0, 30.0),
    "中距": (30.0, 50.0),
    "远距": (50.0, 80.0),
}

#: 距离带顺序（唯一真源；tiering 与 renderers 均从此处引用）
BAND_NAMES: tuple = tuple(DISTANCE_BANDS)


def band_summary(curve: Sequence[TtkResult]) -> Dict[str, Dict[str, float]]:
    """按距离带聚合：带内 TTK（毫秒）与带内平均期望击杀发数。

    带互斥（首带 ``[lo, hi]``、其余 ``(lo, hi]``）：15/30/50 m 端点只计入一个带，
    不重复统计。``mean_expected_shots`` 供上层计算击杀成本使用，故**不做取整**——
    它乘上单价后由成本函数统一四舍五入。
    """
    out: Dict[str, Dict[str, float]] = {}
    for index, (name, (lo, hi)) in enumerate(DISTANCE_BANDS.items()):
        if index == 0:
            points = [r for r in curve if lo <= r.distance_m <= hi]
        else:
            points = [r for r in curve if lo < r.distance_m <= hi]
        if not points:
            continue
        ttks = [r.ttk_milliseconds for r in points]
        shots = [r.expected_shots for r in points]
        out[name] = {
            "min_ms": round(min(ttks), 2),
            "max_ms": round(max(ttks), 2),
            "mean_ms": round(sum(ttks) / len(ttks), 2),
            "mean_expected_shots": sum(shots) / len(shots),
        }
    return out
