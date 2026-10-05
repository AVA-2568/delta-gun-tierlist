"""修饰层语义内核：官方 modifier 作用到面板/派生平上的合成规则。

从 :mod:`src.engine.weapon_state` 抽出，职责单一——只做修饰语义合成，
不含配装枚举、规则解析与档案装配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from src.engine.curves import Curve, apply_modifier, modifier_factor

# 下列目标前缀 / profile 槽位常量只服务于本内核，故随内核一并从
# ``weapon_state`` 迁出；``weapon_state`` 不再引用它们。
_ATTR_TARGET_PREFIX = "WeaponMainAttribute.MainAttrValues."
_DISPLAY_TARGET_PREFIX = "DisplayAttrValues."

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


def factor(modifier: Optional[str], value: Optional[float]) -> Optional[float]:
    """把单次乘性修饰换算成倍率；语义真源在 :func:`curves.modifier_factor`。"""
    return modifier_factor(modifier, value)


def hitbox_key(target: str) -> Optional[str]:
    if not target.startswith(_HITBOX_PREFIX) or not target.endswith(_HITBOX_SUFFIX):
        return None
    stem = target[len(_HITBOX_PREFIX) : -len(_HITBOX_SUFFIX)]
    if not stem:
        return None
    return stem[0].lower() + stem[1:]


def falloff_from_bullet_profile(profile: Mapping[str, Any]) -> List[Dict[str, float]]:
    """把弹道 profile 的衰减声明还原为 ``falloff_segments``（schema 同官方摘要）。

    ``attenuation_distances_cm`` 为各速率段**终点**（厘米）：``[0, valid)``
    固定 1.0，``rate[i]`` 施加于 ``[dist[i-1], dist[i])``。与 catalog
    ``damageFalloffSegments`` 的派生关系已用 MK4/M4A1 base 全量比对确认。
    """
    valid = float(profile.get("valid_distance_cm") or 0.0) / 100.0
    distances = [float(x) / 100.0 for x in profile.get("attenuation_distances_cm") or []]
    rates = [float(x) for x in profile.get("attenuation_rates") or []]
    if valid <= 0.0 or not distances or len(distances) != len(rates):
        return []
    segments: List[Dict[str, float]] = [{"from_m": 0.0, "to_m": valid, "rate": 1.0}]
    previous = valid
    for distance, rate in zip(distances, rates):
        segments.append({"from_m": previous, "to_m": distance, "rate": rate})
        previous = distance
    return segments


def accumulate(layer: ModifierLayer, target: Optional[str], modifier: Optional[str],
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
        hitbox = hitbox_key(target)
        if hitbox is not None and value is not None:
            layer.hitbox_overrides[hitbox] = value
            return

    factor_value = factor(modifier, value)
    if factor_value is not None:
        layer.scales[target] = layer.scales.get(target, 1.0) * factor_value
        return
    if modifier == "Addend" and value is not None:
        layer.addends[target] = layer.addends.get(target, 0.0) + value
        return
    if modifier == "Initial" and value is not None:
        layer.overrides[target] = value


def apply_attribute_effects(panel: Dict[str, float], part: Mapping[str, Any]) -> None:
    for effect in part.get("effects") or []:
        target = effect.get("target") or ""
        if not target.startswith(_ATTR_TARGET_PREFIX):
            continue
        index = target[len(_ATTR_TARGET_PREFIX) :]
        if index not in panel:
            continue
        panel[index] = apply_modifier(panel[index], effect.get("modifier"), effect.get("value"))


def part_effect_layer(part: Mapping[str, Any]) -> ModifierLayer:
    layer = ModifierLayer()
    for effect in part.get("effects") or []:
        accumulate(
            layer,
            effect.get("target"),
            effect.get("modifier"),
            effect.get("value"),
            effect.get("value_ref"),
        )
    return layer


def part_tuning_layer(part: Mapping[str, Any], setting: Mapping[str, float]) -> ModifierLayer:
    """按给定滑块读数求一件配件的精校修饰层。``setting`` 为 ``{tune_id: 读数}``。

    每条 function 求值后**委托** :func:`accumulate` 逐条累加，因此继承它的目标过滤与
    路由规则：跳过 ``WeaponMainAttribute.MainAttrValues.`` / ``DisplayAttrValues.``
    前缀目标（面板属性另由 :func:`apply_attribute_effects` 处理）与空目标；``Initial``
    作用于 :data:`PROFILE_SLOT_TARGETS` 槽位时改指向 profile 引用。

    **hitbox 路由**：``Initial`` 作用于 ``DamagePointId.<部位>DamageRate`` 时落到
    ``hitbox_overrides``（键为 :func:`hitbox_key` 还原的部位别名，如 ``head``），
    **而非** ``overrides``。这是正确的路由——``overrides`` 只被消费
    ``FireRateMode`` / ``RT_MAG_CAPACITY`` / ``ProjectileNumPerShot`` 三个键，把
    hitbox 目标写进去等于静默丢弃该效果；``hitbox_overrides`` 则会被
    :mod:`src.engine.weapon_state` 合入伤害档案的部位倍率。

    精校 function 归一化后只有 ``target`` / ``modifier`` / ``curve`` 三键（没有
    ``value_ref``），故 ``Initial`` + profile 槽位这一支在本路径下不登记任何内容。

    实测口径（2026-09-28 数据快照，配件表全量 541 个滑块 /
    1285 条 function）：精校 function 只携带 ``Mult_A``(1061) 与 ``Addend``(224)，
    不含 ``Initial``；上述 hitbox 路由目前无官方数据触发，由单元测试钉死契约。
    """
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
            accumulate(layer, func.get("target"), func.get("modifier"), value, None)
    return layer
