"""武器状态解析链：裸枪面板 × 配件效果 × 精校 → 实机规则量。

口径
----
全部锁定国服 ``sol``（烽火地带）分支。上游 sol/mp 在初速、部分后坐机制曲线上确有差异，
混用会得到错误结果。

官方解析语义（均已用实机数据锚点核验）
--------------------------------------
1. **面板属性** 由 ``weapon.panel_attributes`` 给出（裸枪基准）。配件通过
   ``WeaponMainAttribute.MainAttrValues.N`` 修改之；``DisplayAttrValues.N`` 只是 UI 镜像，
   不重复计入。修饰符语义见 :func:`src.engine.curves.apply_modifier`。
2. **精校** 每件配件自带 ``tunes`` 滑块，其 ``functions`` 的曲线以滑块读数为输入，
   输出倍率/加量后**直接作用于规则目标**，不经过面板属性。因此「配件效果」与「精校效果」
   是两个彼此独立、都需要累加的修饰层。
3. **规则量** 按 ``mappingType`` 分成两类，分开存放以免误用：

   - ``AbsoluteMapping*``：输出**绝对物理量**（开镜秒数、射程厘米、初速 m/s）。
     ``v = curve(面板值)``；叠加 ``Addend`` 后乘上配件/精校的直接缩放。
   - ``DeltaMapping*``：输出**相对倍率**（相对裸枪的缩放系数）。
     ``m = curve(面板值 - 基准值)``；乘上配件/精校的直接缩放。
     后坐/散布/稳定这类量在实战建模中只需要相对倍率，故不做无谓的绝对值还原。

   说明：上游 ``mappingType`` 的 ``ThenScale`` 后缀表示「映射后再乘缩放」，但实测存在
   形如 ``GAiming_ADSTime`` + ``AbsoluteMapping``（无后缀）却被配件以
   ``Mult_A -0.16`` 直接修改的条目。若按字面只对 ``ThenScale`` 应用缩放，这类配件效果
   会被静默丢弃，与数据自相矛盾。因此本模块**一律累加**配件/精校的直接修饰；
   后缀仅作为上游语义注记保留在 ``rule_mapping_types`` 中。
4. **``directRuleTargets``** 是增量传播目标：没有独立 ``curveMapping`` 的目标
   （如 ``GBullet_Velocity``）继承所属属性的**相对变化**。

核验锚点
--------
- ``GAiming_ADSTime``：``handlingDefault:0:sol`` 在操控 50 处输出 0.35 s（350 ms）；
  M4A1（操控 58）得 302.4 ms。
- ``GBullet_Velocity``：attr2 ``Mult_A 0.30`` → M4A1 初速 575 → 747.5；
  ``Mult_A 0.18`` → 575 → 678.5。两者与官方 ``reference_candidates`` 逐位吻合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.engine.curves import Curve, CurveLibrary, apply_modifier

DEFAULT_MODE = "sol"

#: 面板属性索引（官方索引 2..6）
PANEL_ATTR_INDEXES: Tuple[str, ...] = ("2", "3", "4", "5", "6")

#: 官方属性索引 → 语义键（与 ``src.collectors.game_data_sync.PANEL_ATTR_KEYS`` 一致）
PANEL_ATTR_NAMES: Dict[str, str] = {
    "2": "effective_range",
    "3": "recoil_control",
    "4": "waist_accuracy",
    "5": "handling",
    "6": "stability",
}

_ATTR_TARGET_PREFIX = "WeaponMainAttribute.MainAttrValues."
_DISPLAY_TARGET_PREFIX = "DisplayAttrValues."

# --------------------------------------------------------------------------- #
# 规则目标常量
# --------------------------------------------------------------------------- #
RT_ADSTime = "GAiming_ADSTime"
RT_SPRINT_TO_FIRE = "GSprintToFireTime"
RT_ADS_MOVE_SPEED = "GMovement_ADSSpeed"
RT_SILENT_WALK = "GMovement_SilentWalkSpeed"
RT_VELOCITY = "GBullet_Velocity"
RT_RANGE = "GBullet_Range"
RT_RANGE_ONLY = "GBullet_OnlyRange"
RT_SPEED_ONLY = "GRange_OnlySpeed"
RT_ADS_SPREAD = "GSpread_ADS"
RT_HIP_SPREAD = "GSpread_Hip"
RT_HIP_SPREAD_CONTINUOUS = "GSpread_Hip_Continuous"
RT_RECOIL_H = "GRecoil_H"
RT_RECOIL_V = "GRecoil_V"
RT_RECOIL_HIP_H = "GRecoil_Hip"
RT_RATE_OF_FIRE = "GRateOfFire"
RT_FIRE_INTERVAL = "FireInterval"
RT_FIRE_CD = "FireCD"
RT_RECOIL_H_SHAKE = "GRecoil_HShake"
RT_RECOIL_V_SHAKE = "GRecoil_VShake"
RT_GUNKICK_SPRING = "GGunkickSpring"
RT_GUNKICK_RANDOM = "GGunkickRandom"
RT_MAG_CAPACITY = "GMagCapacity"
RT_CLIP_TIME = "ChangeClipTime"
RT_CLIP_TIME_EMPTY = "ChangeClipTimewhenEmpty"

#: 效果里对规则目标的别名 → 归一到规则目标。
#:
#: 此处刻意**不**把 ``GRange_OnlySpeed`` / ``GBullet_OnlyRange`` 归一到初速/射程：
#: 这两个目标与面板 attr2（优势射程）表达的是同一件事，而上游配件习惯同时声明两者。
#: 实测 ``MCX LT猎手枪管`` 同时带 ``MainAttrValues.2 Mult_A 0.3`` 与
#: ``GRange_OnlySpeed Mult_A 0.3``，官方候选初速为 **585 = 450 × 1.3**（只算一次）；
#: 若叠加则为 760.5（错）。反过来 ``AR加百列长枪管组合`` 只有面板 attr2 增量、
#: 没有显式修饰符，官方初速 747.5 = 575 × 1.3，说明**面板 attr2 的相对变化才是权威**。
#: 因此这两类显式修饰符仅登记在 ``scales`` 中供审计，不参与取值。
TARGET_ALIASES: Dict[str, str] = {}

#: ``Initial`` 引用型效果的目标 → profile 槽位
PROFILE_SLOT_TARGETS: Dict[str, str] = {
    "WaistShootSpreadId": "hip_spread",
    "WaistShootRecoilId": "hip_recoil",
    "AimingId.SpreadId": "ads_spread",
    "AimingId.RecoilId": "ads_recoil",
    "MovementSpeedId": "movement",
    "BulletFlyingId": "bullet",
    "AttackerValueId.DefaultDamageId": "damage",
}

_HITBOX_PREFIX = "DamagePointId."
_HITBOX_SUFFIX = "DamageRate"


# --------------------------------------------------------------------------- #
# 修饰层
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModifierLayer:
    """配件效果 / 精校合成的修饰层。

    ``scales`` 为乘积（已按修饰符语义还原为倍率），``addends`` 为求和，
    ``overrides`` 为绝对值覆盖（``Initial``），``profiles`` 为 profile 引用替换。
    """

    scales: Dict[str, float] = field(default_factory=dict)
    addends: Dict[str, float] = field(default_factory=dict)
    overrides: Dict[str, float] = field(default_factory=dict)
    profiles: Dict[str, str] = field(default_factory=dict)
    hitbox_overrides: Dict[str, float] = field(default_factory=dict)

    def merged_with(self, other: "ModifierLayer") -> "ModifierLayer":
        scales = dict(self.scales)
        for key, value in other.scales.items():
            scales[key] = scales.get(key, 1.0) * value
        addends = dict(self.addends)
        for key, value in other.addends.items():
            addends[key] = addends.get(key, 0.0) + value
        return ModifierLayer(
            scales=scales,
            addends=addends,
            overrides={**self.overrides, **other.overrides},
            profiles={**self.profiles, **other.profiles},
            hitbox_overrides={**self.hitbox_overrides, **other.hitbox_overrides},
        )


def _factor(modifier: Optional[str], value: Optional[float]) -> Optional[float]:
    """把单次乘性修饰换算成倍率。"""
    if value is None:
        return None
    if modifier == "Mult_A":
        return 1.0 + value
    if modifier == "Mult_C":
        return value
    return None


def _hitbox_key(target: str) -> Optional[str]:
    if not target.startswith(_HITBOX_PREFIX) or not target.endswith(_HITBOX_SUFFIX):
        return None
    stem = target[len(_HITBOX_PREFIX) : -len(_HITBOX_SUFFIX)]
    if not stem:
        return None
    return stem[0].lower() + stem[1:]


def _accumulate(layer: ModifierLayer, target: Optional[str], modifier: Optional[str],
                value: Optional[float], value_ref: Optional[str]) -> None:
    """把一条效果累加进修饰层（面板属性与 UI 镜像除外，由调用方处理）。"""
    if not target:
        return
    if target.startswith(_ATTR_TARGET_PREFIX) or target.startswith(_DISPLAY_TARGET_PREFIX):
        return

    if modifier == "Initial":
        slot = PROFILE_SLOT_TARGETS.get(target)
        if slot is not None:
            if value_ref:
                layer.profiles[slot] = value_ref
            return
        hitbox = _hitbox_key(target)
        if hitbox is not None and value is not None:
            layer.hitbox_overrides[hitbox] = value
            return

    rule_target = TARGET_ALIASES.get(target, target)
    factor = _factor(modifier, value)
    if factor is not None:
        layer.scales[rule_target] = layer.scales.get(rule_target, 1.0) * factor
        return
    if modifier == "Addend" and value is not None:
        layer.addends[rule_target] = layer.addends.get(rule_target, 0.0) + value
        return
    if modifier == "Initial" and value is not None:
        layer.overrides[rule_target] = value


def _apply_attribute_effects(panel: Dict[str, float], part: Mapping[str, Any]) -> None:
    for effect in part.get("effects") or []:
        target = effect.get("target") or ""
        if not target.startswith(_ATTR_TARGET_PREFIX):
            continue
        index = target[len(_ATTR_TARGET_PREFIX) :]
        if index not in panel:
            continue
        panel[index] = apply_modifier(panel[index], effect.get("modifier"), effect.get("value"))


def _part_effect_layer(part: Mapping[str, Any]) -> ModifierLayer:
    layer = ModifierLayer()
    for effect in part.get("effects") or []:
        _accumulate(
            layer,
            effect.get("target"),
            effect.get("modifier"),
            effect.get("value"),
            effect.get("value_ref"),
        )
    return layer


def _part_tuning_layer(part: Mapping[str, Any], setting: Mapping[str, float]) -> ModifierLayer:
    """按给定滑块读数求一件配件的精校修饰层。``setting`` 为 ``{tune_id: 读数}``。"""
    layer = ModifierLayer()
    for tune in part.get("tunes") or []:
        tune_id = tune["tune_id"]
        raw = setting.get(tune_id)
        if raw is None:
            x = float(tune.get("default_value") or 0.0)
        else:
            x = float(raw)
            low = float(tune.get("min_value") or 0.0)
            high = float(tune.get("max_value") or 0.0)
            if x < low - 1e-9 or x > high + 1e-9:
                raise ValueError(f"精校 {tune_id} 读数 {x} 超出官方范围 [{low}, {high}]")
        for func in tune.get("functions") or []:
            points = func.get("curve") or []
            if not points:
                continue
            value = Curve(points).evaluate(x)
            target = func.get("target")
            modifier = func.get("modifier")
            factor = _factor(modifier, value)
            if factor is not None:
                layer.scales[target] = layer.scales.get(target, 1.0) * factor
            elif modifier == "Addend":
                layer.addends[target] = layer.addends.get(target, 0.0) + value
            elif modifier == "Initial":
                layer.overrides[target] = value
    return layer


# --------------------------------------------------------------------------- #
# 武器状态
# --------------------------------------------------------------------------- #
@dataclass
class WeaponState:
    """一把枪在「某配装 + 某精校」下的实机状态。"""

    profile_key: str
    weapon_id: str
    display_name: str
    base_name: str
    category: str
    weapon_type: str
    mode: str = DEFAULT_MODE

    loadout: Dict[str, str] = field(default_factory=dict)
    tuning: Dict[str, Dict[str, float]] = field(default_factory=dict)

    base_panel: Dict[str, float] = field(default_factory=dict)
    panel: Dict[str, float] = field(default_factory=dict)
    panel_named: Dict[str, float] = field(default_factory=dict)

    #: 绝对量：开镜秒数、射程厘米、初速 m/s 等
    absolute_rules: Dict[str, float] = field(default_factory=dict)
    #: 相对倍率：后坐/散布/稳定等相对裸枪的缩放
    relative_rules: Dict[str, float] = field(default_factory=dict)
    rule_mapping_types: Dict[str, str] = field(default_factory=dict)

    scales: Dict[str, float] = field(default_factory=dict)
    addends: Dict[str, float] = field(default_factory=dict)
    overrides: Dict[str, float] = field(default_factory=dict)
    profile_refs: Dict[str, str] = field(default_factory=dict)
    hitbox_overrides: Dict[str, float] = field(default_factory=dict)

    ads_seconds: float = 0.0
    sprint_to_fire_seconds: float = 0.0
    rpm: float = 0.0
    fire_interval_seconds: float = 0.0
    muzzle_velocity_mps: float = 0.0
    effective_range_m: float = 0.0
    rate_of_fire_multiplier: float = 1.0
    attr2_ratio: float = 1.0
    burst_cadence_seconds: float = 0.0
    reload_seconds: float = 0.0
    empty_reload_seconds: float = 0.0
    clip_capacity: int = 0

    recoil_multipliers: Dict[str, float] = field(default_factory=dict)
    spread_multipliers: Dict[str, float] = field(default_factory=dict)

    spread_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    recoil_profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    movement_profile: Optional[Dict[str, Any]] = None
    bullet_profile: Optional[Dict[str, Any]] = None

    hitbox_multipliers: Dict[str, float] = field(default_factory=dict)
    base_damage: float = 0.0
    base_armor_damage: float = 0.0
    base_penetration_level: int = 0
    damage_profile_id: Optional[str] = None
    damage_profile_source: str = ""

    caliber: str = ""
    ammo_type_id: str = ""
    falloff_segments: List[Dict[str, float]] = field(default_factory=list)
    projectile_count: int = 1
    burst_count: Optional[int] = None

    notes: List[str] = field(default_factory=list)

    # ---------------------------------------------------------------- #
    def falloff_rate(self, distance_m: float) -> float:
        """距离衰减系数（分段阶梯，与官方 ``damageFalloffSegments`` 一致）。"""
        rate = 1.0
        for segment in self.falloff_segments:
            if distance_m >= float(segment["from_m"]):
                rate = float(segment["rate"])
            else:
                break
        return rate

    def damage_at(self, distance_m: float) -> float:
        """距离衰减后的单发基础伤害（未计弹药与护甲）。"""
        return self.base_damage * self.projectile_count * self.falloff_rate(distance_m)

    def armor_damage_at(self, distance_m: float) -> float:
        return self.base_armor_damage * self.projectile_count * self.falloff_rate(distance_m)

    def ads_milliseconds(self) -> float:
        return self.ads_seconds * 1000.0

    def shots_per_second(self) -> float:
        return 1.0 / self.fire_interval_seconds if self.fire_interval_seconds > 0 else 0.0

    def describe_panel(self) -> str:
        chunks = []
        for index in PANEL_ATTR_INDEXES:
            base = self.base_panel.get(index, 0.0)
            current = self.panel.get(index, 0.0)
            label = PANEL_ATTR_NAMES[index]
            if abs(current - base) > 1e-9:
                chunks.append(f"{label}={base:.0f}→{current:.0f}")
            else:
                chunks.append(f"{label}={current:.0f}")
        return " ".join(chunks)


# --------------------------------------------------------------------------- #
# 解析器
# --------------------------------------------------------------------------- #
class WeaponStateResolver:
    """把「配装 + 精校」解析为 :class:`WeaponState`。"""

    def __init__(self, game_data: Any, mode: str = DEFAULT_MODE):
        self.gd = game_data
        self.mode = mode
        self.curves: CurveLibrary = game_data.curves

    # ---------------------------------------------------------------- #
    @staticmethod
    def _socket_for_item(weapon: Mapping[str, Any], item_id: str) -> Optional[str]:
        """在武器的可选槽位中定位某配件的槽位。"""
        for socket in weapon.get("sockets") or []:
            if item_id in (socket.get("options") or []):
                return str(socket["socket_id"])
        for provider_id, sockets in (weapon.get("provider_sockets") or {}).items():
            if provider_id == item_id:
                continue
            for socket in sockets:
                if item_id in (socket.get("options") or []):
                    return str(socket["socket_id"])
        for candidate in weapon.get("reference_candidates") or []:
            for entry in candidate.get("loadout_config") or []:
                if str(entry.get("itemId")) == item_id:
                    return str(entry.get("slotPath"))
        return None

    def _build_loadout(
        self,
        weapon: Mapping[str, Any],
        loadout: Optional[Mapping[str, Any]],
    ) -> Tuple[Dict[str, str], List[str]]:
        """合成最终配装。

        顺序：官方默认件 → 变体强制自带件 → 调用方显式配装 → 官方 ``coupling`` 强制联动。
        变体（``is_variant``）必须挂载 ``variant_item_id``，因为归一化后的变体档案与基线
        共用 ``panel_attributes``/``rpm`` 等字段，变异完全由该配件承载。
        """
        notes: List[str] = []
        mounted: Dict[str, str] = {
            str(k): str(v) for k, v in (weapon.get("default_items") or {}).items()
        }

        variant_item = weapon.get("variant_item_id")
        if weapon.get("is_variant") and variant_item:
            socket_id = self._socket_for_item(weapon, str(variant_item))
            if socket_id is None:
                notes.append(f"变体件 {variant_item} 未能定位槽位")
            else:
                mounted[socket_id] = str(variant_item)

        # 官方候选配装是「差异集」，需要叠加在默认配装之上而非整体替换
        for socket_id, item_id in (loadout or {}).items():
            key = str(socket_id)
            if item_id in (None, "", 0):
                mounted.pop(key, None)
            else:
                mounted[key] = str(item_id)

        # coupling：condition 命中则强制把 mounted_item_id 装入 target_socket_id
        #
        # 必须做**槽位归属仲裁**：官方数据里存在多条 ``forced`` 规则争抢同一槽位的情况
        # （例：QJB201 的 rule4 与 rule11 都要写 slot4，条件分别是 13020000517 与 13120000380，
        # 而前者就在默认配装里）。若无仲裁，两条规则会互相覆盖，``while changed`` 永不收敛。
        # 语义取「先到者胜」：某槽位被首条规则占用后，其余规则不得改写，并记入 notes。
        changed = True
        mounted_items = set(mounted.values())
        claimed: Dict[str, str] = {}
        conflicts: List[str] = []
        guard = 0
        guard_limit = 4 * len(weapon.get("coupling") or []) + 8
        while changed and guard < guard_limit:
            guard += 1
            changed = False
            for rule in weapon.get("coupling") or []:
                if rule.get("mount_policy") != "forced":
                    continue
                conditions = set(rule.get("condition_item_ids") or [])
                if conditions and not (conditions & mounted_items):
                    continue
                target = str(rule.get("target_socket_id"))
                item = str(rule.get("mounted_item_id"))
                if not item:
                    continue
                owner = claimed.get(target)
                if owner is not None and owner != item:
                    conflicts.append(f"槽位 {target} 被规则争用：保留 {owner}，忽略 {item}")
                    continue
                if mounted.get(target) == item:
                    claimed.setdefault(target, item)
                    continue
                mounted[target] = item
                mounted_items.add(item)
                claimed[target] = item
                changed = True
        if conflicts:
            notes.extend(sorted(set(conflicts)))

        return mounted, notes

    # ---------------------------------------------------------------- #
    def resolve(
        self,
        profile_key: str,
        loadout: Optional[Mapping[str, Any]] = None,
        tuning: Optional[Mapping[str, Mapping[str, float]]] = None,
    ) -> WeaponState:
        """解析一把枪的实机状态。

        Args:
            profile_key: 形如 ``18010000001:base`` 的武器档案键。
            loadout: ``{socket_id: item_id}``；``None`` 表示使用官方默认配装。
            tuning: ``{item_id: {tune_id: 读数}}``；未给出的配件使用官方默认读数。
        """
        weapon = self.gd.get_weapon(profile_key)
        tuning_setting = {str(k): dict(v) for k, v in (tuning or {}).items()}
        resolved_loadout, loadout_notes = self._build_loadout(weapon, loadout)

        state = WeaponState(
            profile_key=profile_key,
            weapon_id=weapon["weapon_id"],
            display_name=weapon["display_name"],
            base_name=weapon["name"],
            category=weapon["category"],
            weapon_type=weapon["weapon_type"],
            mode=self.mode,
            loadout=resolved_loadout,
            tuning=tuning_setting,
            caliber=weapon.get("caliber") or "",
            ammo_type_id=str(weapon.get("ammo_type_id") or ""),
            falloff_segments=[dict(s) for s in (weapon.get("falloff_segments") or [])],
            projectile_count=int(weapon.get("projectile_count") or 1),
            burst_count=weapon.get("burst_count"),
            notes=list(loadout_notes),
        )

        base_panel = {
            index: float(weapon["panel_attributes"][PANEL_ATTR_NAMES[index]])
            for index in PANEL_ATTR_INDEXES
        }
        panel = dict(base_panel)
        layer = ModifierLayer()

        for socket_id, item_id in sorted(resolved_loadout.items()):
            part = self.gd.get_part(item_id)
            if part is None:
                state.notes.append(f"槽位 {socket_id} 的配件 {item_id} 未收录")
                continue
            _apply_attribute_effects(panel, part)
            layer = layer.merged_with(_part_effect_layer(part))
            setting = tuning_setting.get(str(item_id)) or {}
            layer = layer.merged_with(_part_tuning_layer(part, setting))

        state.base_panel = base_panel
        state.panel = panel
        state.panel_named = {PANEL_ATTR_NAMES[i]: panel[i] for i in PANEL_ATTR_INDEXES}
        state.scales = layer.scales
        state.addends = layer.addends
        state.overrides = layer.overrides
        state.profile_refs = dict(layer.profiles)
        state.hitbox_overrides = layer.hitbox_overrides

        self._resolve_rules(weapon, state)
        self._resolve_profiles(weapon, state)
        self._resolve_damage(weapon, state)
        return state

    # ---------------------------------------------------------------- #
    def _resolve_rules(self, weapon: Mapping[str, Any], state: WeaponState) -> None:
        rules = weapon.get("attribute_rules") or {}

        for index in PANEL_ATTR_INDEXES:
            node = rules.get(index) or {}
            base_value = state.base_panel[index]
            current_value = state.panel[index]
            primary_ratio: Optional[float] = None

            for mapping in node.get("curveMappings") or []:
                target = mapping.get("target")
                if not target:
                    continue
                mapping_type = str(mapping.get("mappingType") or "AbsoluteMapping")
                curve_id = (mapping.get("curveIds") or {}).get(self.mode)
                curve = self.curves.get(curve_id) if curve_id else None
                scale = state.scales.get(target, 1.0)
                addend = state.addends.get(target, 0.0)

                if mapping_type.startswith("Absolute"):
                    value = (curve.evaluate(current_value) if curve else 0.0) * scale + addend
                    state.absolute_rules[target] = value
                    if primary_ratio is None:
                        primary_ratio = (
                            current_value / base_value if abs(base_value) > 1e-12 else 1.0
                        )
                else:
                    delta = current_value - base_value
                    multiplier = (curve.evaluate(delta) if curve else 1.0) * scale + addend
                    state.relative_rules[target] = multiplier
                    if primary_ratio is None:
                        primary_ratio = multiplier
                state.rule_mapping_types[target] = mapping_type

            # directRuleTargets：无独立曲线的目标继承该属性的相对变化
            ratio = primary_ratio if primary_ratio is not None else 1.0
            for target in node.get("directRuleTargets") or []:
                if target in state.rule_mapping_types:
                    continue
                base_rule = self._base_rule_value(weapon, target)
                scale = state.scales.get(target, 1.0)
                if base_rule is None:
                    state.relative_rules[target] = ratio * scale
                else:
                    state.absolute_rules[target] = base_rule * ratio * scale
                state.rule_mapping_types[target] = "directRuleTarget"

        # ---- 派生量 ----
        ads = state.absolute_rules.get(RT_ADSTime)
        state.ads_seconds = (
            float(ads)
            if ads is not None
            else float((weapon.get("aiming") or {}).get("ads_on_s") or 0.0)
        )

        timings = weapon.get("timings") or {}
        sprint_rule = state.relative_rules.get(RT_SPRINT_TO_FIRE)
        sprint_base = float(timings.get("sprint_to_fire_s") or 0.0)
        state.sprint_to_fire_seconds = sprint_base * sprint_rule if sprint_rule is not None else sprint_base

        # 射速：官方候选的 ``fire_rate`` 由「射击节拍」决定，规则如下（4 个锚点互证）：
        #
        # 1. 默认节拍 = 目录 ``shotIntervalSeconds``（已等于所选模式的等效间隔）。
        #    例：MK4 的 0.0756667 s 正是连发节拍 ``((3-1)×0.051+0.125)/3``；
        #        M16A4 的 0.11811 s 同理。
        # 2. ``FireRateMode`` 被配件改写时按 ``sdkTiming`` 重算节拍：
        #    ``>=1`` 用连发节拍 ``((burstCount-1)×burstFireInterval + burstFireCd)/burstCount``，
        #    ``0`` 用 ``fireInterval``。
        #    例：MK4 + 深空镀铬枪管（改为 0）→ 0.0688 s → 872.09 rpm（官方 872）；
        #        AS-Val + 刺客高级枪管（改为 1）→ 0.088235 s → 680.0 rpm（官方 680）。
        # 3. ``GRateOfFire`` 作用于节拍：``Mult_A +0.25`` → 间隔 ×1.25，
        #    ASh-12 战斧 / HVK双发 均为 500 → 400 rpm。
        # 4. ``FireInterval`` / ``FireCD`` 与节拍量同源，属冗余声明，**不叠加**
        #    （与 ``GRange_OnlySpeed`` 同类，理由见 ``TARGET_ALIASES`` 注释）。
        sdk = weapon.get("sdk_timing") or {}
        burst_count = int(sdk.get("burst_count") or 0)
        burst_cadence = (
            ((burst_count - 1) * float(sdk.get("burst_fire_interval_s") or 0.0)
             + float(sdk.get("burst_fire_cd_s") or 0.0)) / burst_count
            if burst_count > 1
            else 0.0
        )
        base_interval = float(weapon.get("fire_interval_s") or 0.0)
        base_mode_burst = str(sdk.get("fire_rate_mode") or "") == "Burst"
        mode_override = state.overrides.get("FireRateMode")
        if mode_override is not None and (float(mode_override) >= 1.0) != base_mode_burst:
            if float(mode_override) >= 1.0:
                base_interval = burst_cadence or float(sdk.get("fire_interval_s") or 0.0)
            else:
                base_interval = float(sdk.get("fire_interval_s") or 0.0)
        interval_scale = state.scales.get(RT_RATE_OF_FIRE, 1.0)
        interval = base_interval * interval_scale
        state.rate_of_fire_multiplier = interval_scale
        state.fire_interval_seconds = interval
        state.rpm = 60.0 / interval if interval > 0 else 0.0
        state.burst_cadence_seconds = burst_cadence

        # 初速：面板 attr2（优势射程）的相对变化传播到 GBullet_Velocity。
        attr2_ratio = (
            state.panel["2"] / state.base_panel["2"]
            if abs(state.base_panel["2"]) > 1e-12
            else 1.0
        )
        state.attr2_ratio = attr2_ratio
        velocity = state.absolute_rules.get(RT_VELOCITY)
        if velocity is not None:
            state.muzzle_velocity_mps = float(velocity)
        else:
            # ``GBullet_Velocity`` 属 attr2 的 ``directRuleTargets``，当枪械未声明独立曲线时
            # 落入 ``relative_rules``（= 面板射程相对变化 × 配件/精校的直接倍率）。
            # 必须用该相对量，否则配件与「长度」精校对初速的效果会被丢弃。
            relative = state.relative_rules.get(RT_VELOCITY)
            factor = relative if relative is not None else attr2_ratio
            state.muzzle_velocity_mps = float(weapon.get("muzzle_velocity_mps") or 0.0) * factor

        range_cm = state.absolute_rules.get(RT_RANGE)
        state.effective_range_m = (
            float(range_cm) / 100.0
            if range_cm is not None
            else float(weapon.get("valid_range_m") or 0.0) * attr2_ratio
        )

        # 距离衰减分段随优势射程等比缩放。官方机制：M4A1 装长枪管后，
        # ``validDamageRange`` 40→52、衰减段 40/70/1000 → 52/91/1300，
        # 恰为 attr2 比值 1.3 的等比缩放（由 dynamic 文件 damageModel 反解确认）。
        if state.falloff_segments and abs(attr2_ratio - 1.0) > 1e-12:
            state.falloff_segments = [
                {
                    **segment,
                    "from_m": float(segment.get("from_m", 0.0)) * attr2_ratio,
                    "to_m": float(segment.get("to_m", 0.0)) * attr2_ratio,
                }
                for segment in state.falloff_segments
            ]

        capacity = state.overrides.get(RT_MAG_CAPACITY)
        state.clip_capacity = (
            int(capacity) if capacity is not None else int(weapon.get("clip_capacity") or 0)
        )
        projectiles = state.overrides.get("ProjectileNumPerShot")
        if projectiles is not None:
            state.projectile_count = max(1, int(round(projectiles)))
        state.reload_seconds = float(timings.get("reload_s") or 0.0) * state.scales.get(RT_CLIP_TIME, 1.0)
        state.empty_reload_seconds = float(timings.get("empty_reload_s") or 0.0) * state.scales.get(
            RT_CLIP_TIME_EMPTY, 1.0
        )

        state.recoil_multipliers = {
            "horizontal": state.relative_rules.get(RT_RECOIL_H, 1.0),
            "vertical": state.relative_rules.get(RT_RECOIL_V, 1.0),
            "hip_horizontal": state.relative_rules.get(RT_RECOIL_HIP_H, 1.0),
            "horizontal_shake": state.relative_rules.get(RT_RECOIL_H_SHAKE, 1.0),
            "vertical_shake": state.relative_rules.get(RT_RECOIL_V_SHAKE, 1.0),
            "gunkick_spring": state.relative_rules.get(RT_GUNKICK_SPRING, 1.0),
            "gunkick_random": state.relative_rules.get(RT_GUNKICK_RANDOM, 1.0),
        }
        state.spread_multipliers = {
            "ads": state.relative_rules.get(RT_ADS_SPREAD, 1.0),
            "hip": state.relative_rules.get(RT_HIP_SPREAD, 1.0),
            "hip_continuous": state.relative_rules.get(RT_HIP_SPREAD_CONTINUOUS, 1.0),
        }

    @staticmethod
    def _base_rule_value(weapon: Mapping[str, Any], target: str) -> Optional[float]:
        if target == RT_VELOCITY:
            return float(weapon.get("muzzle_velocity_mps") or 0.0)
        return None

    # ---------------------------------------------------------------- #
    def _resolve_profiles(self, weapon: Mapping[str, Any], state: WeaponState) -> None:
        refs = weapon.get("references") or {}
        aiming = self.gd.get_profile(refs.get("aiming_profile_id")) or {}
        slot_ids: Dict[str, Optional[str]] = {
            "hip_spread": refs.get("waist_spread_profile_id"),
            "hip_recoil": refs.get("waist_recoil_profile_id"),
            "ads_spread": aiming.get("ads_spread_profile_id"),
            "ads_recoil": aiming.get("ads_recoil_profile_id"),
            "movement": refs.get("movement_profile_id"),
            "bullet": refs.get("bullet_profile_id"),
        }
        slot_ids.update(state.profile_refs)

        for slot in ("hip_spread", "ads_spread", "hip_recoil", "ads_recoil"):
            profile = self.gd.get_profile(slot_ids.get(slot))
            if profile is None:
                state.notes.append(f"缺失 {slot} profile（id={slot_ids.get(slot)}）")
                continue
            if slot.endswith("spread"):
                state.spread_profiles[slot] = profile
            else:
                state.recoil_profiles[slot] = profile
        state.movement_profile = self.gd.get_profile(slot_ids.get("movement"))
        state.bullet_profile = self.gd.get_profile(slot_ids.get("bullet"))
        state.profile_refs = {k: v for k, v in slot_ids.items() if v}

    def _resolve_damage(self, weapon: Mapping[str, Any], state: WeaponState) -> None:
        # 配件可用 ``AttackerValueId.DefaultDamageId`` **整体替换**伤害档案
        # （基础伤害、甲伤、穿透等级、部位倍率一起换），必须优先采用。
        swapped = self.gd.get_profile(state.profile_refs.get("damage"))
        if swapped is not None and swapped.get("kind") != "damage":
            swapped = None
        profile = swapped or weapon.get("damage_profile") or {}
        state.damage_profile_id = profile.get("profile_id")
        state.damage_profile_source = (
            "part-swap" if swapped else weapon.get("damage_profile_source", "catalog-summary")
        )
        state.base_damage = float(profile.get("base_damage") or weapon.get("flesh_damage") or 0.0)
        state.base_armor_damage = float(
            profile.get("base_armor_damage") or weapon.get("armor_damage") or 0.0
        )
        state.base_penetration_level = int(profile.get("base_penetration_level") or 0)

        hitbox = {
            str(k): float(v)
            for k, v in (
                profile.get("hitbox_multipliers") or weapon.get("hitbox_multipliers") or {}
            ).items()
        }
        hitbox.update(state.hitbox_overrides)
        state.hitbox_multipliers = hitbox

        # 配件可用 ``BulletFlyingId`` 替换弹道 profile：此时初速以新 profile 为基准，
        # 再按面板 attr2 的相对变化平移，**并叠加配件/精校对初速的直接倍率**。
        # 锚点：MK47 余烬枪管（attr2 无变化）官方初速 525 → 700，正是换弹道 profile 的结果；
        #       ASh-12 战斧重型枪管 官方 340 → 500 同理。
        # 例：M4A1 + AR特勤一体消音组合，初速基准换为 profile 值后再乘「长度」精校倍率
        #     （+10 mm → ×1.09），否则精校对初速的效果会被静默丢弃。
        if state.bullet_profile:
            profile_speed = float(state.bullet_profile.get("initial_speed_cm_s") or 0.0) / 100.0
            if profile_speed > 0.0:
                velocity_scale = state.scales.get(RT_VELOCITY, 1.0)
                state.muzzle_velocity_mps = profile_speed * state.attr2_ratio * velocity_scale
            if RT_RANGE not in state.absolute_rules:
                valid = float(state.bullet_profile.get("valid_distance_cm") or 0.0) / 100.0
                if valid > 0.0:
                    state.effective_range_m = valid * state.attr2_ratio


def resolve_weapon_state(
    game_data: Any,
    profile_key: str,
    loadout: Optional[Mapping[str, Any]] = None,
    tuning: Optional[Mapping[str, Mapping[str, float]]] = None,
    mode: str = DEFAULT_MODE,
) -> WeaponState:
    """便捷入口。"""
    return WeaponStateResolver(game_data, mode=mode).resolve(
        profile_key, loadout=loadout, tuning=tuning
    )
