"""弹道伤害与击杀发数（STK）模型 —— 与官方 ``candidateMetrics`` 对齐。

本模块实现的是**从 dfttk 上游数据反解并验证过**的官方伤害规则。验证方式：
用本模块重算官方 ``rankings/firefight/*.json`` 中 ``candidateMetrics`` 的期望击杀发数，
21 情景 / S12 数据集全量复现 **4029 个样本点**：逐位一致 1516、|Δ|≤1e-9 1593、
|Δ|≤1e-5 842、|Δ|≤1e-2 64、|Δ|>1e-2 14（最差 0.07218 发）。920 个残余偏差点
经白盒对拍（官方 dynamic damageModel 与 statusEffects 自声明参数独立重算）
**全部**证明为官方上游数据自相矛盾——官方参数重算与本地逐位一致而官方 E 偏离、
未归类 0 点，记录于 data/game/provenance.json 的
``integrity.official_reproduction_residual``。复现入口：
``python tools/verify_official_reproduction.py``（``--official-param-audit`` 为白盒对拍）；
回归测试 ``tests/test_official_reproduction.py`` 与数据完整性测试
``tests/test_data_integrity.py``（哈希）已入 CI。

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
9. S12 ``onHitEffects.detonation``（叠层引爆）：每发命中叠 1 层，层数达到
   ``stageStackCounts`` 阈值时追加**一次带护甲结算的额外命中**（作用于背心
   槽）。基础血伤 ``damage``、基础护甲伤害 ``armorDamage``、穿甲率取爆炸
   自带的 ``armorCorrection[护甲等级]``；爆炸不吃距离衰减与命中部位倍率，
   但额外扣背心耐久，故后续子弹的碎甲进度提前。``clearOnDetonate=false``，
   末个阈值之后按等间距继续触发至 ``maxStacks``。口径由 55 个 chest-only
   整数 STK 样本反解并零误差验证。``onHitEffects.burn`` 为时间轴 DoT，
   白盒对拍证实其不进官方 ``candidateMetrics`` 的发数期望。
"""

from __future__ import annotations

import math
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



