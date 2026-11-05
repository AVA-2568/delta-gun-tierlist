"""Payload 序列化：把内部排名结构转成 ``data/榜单/*.json`` 的稳定形状。

从 :mod:`src.engine.tiering` 抽出。依赖方向：tierlist_export → tiering（单向）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from src.engine import engagement as eg
from src.engine.ammo_pricing import DEFAULT_CURRENCY
from src.engine.engagement import BAND_NAMES
from src.engine.tiering import SPARE_AMMO_ROUNDS, TIER_QUANTILES, GunRanking

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from src.engine.ammo_pricing import AmmoPriceTable
    from src.engine.part_pricing import PartPriceTable
    from src.engine.weapon_pricing import WeaponPriceTable

#: 对外发布层级：只发布 T0 / T1；T2 / T3 仍参与分位阈值计算，但不落盘、不渲染。
#: 口径见 ADR-0010（取代 ADR-0002 的「T1 前 100 行」截断规则）。
PUBLISHED_TIERS: tuple = ("T0", "T1")


def _config_rows(rankings: List[GunRanking]) -> Dict[str, List[Dict[str, Any]]]:
    """按 weapon_id 聚合全部配置行（含未发布的 T2/T3 与非最优配置）。

    只保留配置明细页需要的字段：配置本身、弹药、射击参数与各带 TTK，
    不带价格与订单信息（价格随情景刷新，明细页不展示成本）。
    """
    by_weapon: Dict[str, List[Dict[str, Any]]] = {}
    for entry in rankings:
        by_weapon.setdefault(entry.weapon_id, []).append(
            {
                "profile_key": entry.profile_key,
                "name": entry.base_name,
                "loadout": dict(entry.loadout),
                "entry_kind": entry.entry_kind,
                "ammo": entry.ammo_name,
                "ammo_item_id": entry.ammo_item_id,
                "rpm": round(entry.rpm, 1),
                "expected_shots_0m": round(entry.expected_shots_0m, 3),
                "muzzle_velocity_mps": round(entry.muzzle_velocity_mps, 1),
                "effective_range_m": round(entry.effective_range_m, 1),
                "bands": {
                    band: {
                        "mean_ms": round(result.mean_ms, 1),
                        "worst_ms": round(result.worst_ms, 1),
                        "tier": result.tier,
                        "is_best": result.is_best,
                    }
                    for band, result in entry.bands.items()
                },
            }
        )
    for rows in by_weapon.values():
        rows.sort(
            key=lambda row: (
                sum(b["mean_ms"] for b in row["bands"].values()) / len(row["bands"])
                if row["bands"]
                else float("inf")
            )
        )
    return by_weapon


def is_published_entry(entry: GunRanking) -> bool:
    """条目是否进对外榜单：任一带是该枪最优配置且层级属于 T0/T1 即发布。

    榜单每带每枪只展示其最优配置（``is_best``），层级由该枪最优配置决定；
    同枪其他配置不单独成行。
    """
    return any(
        band.is_best and band.tier in PUBLISHED_TIERS for band in entry.bands.values()
    )



def to_export(
    rankings: List[GunRanking],
    thresholds: Mapping[str, Mapping[str, float]],
    scenario_id: str,
    excluded: Optional[Sequence[Mapping[str, str]]] = None,
    price_table: Optional["AmmoPriceTable"] = None,
    weapon_price_table: Optional["WeaponPriceTable"] = None,
    part_price_table: Optional["PartPriceTable"] = None,
) -> Dict[str, Any]:
    """序列化为可写入 JSON 的结构（渲染层直接消费，禁止二次计算）。

    只序列化 T0/T1 条目（:data:`PUBLISHED_TIERS`）：T2/T3 仍参与分层阈值计算，
    但不进对外榜单（JSON 与文档一致，见 ADR-0010）。
    """
    published = [entry for entry in rankings if is_published_entry(entry)]
    payload_rankings: List[Dict[str, Any]] = []
    for entry in published:
        payload_rankings.append(
            {
                "profile_key": entry.profile_key,
                "weapon_id": entry.weapon_id,
                "name": entry.display_name,
                "base_name": entry.base_name,
                "category": entry.category,
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
                        "is_best": b.is_best,
                        "mean_ms": round(b.mean_ms, 2),
                        "worst_ms": round(b.worst_ms, 2),
                        "best_ms": round(b.best_ms, 2),
                        "mean_expected_shots": round(b.mean_expected_shots, 6),
                        "kill_cost": b.kill_cost,
                    }
                    for name, b in entry.bands.items()
                    # 只发布「该枪在本带的最优配置」且层级为 T0/T1 的带：
                    # 非最优配置不占榜单行，T2/T3 不公开
                    if b.is_best and b.tier in PUBLISHED_TIERS
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
        "published_entry_count": len(published),
        "published_tiers": list(PUBLISHED_TIERS),
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
        # 每把枪的全部起枪配置（不限 T0/T1、不限带内最优）：供「武器配置明细页」渲染，
        # 榜单表每带每枪只展示 is_best 一行，完整配置在这里可查。
        "configs": _config_rows(rankings),
    }
