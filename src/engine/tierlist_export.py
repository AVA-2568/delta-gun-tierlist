"""Payload 序列化：把内部排名结构转成 ``data/榜单/*.json`` 的稳定形状。

从 :mod:`src.engine.tiering` 抽出。依赖方向：tierlist_export → tiering（单向）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from src.engine import engagement as eg
from src.engine.ammo_pricing import DEFAULT_CURRENCY
from src.engine.tiering import BAND_NAMES, SPARE_AMMO_ROUNDS, TIER_QUANTILES, GunRanking

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from src.engine.ammo_pricing import AmmoPriceTable
    from src.engine.part_pricing import PartPriceTable
    from src.engine.weapon_pricing import WeaponPriceTable


def to_export(
    rankings: List[GunRanking],
    thresholds: Mapping[str, Mapping[str, float]],
    scenario_id: str,
    excluded: Optional[Sequence[Mapping[str, str]]] = None,
    price_table: Optional["AmmoPriceTable"] = None,
    weapon_price_table: Optional["WeaponPriceTable"] = None,
    part_price_table: Optional["PartPriceTable"] = None,
) -> Dict[str, Any]:
    """序列化为可写入 JSON 的结构（渲染层直接消费，禁止二次计算）。"""
    payload_rankings: List[Dict[str, Any]] = []
    for entry in rankings:
        payload_rankings.append(
            {
                "profile_key": entry.profile_key,
                "weapon_id": entry.weapon_id,
                "name": entry.display_name,
                "base_name": entry.base_name,
                "category": entry.category,
                "is_variant": entry.is_variant,
                "variant_item_id": entry.variant_item_id,
                "variant_item_name": entry.variant_item_name,
                "loadout": entry.loadout,
                "tuning": entry.tuning,
                "entry_kind": entry.entry_kind,
                "loadout_effects": [dict(e) for e in entry.loadout_effects],
                "ttk_by_distance_ms": dict(entry.ttk_by_distance_ms),
                "stock_bands": {
                    name: {k: round(v, 2) for k, v in stats.items()}
                    for name, stats in entry.stock_bands.items()
                },
                "overall_mean_ms": round(entry.overall_mean_ms, 2),
                "expected_shots_0m": round(entry.expected_shots_0m, 4),
                "rpm": round(entry.rpm, 1),
                "ads_ms_reference": round(entry.ads_ms_reference, 2),
                "muzzle_velocity_mps": round(entry.muzzle_velocity_mps, 2),
                "effective_range_m": round(entry.effective_range_m, 2),
                "ammo": {
                    "ammo_item_id": entry.ammo_item_id,
                    "name": entry.ammo_name,
                    "caliber": entry.ammo_caliber,
                    "price_daily": entry.ammo_price_daily,
                },
                "gun_price_daily": entry.gun_price_daily,
                "parts_price_daily": entry.parts_price_daily,
                "full_price_180rd": entry.full_price_180rd,
                "bands": {
                    name: {
                        "rank": b.rank,
                        "tier": b.tier,
                        "mean_ms": round(b.mean_ms, 2),
                        "worst_ms": round(b.worst_ms, 2),
                        "best_ms": round(b.best_ms, 2),
                        "mean_expected_shots": round(b.mean_expected_shots, 6),
                        "kill_cost": b.kill_cost,
                    }
                    for name, b in entry.bands.items()
                },
            }
        )
    # 变体出厂态行与本体的最优配装行同属「可参赛武器」，直接计入 eligible
    eligible = len(rankings)
    excluded_count = len(excluded or [])

    return {
        "scenario_id": scenario_id,
        "ammo_price_meta": {
            "currency": price_table.currency if price_table is not None else DEFAULT_CURRENCY,
            "window": dict(price_table.window) if price_table is not None else {},
            "updated_at": price_table.updated_at if price_table is not None else "",
            "available": bool(price_table is not None and not price_table.is_empty),
        },
        "weapon_price_meta": {
            "currency": (
                weapon_price_table.currency if weapon_price_table is not None else DEFAULT_CURRENCY
            ),
            "window": dict(weapon_price_table.window) if weapon_price_table is not None else {},
            "updated_at": (
                weapon_price_table.updated_at if weapon_price_table is not None else ""
            ),
            "available": bool(
                weapon_price_table is not None and not weapon_price_table.is_empty
            ),
            "spare_ammo_rounds": SPARE_AMMO_ROUNDS,
        },
        "part_price_meta": {
            "currency": (
                part_price_table.currency if part_price_table is not None else DEFAULT_CURRENCY
            ),
            "window": dict(part_price_table.window) if part_price_table is not None else {},
            "updated_at": (
                part_price_table.updated_at if part_price_table is not None else ""
            ),
            "available": bool(
                part_price_table is not None and not part_price_table.is_empty
            ),
        },
        "ranking_key": "band_mean_ttk_ms",
        "robustness_key": "band_worst_ttk_ms",
        "tier_quantiles": list(TIER_QUANTILES),
        "weapon_pool_count": eligible + excluded_count,
        "eligible_weapon_count": eligible,
        "excluded_weapon_count": excluded_count,
        "ranked_entry_count": len(rankings),
        "excluded_weapons": [dict(item) for item in (excluded or [])],
        "tier_thresholds_ms": {
            band: {tier: round(value, 2) for tier, value in per.items()}
            for band, per in thresholds.items()
        },
        "band_definitions": {
            name: {"from_m": eg.DISTANCE_BANDS[name][0], "to_m": eg.DISTANCE_BANDS[name][1]}
            for name in BAND_NAMES
        },
        "weapons": payload_rankings,
    }