class DamageContext:
    """一次「武器 × 弹药 × 护甲 × 距离」伤害结算的全部输入。"""

    __slots__ = (
        "base_flesh", "base_armor", "hitbox_multipliers", "ammo", "armor_level",
        "helmet_durability", "armor_durability", "helmet_covered", "armor_covered",
        "hit_probabilities", "falloff", "helmet_cap", "armor_cap", "_pen", "_need_by_slot", "_slot_by_part", "_table",
        "_detonation_base", "_detonation_need", "_detonation_health_rate",
        "_detonation_triggers", "_max_detonations",
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
        h_need = self._need_by_slot["helmet"]
        a_need = self._need_by_slot["armor"]
        self.helmet_cap = max(1, math.ceil(self.helmet_durability / h_need)) if h_need > 0 else 0
        self.armor_cap = max(1, math.ceil(self.armor_durability / a_need)) if a_need > 0 else 0
        self._slot_by_part = {part: self._resolve_slot(part) for part in self.hit_probabilities}

        # ---- S12 叠层引爆（onHitEffects.detonation）----
        # 每发命中叠 1 层；达到 stageStackCounts 阈值时追加一次「额外命中」：
        # 基础血伤 damage、基础护甲伤害 armorDamage，穿甲率取爆炸自带的
        # armorCorrection[护甲等级]。爆炸不吃距离衰减与命中部位倍率，但额外
        # 扣背心耐久（故 DP 的剩余耐久依赖已引爆次数）。clearOnDetonate=false，
        # 末个阈值之后按等间距继续触发至 maxStacks。口径由 55 个 chest-only
        # 整数 STK 样本反解并零误差验证。
        detonation = (ammo.get("on_hit_effects") or {}).get("detonation") or {}
        damage = float(detonation.get("damage") or 0.0)
        armor_damage = float(detonation.get("armorDamage") or 0.0)
        correction = (detonation.get("armorCorrection") or {}).get(str(self.armor_level)) or {}
        health_rate = float(correction.get("bodyHealthRate") or 0.0)
        durability_rate = float(correction.get("bodyDurabilityRate") or 0.0)
        stages = [int(n) for n in (detonation.get("stageStackCounts") or [])]
        max_stacks = int(detonation.get("maxStacks") or 0)
        triggers = set(stages)
        if len(stages) >= 2:
            step = stages[1] - stages[0]
            if step > 0:
                n = stages[-1] + step
                while n <= max_stacks:
                    triggers.add(n)
                    n += step
        active = damage > 0.0 and bool(triggers)
        self._detonation_base = damage if active else 0.0
        self._detonation_need = armor_damage * durability_rate if active else 0.0
        self._detonation_health_rate = health_rate
        self._detonation_triggers = frozenset(triggers) if active else frozenset()
        self._max_detonations = len(triggers) if active else 0

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
        """预计算 ``(part, 头盔命中数, 背心命中数, 已引爆次数) -> 该发血量伤害``。

        引爆额外扣背心耐久，故剩余耐久同时依赖命中数与已引爆次数；两者上限
        之外护甲已永久失效、伤害恒定，故表仍可枚举。
        """
        pen = self._pen
        table: Dict[tuple, float] = {}
        det_need = self._detonation_need
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
            for det in range(self._max_detonations + 1):
                if slot is None:
                    for hh in range(self.helmet_cap + 1):
                        for hb in range(self.armor_cap + 1):
                            table[(part, hh, hb, det)] = base
                    continue
                if slot == "helmet":
                    need = self._need_by_slot["helmet"]
                    health_rate = float(pen["helmet_health_rate"])
                    initial = self.helmet_durability
                    det_extra = 0.0  # 爆炸只作用于背心槽
                else:
                    need = self._need_by_slot["armor"]
                    health_rate = float(pen["body_health_rate"])
                    initial = self.armor_durability
                    det_extra = det * det_need
                for hh in range(self.helmet_cap + 1):
                    for hb in range(self.armor_cap + 1):
                        hits = hh if slot == "helmet" else hb
                        remaining = initial - hits * need - det_extra
                        if remaining <= 0.0:
                            table[(part, hh, hb, det)] = base
                        elif need <= 0.0:
                            table[(part, hh, hb, det)] = base * health_rate
                        else:
                            ratio = min(1.0, remaining / need)
                            table[(part, hh, hb, det)] = base * (ratio * health_rate + (1.0 - ratio) * 1.0)
        return table

    # ------------------------------------------------------------------ #
    def expected_kill_shots(self, health: float = PLAYER_HEALTH) -> float:
        """期望击杀发数 ``E[N] = Σ_{n≥0} P(N > n)``（精确 DP，与官方逐位一致）。

        内层只做查表与浮点乘加：伤害表、部位归属与命中概率均在构造期预取，
        DP 每秒可达百万次迭代，任何重复计算或 typing 运行时检查都会成为主要开销。
        """
        table = self._table
        det_base = self._detonation_base
        det_need = self._detonation_need
        det_hr = self._detonation_health_rate
        det_triggers = self._detonation_triggers
        max_det = self._max_detonations
        a_need = self._need_by_slot["armor"]
        a_initial = self.armor_durability
        # (部位, 所属护甲槽, 命中概率)
        parts = [(part, self._slot_by_part[part], prob) for part, prob in self.hit_probabilities.items()]
        states: Dict[Tuple[int, int], Dict[float, float]] = {(0, 0): {health: 1.0}}
        total = 0.0
        alive = 1.0
        steps = 0
        det_count = 0
        while alive > 1e-15 and steps < 400:
            total += alive
            det_idx = min(det_count, max_det)
            nxt: Dict[Tuple[int, int], Dict[float, float]] = defaultdict(lambda: defaultdict(float))
            died = 0.0
            for (hh, hb), hp_map in states.items():
                for hp, prob in hp_map.items():
                    for part, slot, p in parts:
                        new_hp = hp - table[(part, hh, hb, det_idx)]
                        joint = prob * p
                        if new_hp <= 1e-12:
                            died += joint
                            continue
                        nhh = hh + 1 if slot == "helmet" else hh
                        nhb = hb + 1 if slot == "armor" else hb
                        if nhh > self.helmet_cap:
                            nhh = self.helmet_cap
                        if nhb > self.armor_cap:
                            nhb = self.armor_cap
                        nxt[(nhh, nhb)][round(new_hp, 8)] += joint
            # 叠层引爆：本发达阈值 → 对背心槽追加一次带护甲结算的命中。
            # 伤害依赖该路径的背心剩余耐久（子弹命中数 + 此前引爆次数），
            # 且本次爆炸再扣一份耐久（体现在下一步 det_count+1 的表索引）。
            if det_base and (steps + 1) in det_triggers:
                exploded: Dict[Tuple[int, int], Dict[float, float]] = defaultdict(lambda: defaultdict(float))
                for (hh, hb), hp_map in nxt.items():
                    remaining = a_initial - hb * a_need - det_count * det_need
                    if det_need > 0.0 and remaining > 0.0:
                        ratio = min(1.0, remaining / det_need)
                        dmg = det_base * (ratio * det_hr + (1.0 - ratio))
                    else:
                        dmg = det_base
                    for hp, prob in hp_map.items():
                        new_hp = hp - dmg
                        if new_hp <= 1e-12:
                            died += prob
                        else:
                            exploded[(hh, hb)][round(new_hp, 8)] += prob
                nxt = exploded
                det_count += 1
            states = nxt
            alive -= died
            steps += 1
        return total


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
