"""Pydantic data contract models for weapon metadata, ammo pricing, builds, and simulation results."""

from typing import List
from pydantic import BaseModel, ConfigDict, Field


class DamageDropoff(BaseModel):
    """Damage and armor damage values at specific distance intervals."""

    model_config = ConfigDict(extra="forbid")

    max_distance: float = Field(gt=0, description="衰减起始/截止距离（米）")
    chest_damage: float = Field(gt=0, description="胸部基础肉伤")
    armor_damage: float = Field(gt=0, description="护甲耐久削减值")


class GunMeta(BaseModel):
    """Core weapon metadata and baseline performance characteristics."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, description="枪械唯一标识（如 m4a1）")
    name: str = Field(min_length=1, description="枪械中文名称")
    category: str = Field(min_length=1, description="类别：突击步枪 / 冲锋枪 / 精确射手步枪 / 机枪")
    caliber: str = Field(min_length=1, description="弹药口径（如 5.56x45mm）")
    rpm: int = Field(gt=0, description="射速（发/分钟）")
    bullet_velocity: float = Field(gt=0, description="子弹初速 (m/s)")
    base_price: int = Field(ge=0, description="裸枪指导参考价（哈夫币）")
    default_mag_size: int = Field(gt=0, description="默认/实用弹匣容量")
    ads_time_ms: int = Field(gt=0, description="开镜时间 (毫秒)")
    recoil_control: float = Field(ge=0.0, le=100.0, description="垂直/水平后坐控制综合评分 (0~100)")
    stability: float = Field(ge=0.0, le=100.0, description="瞄准走火稳定度 (0~100)")
    dropoffs: List[DamageDropoff] = Field(min_length=1, description="距离衰减区间表")


class AmmoPrice(BaseModel):
    """Market price and penetration attributes for ammunition."""

    model_config = ConfigDict(extra="forbid")

    caliber: str = Field(min_length=1, description="口径")
    level: int = Field(ge=1, le=7, description="弹药等级 (通常为 4 或 5)")
    name: str = Field(min_length=1, description="弹药完整名称")
    penetration: int = Field(ge=0, description="穿透等级数值 (如 40, 50)")
    price_per_round: int = Field(gt=0, description="市场单发价格 (哈夫币)")
    source: str = Field(min_length=1, description="数据源标识 (zxfps_live, snapshot, baseline)")
    updated_at: str = Field(min_length=1, description="ISO-8601 或时间戳字符串")


class WeaponBuild(BaseModel):
    """Recommended weapon modification plan and tactical attachment attributes."""

    model_config = ConfigDict(extra="forbid")

    gun_id: str = Field(min_length=1, description="对应枪械ID")
    build_name: str = Field(min_length=1, description="方案名称")
    build_code: str = Field(min_length=1, description="游戏内改枪码")
    mod_cost: int = Field(ge=0, description="改装配件总造价（哈夫币）")
    ads_modifier_ms: int = Field(default=0, description="改装对开镜时间的影响 (ms)")
    recoil_bonus: float = Field(default=0.0, description="改装后坐优化增益")
    attachments: List[str] = Field(default_factory=list, description="配件清单")


class SimulationResult(BaseModel):
    """Output metrics from the discrete bullet-by-bullet combat simulation."""

    model_config = ConfigDict(extra="forbid")

    stk: int = Field(gt=0, description="击杀所需发数 (Shots to Kill)")
    theoretical_ttk_ms: float = Field(ge=0.0, description="理论击杀时间 (ms)")
    practical_ttk_ms: float = Field(ge=0.0, description="实战经散布修正后的击杀时间 (ms)")
    ehr: float = Field(ge=0.0, le=1.0, description="有效命中率 (Effective Hit Rate, 0~1.0)")


class TierEntry(BaseModel):
    """Final tier list entry under a specific scenario matrix condition."""

    model_config = ConfigDict(extra="forbid")

    gun_id: str = Field(min_length=1, description="枪械ID")
    gun_name: str = Field(min_length=1, description="枪械中文名称")
    category: str = Field(min_length=1, description="类别")
    distance_m: int = Field(gt=0, description="交战距离 (m)")
    armor_level: int = Field(ge=1, le=7, description="护甲等级")
    ammo_level: int = Field(ge=1, le=7, description="弹药等级")
    stk: int = Field(gt=0, description="击杀所需发数")
    practical_ttk_ms: float = Field(ge=0.0, description="实战击杀时间 (ms)")
    ammo_60_cost: int = Field(ge=0, description="60发备弹成本（哈夫币）")
    total_loadout_cost: int = Field(ge=0, description="裸枪+改装+60发备弹总成本（哈夫币）")
    single_kill_cost: int = Field(ge=0, description="单次击杀消耗弹药成本（哈夫币）")
    combat_score: float = Field(ge=0.0, le=100.0, description="战力效能分 (0~100)")
    handling_score: float = Field(ge=0.0, le=100.0, description="操控容错分 (0~100)")
    cost_score: float = Field(ge=0.0, le=100.0, description="经济性价比分 (0~100)")
    composite_score: float = Field(ge=0.0, le=100.0, description="加权综合得分 (0~100)")
    tier: str = Field(min_length=1, description="梯队级别 (T0, T1, T2, T3)")
    build_code: str = Field(min_length=1, description="推荐实用改枪码")
    tags: List[str] = Field(default_factory=list, description="特性标签")


class DataSourceStatus(BaseModel):
    """Health status and fallback level metadata of external price data sources."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, description="数据源标识 (zxfps_live, snapshot, baseline)")
    is_fallback: bool = Field(default=False, description="是否处于降级状态")
    fallback_tier: int = Field(default=0, ge=0, le=2, description="降级梯次：0=在线实时, 1=历史快照, 2=固化基准")
    updated_at: str = Field(min_length=1, description="数据更新时间戳")
    message: str = Field(default="", description="状态附加提示或警告说明")
