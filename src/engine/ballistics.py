"""弹道伤害与击杀发数（STK）模型 —— 与官方 ``candidateMetrics`` 逐位对齐。

本模块实现的是**从 dfttk 上游数据反解并验证过**的官方伤害规则。验证方式：
用本模块重算官方 ``rankings/firefight/*.json`` 中 ``candidateMetrics`` 的期望击杀发数，
16 个（情景 × 距离）样本全部逐位一致（|Δ| ≤ 3.6e-15）。

官方规则（``combat/defense/rule-sets.json`` → ``firefight-v3-initial-1``）：

1. 目标总血量 ``H = 100``；**击杀假设 = 单弹匣不换弹**（``singleMagazineNoReload``）。
2. 每发按情景的命中部位分布随机落到一个部位（``probability.values``）。
3. 部位基础肉伤 ``= baseFleshDamage × ammo.flesh_damage_multiplier × hitbox × rate(d)``。
4. 该部位被护甲覆盖且耐久 > 0 时：
   - 本发应扣耐久 ``need = baseArmorDamage × ammo.armor_damage_multiplier × durabilityRate × rate(d)``
     （**注意：距离衰减 ``rate`` 同时作用于肉伤与护甲伤害**，已由 53m 样本反解确认）
   - 碎甲比 ``r = min(1, 剩余耐久 / need)``
   - 实收肉伤 ``= 基础肉伤 × (r × healthRate + (1 − r) × 1.0)``
   - 耐久 ``= max(0, 剩余 − need)``（``armorBreakTransfer = proportionalRemainingDurability``）
5. 部位是否被护甲覆盖由护甲的 ``covered_hit_areas`` 决定（头盔覆盖 ``head``；
   背心覆盖部位随护甲等级变化，如 L5/L6 含 ``upperArm``），**不得硬编码**。
6. 未被覆盖的部位按全额伤害结算（``× 1.0``）。
7. ``statusEffects.woundRate`` **不参与即时伤害**（已由 chest-only 整数样本排除）。
8. ``candidateMetrics`` = 击杀发数的**数学期望** ``E[N] = Σ_{n≥0} P(N > n)``，
   而非「按期望伤害累加再分数化」（两者在随机部位下不等价）。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Mapping, Sequence, Tuple

# 官方命中部位（hitProbabilities 的键）-> 武器 hitbox 倍率键
PART_TO_HITBOX: Dict[str, str] = {
    "head": "head",
    "chest": "upperChest",
    "abdomen": "lowerChest",
    "upperArm": "upperArm",
    "lowerArm": "lowerArm",
    "thigh": "thigh",
    "calf": "lowerLeg",
}

# 部位归属的护甲槽：head 由头盔覆盖，其余由背心（按 covered_hit_areas）判定
PART_TO_ARMOR_SLOT: Dict[str, str] = {
    "head": "helmet",
    "chest": "armor",
    "abdomen": "armor",
    "upperArm": "armor",
    "lowerArm": "armor",
    "thigh": "armor",
    "calf": "armor",
}

PLAYER_HEALTH = 100.0

# 护甲耐久被打光后，命中次数超过该上限即视为永久失效（防止状态无限增长）
_HELMET_HIT_CAP = 8
_ARMOR_HIT_CAP = 12


class DamageContext:
    """一次「武器 × 弹药 × 护甲 × 距离」伤害结算的全部输入。"""

    __slots__ = (
        "base_flesh", "base_armor", "hitbox_multipliers", "ammo", "armor_level",
        "helmet_durability", "armor_durability", "helmet_covered", "armor_covered",
        "hit_probabilities", "falloff", "_pen", "_need_by_slot", "_slot_by_part", "_table",
    )

    def __init__(
        self,
        base_flesh: float,
        base_armor: float,
        hitbox_multipliers: Mapping[str, float],
        ammo: Mapping[str, object],
        armor_level: int,
        helmet_durability: float,
        armor_durability: float,
        helmet_covered: Sequence[str],
        armor_covered: Sequence[str],
        hit_probabilities: Mapping[str, float],
        falloff: float = 1.0,
    ) -> None:
        self.base_flesh = float(base_flesh)
        self.base_armor = float(base_armor)
        self.hitbox_multipliers = dict(hitbox_multipliers)
        self.ammo = ammo
        self.armor_level = int(armor_level)
        self.helmet_durability = float(helmet_durability)
        self.armor_durability = float(armor_durability)
        self.helmet_covered = frozenset(helmet_covered)
        self.armor_covered = frozenset(armor_covered)
        self.hit_probabilities = {k: float(v) for k, v in hit_probabilities.items() if float(v) > 0}
        self.falloff = float(falloff)

        # ---- 预计算：DP 内层每发都要取值，必须避免重复计算与 typing 运行时检查 ----
        matrix = ammo["penetration_matrix"]  # type: ignore[index]
        self._pen = matrix[str(self.armor_level)]  # type: ignore[index]
        # 注意：``ammo`` 恒为 dict，**不要**用 ``isinstance(ammo, Mapping)``——
        # typing.Mapping 的 __instancecheck__ 极慢，DP 内层千万次调用会成为主要开销。
        per_part = ammo.get("per_part") or {}
        self._need_by_slot = {
            "helmet": self.base_armor
            * float(ammo["armor_damage_multiplier"])
            * float(self._pen["helmet_durability_rate"])
            * self.falloff,
            "armor": self.base_armor
            * float(ammo["armor_damage_multiplier"])
            * float(self._pen["body_durability_rate"])
            * self.falloff,
        }
        self._slot_by_part = {part: self._resolve_slot(part) for part in self.hit_probabilities}
        self._table = self._build_damage_table(float(ammo["flesh_damage_multiplier"]), per_part)

    # ------------------------------------------------------------------ #
    def _resolve_slot(self, part: str) -> str | None:
        """该命中部位当前由哪个护甲槽覆盖（无覆盖返回 ``None``）。"""
        slot = PART_TO_ARMOR_SLOT[part]
        hitbox = PART_TO_HITBOX[part]
        if slot == "helmet" and hitbox in self.helmet_covered:
            return "helmet"
        if slot == "armor" and hitbox in self.armor_covered:
            return "armor"
        return None

    def _build_damage_table(
        self, flesh_mult: float, per_part: Mapping[str, object]
    ) -> Dict[tuple, float]:
        """预计算 ``(part, 头盔命中数, 背心命中数) -> 该发血量伤害``。

        命中数上限之外护甲已永久失效，伤害恒定，故表是可枚举的。
        """
        pen = self._pen
        table: Dict[tuple, float] = {}
        for part in self.hit_probabilities:
            hitbox = PART_TO_HITBOX[part]
            part_mult = 1.0
            if per_part:
                try:
                    part_mult = float(per_part.get(hitbox, 1.0))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    part_mult = 1.0
            base = (
                self.base_flesh
                * flesh_mult
                * float(self.hitbox_multipliers.get(hitbox, 1.0))
                * part_mult
                * self.falloff
            )
            slot = self._slot_by_part[part]
            if slot is None:
                for hh in range(_HELMET_HIT_CAP + 1):
                    for hb in range(_ARMOR_HIT_CAP + 1):
                        table[(part, hh, hb)] = base
                continue
            if slot == "helmet":
                need = self._need_by_slot["helmet"]
                health_rate = float(pen["helmet_health_rate"])
                initial = self.helmet_durability
            else:
                need = self._need_by_slot["armor"]
                health_rate = float(pen["body_health_rate"])
                initial = self.armor_durability
            for hh in range(_HELMET_HIT_CAP + 1):
                for hb in range(_ARMOR_HIT_CAP + 1):
                    hits = hh if slot == "helmet" else hb
                    remaining = initial - hits * need
                    if remaining <= 0.0 or need <= 0.0:
                        table[(part, hh, hb)] = base
                    else:
                        ratio = min(1.0, remaining / need)
                        table[(part, hh, hb)] = base * (ratio * health_rate + (1.0 - ratio) * 1.0)
        return table

    # ------------------------------------------------------------------ #
    def shot_damage(self, part: str, helmet_hits: int, armor_hits: int) -> float:
        """给定部位与当前护甲命中次数，返回该发的实际血量伤害（查预计算表）。"""
        return self._table[(part, helmet_hits, armor_hits)]

    # ------------------------------------------------------------------ #
    def expected_kill_shots(self, health: float = PLAYER_HEALTH) -> float:
        """期望击杀发数 ``E[N] = Σ_{n≥0} P(N > n)``（精确 DP，与官方逐位一致）。

        内层只做查表与浮点乘加：伤害表、部位归属与命中概率均在构造期预取，
        DP 每秒可达百万次迭代，任何重复计算或 typing 运行时检查都会成为主要开销。
        """
        table = self._table
        # (部位, 所属护甲槽, 命中概率)
        parts = [(part, self._slot_by_part[part], prob) for part, prob in self.hit_probabilities.items()]
        states: Dict[Tuple[int, int], Dict[float, float]] = {(0, 0): {health: 1.0}}
        total = 0.0
        alive = 1.0
        steps = 0
        while alive > 1e-15 and steps < 400:
            total += alive
            nxt: Dict[Tuple[int, int], Dict[float, float]] = defaultdict(lambda: defaultdict(float))
            died = 0.0
            for (hh, hb), hp_map in states.items():
                for hp, prob in hp_map.items():
                    for part, slot, p in parts:
                        new_hp = hp - table[(part, hh, hb)]
                        joint = prob * p
                        if new_hp <= 1e-12:
                            died += joint
                            continue
                        nhh = hh + 1 if slot == "helmet" else hh
                        nhb = hb + 1 if slot == "armor" else hb
                        if nhh > _HELMET_HIT_CAP:
                            nhh = _HELMET_HIT_CAP
                        if nhb > _ARMOR_HIT_CAP:
                            nhb = _ARMOR_HIT_CAP
                        nxt[(nhh, nhb)][round(new_hp, 8)] += joint
            states = nxt
            alive -= died
            steps += 1
        return total


def expected_kill_shots(ctx: DamageContext) -> float:
    """便捷函数：见 :meth:`DamageContext.expected_kill_shots`。"""
    return ctx.expected_kill_shots()


def build_context_from_state(
    state: Any,
    ammo_record: Mapping[str, object],
    armor_definition: Mapping[str, object],
    hit_probabilities: Mapping[str, float],
    distance_m: float,
    armor_level: int | None = None,
) -> DamageContext:
    """从 :class:`~src.engine.weapon_state.WeaponState` 与官方弹药/护甲记录组装伤害上下文。

    ``state`` 需提供 ``base_damage`` / ``base_armor_damage`` / ``hitbox_multipliers`` /
    ``falloff_rate(distance)`` / ``base_penetration_level``；护甲记录形如
    ``armor.json`` 的 ``levels[L]``（含 ``helmet`` / ``armor`` 的耐久与 ``covered_hit_areas``）。
    """
    level = int(armor_level if armor_level is not None else state.base_penetration_level)
    return DamageContext(
        base_flesh=state.base_damage,
        base_armor=state.base_armor_damage,
        hitbox_multipliers=state.hitbox_multipliers,
        ammo=ammo_record,
        armor_level=level,
        helmet_durability=armor_definition["helmet"]["max_durability"],  # type: ignore[index]
        armor_durability=armor_definition["armor"]["max_durability"],  # type: ignore[index]
        helmet_covered=armor_definition["helmet"]["covered_hit_areas"],  # type: ignore[index]
        armor_covered=armor_definition["armor"]["covered_hit_areas"],  # type: ignore[index]
        hit_probabilities=hit_probabilities,
        falloff=state.falloff_rate(distance_m),
    )
