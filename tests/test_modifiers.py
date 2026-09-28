"""修饰层路由契约测试（Task 17 修复轮 1）。

钉死 ``part_tuning_layer`` → ``accumulate`` 的 **hitbox 路由**契约：

``Initial`` 型效果若作用于 ``DamagePointId.<部位>DamageRate`` 目标，必须落到
``hitbox_overrides``（键为 :func:`hitbox_key` 还原的部位别名），而**不是** ``overrides``。

判定依据：``state.overrides`` 只被消费 ``FireRateMode`` / ``RT_MAG_CAPACITY`` /
``ProjectileNumPerShot`` 三个键（``weapon_state.py``），没有任何 hitbox 目标；而
``hitbox_overrides`` 会被合入伤害档案的部位倍率。旧的内联实现把 hitbox 目标写进
``overrides``，等于静默丢弃该精校效果。

当前官方精校数据只携带 ``Mult_A`` / ``Addend``，故该路由暂无数据触发；本用例以合成
数据钉死契约，使将来数据若引入 ``Initial`` 型精校，行为变化会**失败一个测试**而不是
静默移动数值。

放在独立文件而非 ``tests/test_loadout.py``：后者的主题是配装枚举与 TTK 相关性
（面向 ``loadout.py``），本用例钉的是 ``modifiers.py`` 的修饰层路由，且只用合成数据、
不依赖官方目录，独立成文件便于全速运行且契约归属清晰。
"""

from src.engine.modifiers import hitbox_key, part_tuning_layer

HEAD_TARGET = "DamagePointId.HeadDamageRate"
#: 部位别名必须落在 damage profile ``hitbox_multipliers`` 的键空间内
#: （实测其键为 head / upperChest / lowerChest / upperArm / lowerArm / thigh / lowerLeg）。
HEAD_ALIAS = "head"


def _tuning_part(target: str, modifier: str, output: float) -> dict:
    """构造一件只带一个滑块、曲线恒为 ``output`` 的合成配件。"""
    return {
        "tunes": [
            {
                "tune_id": "synthetic",
                "min_value": 0.0,
                "max_value": 10.0,
                "default_value": 5.0,
                "functions": [
                    {"target": target, "modifier": modifier, "curve": [[0.0, output], [10.0, output]]}
                ],
            }
        ]
    }


def test_initial_tuning_on_hitbox_target_routes_to_hitbox_overrides():
    """``Initial`` + hitbox 目标 → ``hitbox_overrides``（契约钉死，防止静默改道）。"""
    assert hitbox_key(HEAD_TARGET) == HEAD_ALIAS

    layer = part_tuning_layer(_tuning_part(HEAD_TARGET, "Initial", 1.35), {})

    assert layer.hitbox_overrides == {HEAD_ALIAS: 1.35}
    # 反向断言：旧内联实现会写这里，而该键无人消费 → 静默丢效果
    assert layer.overrides == {}
