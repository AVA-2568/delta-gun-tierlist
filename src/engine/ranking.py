"""榜单编排：逐武器枚举起枪状态、评分、分层并组装排名条目。

从 :mod:`src.engine.tiering` 抽出。分层数学（``assign_tiers``）、排名条目模型
（``GunRanking``）与常量留在 tiering，本模块只负责编排；
JSON 序列化见 :mod:`src.engine.tierlist_export`。

依赖方向：ranking → tiering（单向）。tiering **不** import 本模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from src.engine import engagement as eg
from src.engine.loadout import LoadoutSolver, part_affects_ttk
from src.engine.tiering import (
    BAND_NAMES,
    BandResult,
    GunRanking,
    _effective_loadout,
    assign_tiers,
    compute_full_price,
    compute_kill_cost,
    compute_parts_price,
    summarize_loadout_effects,
)

if TYPE_CHECKING:  # pragma: no cover - 仅类型标注
    from src.engine.ammo_pricing import AmmoPriceTable
    from src.engine.part_pricing import PartPriceTable
    from src.engine.weapon_pricing import WeaponPriceTable

#: 当前赛季（赛季更迭时人工更新；榜单弹药候选只保留常驻与当前赛季限定弹，
#: 过期赛季限定弹视为实际无价值——持有者之外无法获取，数据仍保留在弹药表）。
CURRENT_SEASON = "S11"


def _ammo_in_season(record: Mapping[str, Any]) -> bool:
    """常驻弹恒有效；赛季限定弹仅当前赛季有效（``season_note`` 如 "S8赛季限定子弹"）。"""
    if not record.get("is_season_limited"):
        return True
    return CURRENT_SEASON in (record.get("season_note") or "")


def pick_priced_ammos(
    game_data: Any,
    profile_key: str,
    ammo_level: int,
    price_table: Optional["AmmoPriceTable"],
) -> List[Dict[str, Any]]:
    """该口径该等级的**全部有价弹**（市场可得），按 ``ammo_item_id`` 升序。

    弹维度展开的候选集口径：

    - 有价（``price_daily`` 非 null）= 玩家市场可得 = 有效候选。缺价弹不参与
      枚举、不上榜——其数据仍保留在 ``data/tables/ammo.json``（语义：数据有效
      但市场暂不可得，赛季更新人工改表）；
    - 口径无该等级弹药 → :class:`src.engine.engagement.ScenarioError`（与
      :func:`src.engine.engagement.pick_ammo` 同语义，调用方排除该枪）；
    - 价格表未配置（``None`` 或空表）→ 返回 ``[]``：价格维度未激活，调用方
      回退官方池单弹，榜单保持可用（成本列显示 ``—``）。
    """
    weapon = game_data.get_weapon(profile_key)
    level = int(ammo_level)
    candidates = [
        record
        for record in game_data.ammo_for_weapon(weapon)
        if record["penetration_level"] == level
    ]
    if not candidates:
        raise eg.ScenarioError(f"{profile_key} 无 {level} 级弹药")
    if price_table is None or price_table.is_empty:
        return []
    return sorted(
        (
            record
            for record in candidates
            if price_table.price_for(str(record["ammo_item_id"])) is not None
            and _ammo_in_season(record)
        ),
        key=lambda record: str(record["ammo_item_id"]),
    )


def rank_weapons_for_scenario(
    game_data: Any,
    scenario_id: str,
    solver: Optional[LoadoutSolver] = None,
    beam_width: int = 48,
    profile_keys: Optional[Sequence[str]] = None,
    price_table: Optional["AmmoPriceTable"] = None,
    weapon_price_table: Optional["WeaponPriceTable"] = None,
    part_price_table: Optional["PartPriceTable"] = None,
) -> tuple:
    """起枪状态口径榜单：每行 = 一个「起枪配置状态 × 一款有价弹」的 TTK，聚合距离带并分层。

    条目构成（同一把枪会产生多个状态行）：

    - **base 本体**：官方默认配装（裸枪）；
    - **本体+官方预装件**：官方变体出厂态（仅预装件影响 TTK 的才列）——
      变体只是本体预装了官方改件，不是独立的枪，裸枪价与本体一致；
    - **改装状态**：束搜索枚举的合法配装（仅影响 TTK 的插槽参与），每个
      TTK 互异状态一行——四带平均 TTK 相同的状态视为同一情况，不重复列。

    全部状态行一起参与排名与 T0–T3 分层。各行的「预装收益」以同枪同弹本体
    裸枪为参照。

    **弹维度展开**：价格表激活（传入非空 ``price_table``）时，该枪在情景弹药
    等级下的候选弹 = 该口径该等级全部弹药中**当日有价**（``price_daily`` 非
    null，有价 = 玩家市场可得）的每一款（:func:`pick_priced_ammos`）——每款弹
    独立束搜索、独立出状态行，行自带该弹的名称 / 单发价 / 击杀成本。同枪不同
    弹排名不同是预期行为；该等级全部弹缺价 → 该枪该情景无行（排除，与「口径
    无该等级弹药」同语义）。价格表未配置（``None`` 或空表）时价格维度不激活，
    回退官方池单弹（:func:`src.engine.engagement.pick_ammo`，同等级取
    ``ammo_item_id`` 最小者）。

    **每日轻量刷新语义**：某弹从有价变缺价（下架）→ 已算出的行保留，成本列经
    每日刷新变为 ``—``；从缺价变有价（重新上架）→ 该弹的行要等下次全量重算
    才出现（上次枚举时无价，未曾成行）。

    **口径弹药不可用的武器会被排除**（与官方榜一致：某些口径没有该等级弹药，
    例如 9x19mm 无 5 级弹）。官方对应输出为 ``eligibleWeaponCount`` / ``excludedWeaponCount``。

    Returns:
        ``(rankings, tier_thresholds, excluded)``。
    """
    solver = solver or LoadoutSolver(game_data, scenario_id)
    keys = list(profile_keys) if profile_keys else [w["profile_key"] for w in game_data.weapons]
    keys_set = set(keys)
    distances = tuple(float(d) for d in range(0, int(eg.DISTANCE_MAX) + 1))

    # 按 weapon_id 分组：base 与其变体
    groups: Dict[str, Dict[str, Any]] = {}
    for weapon in game_data.weapons:
        group = groups.setdefault(str(weapon["weapon_id"]), {"base": None, "variants": []})
        if weapon.get("is_variant"):
            group["variants"].append(weapon)
        else:
            group["base"] = weapon

    def _band_results(
        summary: Mapping[str, Mapping[str, float]], ammo_price: Optional[int]
    ) -> Dict[str, BandResult]:
        return {
            name: BandResult(
                band=name,
                mean_ms=stats["mean_ms"],
                worst_ms=stats["max_ms"],
                best_ms=stats["min_ms"],
                mean_expected_shots=stats["mean_expected_shots"],
                kill_cost=compute_kill_cost(stats["mean_expected_shots"], ammo_price),
            )
            for name, stats in summary.items()
        }

    def _ammo_price(ammo: Mapping[str, Any]) -> Optional[int]:
        ammo_item_id = str(ammo.get("ammo_item_id") or "")
        return price_table.price_for(ammo_item_id) if price_table is not None else None

    def _exclude(profile_key: str, weapon: Mapping[str, Any], exc: Exception) -> Dict[str, str]:
        return {
            "profile_key": profile_key,
            "name": str(weapon.get("display_name") or weapon.get("name") or profile_key),
            "reason": str(exc),
        }

    def _signature(summary: Mapping[str, Mapping[str, float]], ammo_item_id: str = "") -> tuple:
        """TTK 状态签名：**弹药维度 + 四带平均 TTK**。

        相同签名 = 同一 TTK 状态（不重复列）；不同弹的同名状态是不同行，
        故弹药 id 必须参与去重键。
        """
        return (str(ammo_item_id),) + tuple(
            round(summary[b]["mean_ms"], 6) for b in BAND_NAMES if b in summary
        )

    def _factory_ranking(
        weapon: Mapping[str, Any],
        *,
        entry_kind: str,
        curve: Sequence[eg.TtkResult],
        ammo: Mapping[str, Any],
        stock_bands: Mapping[str, Mapping[str, float]],
        loadout_effects: List[Dict[str, Any]],
        loadout: Optional[Mapping[str, Any]] = None,
        gun_price: Optional[int] = None,
    ) -> GunRanking:
        ammo_price = _ammo_price(ammo)
        curve0 = curve[0]
        by_distance: Dict[str, float] = {}
        for point in curve:
            d = point.distance_m
            if abs(d - round(d)) < 1e-9 and round(d) % 10 == 0:
                by_distance[str(int(d))] = round(point.ttk_milliseconds, 2)
        effective_loadout = _effective_loadout(loadout or {}, weapon)
        if entry_kind == "base" and not effective_loadout:
            part_ids: List[str] = []
        elif entry_kind == "variant":
            part_ids = [str(weapon.get("variant_item_id"))] if weapon.get("variant_item_id") else []
        else:
            part_ids = list(effective_loadout.values())
        parts_price = compute_parts_price(part_ids, part_price_table)

        return GunRanking(
            profile_key=str(weapon["profile_key"]),
            weapon_id=str(weapon["weapon_id"]),
            display_name=str(weapon.get("display_name") or weapon.get("name") or weapon["profile_key"]),
            base_name=str(weapon.get("name") or weapon["profile_key"]),
            category=str(weapon.get("category") or ""),
            is_variant=entry_kind == "variant",
            variant_item_name=weapon.get("variant_item_name") if entry_kind == "variant" else None,
            loadout=effective_loadout,
            tuning={},
            entry_kind=entry_kind,
            bands=_band_results(eg.band_summary(curve), ammo_price),
            overall_mean_ms=0.0,
            expected_shots_0m=curve0.expected_shots,
            rpm=curve0.rpm,
            ads_ms_reference=curve0.ads_seconds * 1000.0,
            muzzle_velocity_mps=curve0.muzzle_velocity_mps,
            effective_range_m=curve0.effective_range_m,
            ammo_item_id=str(ammo.get("ammo_item_id") or ""),
            ammo_name=str(ammo.get("name") or ""),
            ammo_caliber=str(ammo.get("caliber") or ""),
            ammo_price_daily=ammo_price,
            gun_price_daily=gun_price,
            parts_price_daily=parts_price,
            full_price_180rd=compute_full_price(gun_price, ammo_price, parts_price=parts_price),
            loadout_effects=loadout_effects,
            stock_bands=dict(stock_bands),
            ttk_by_distance_ms=by_distance,
        )

    rankings: List[GunRanking] = []
    excluded: List[Dict[str, str]] = []

    for _weapon_id, group in groups.items():
        base_weapon = group["base"]
        if base_weapon is None:
            continue
        base_key = str(base_weapon["profile_key"])
        if base_key not in keys_set:
            continue

        # 本体裸枪当日价：同枪全部状态行（本体/预装态/改装态）共用——
        # 变体 = 本体 + 预装改件，改装只换配件，裸枪价不随配置变化
        gun_price = (
            weapon_price_table.price_for(str(base_weapon["weapon_id"]))
            if weapon_price_table is not None
            else None
        )

        # ---- 情景弹药枚举：价格维度激活 → 全部有价弹逐款成行；未激活 → 官方池单弹 ----
        ammo_level = int(solver.scenario["ammo_level"])
        price_dimension_active = price_table is not None and not price_table.is_empty
        try:
            if price_dimension_active:
                ammos = pick_priced_ammos(game_data, base_key, ammo_level, price_table)
                if not ammos:
                    raise eg.ScenarioError(
                        f"{base_key} 的 {ammo_level} 级弹药在市场全部缺价（不上榜）"
                    )
            else:
                ammos = [solver.ammo_for(base_key)]
            base_state = solver.resolver.resolve(base_key, loadout={}, tuning=None)
        except eg.ScenarioError as exc:
            excluded.append(_exclude(base_key, base_weapon, exc))
            continue

        # 变体出厂态的状态解析与弹药无关（变体与本体共用口径弹药池，只解析一次）；
        # TTK 曲线按弹逐款重算
        variant_states: List[tuple] = []
        for variant_weapon in group["variants"]:
            variant_key = str(variant_weapon["profile_key"])
            if variant_key not in keys_set:
                continue
            variant_item_id = str(variant_weapon.get("variant_item_id") or "")
            if not part_affects_ttk(game_data.get_part(variant_item_id)):
                continue
            try:
                variant_states.append(
                    (
                        variant_weapon,
                        solver.resolver.resolve(variant_key, loadout={}, tuning=None),
                    )
                )
            except eg.ScenarioError as exc:
                excluded.append(_exclude(variant_key, variant_weapon, exc))
                continue

        # 状态去重键含弹药维度（见 _signature）：不同弹的同名状态是不同行
        seen_signatures: set = set()

        for ammo in ammos:
            ammo_item_id = str(ammo.get("ammo_item_id") or "")

            # 束搜索打分以「本款弹」为准：与官方池单弹一致时直接复用主求解器
            # （零行为差异）；否则构造单弹求解器（共享状态解析器，弹经打分缓存注入）
            if str(solver.ammo_for(base_key).get("ammo_item_id") or "") == ammo_item_id:
                beam_solver = solver
            else:
                beam_solver = LoadoutSolver(game_data, solver.scenario_id, resolver=solver.resolver)
                beam_solver._ammo_cache[base_key] = ammo  # 单弹求解器：束搜索打分固定用本款弹

            # ---- base 本体：官方默认（裸枪）× 本款弹 ----
            base_curve = eg.ttk_curve(
                base_state, ammo, solver.armor, solver.probabilities, distances
            )
            base_summary = eg.band_summary(base_curve)
            rankings.append(
                _factory_ranking(
                    base_weapon,
                    entry_kind="base",
                    curve=base_curve,
                    ammo=ammo,
                    stock_bands=base_summary,
                    loadout_effects=[],
                    gun_price=gun_price,
                )
            )
            seen_signatures.add(_signature(base_summary, ammo_item_id))

            # ---- 变体枪先入榜：出厂预装态（保留官方身份命名）× 本款弹 ----
            for variant_weapon, variant_state in variant_states:
                variant_curve = eg.ttk_curve(
                    variant_state, ammo, solver.armor, solver.probabilities, distances
                )
                variant_summary = eg.band_summary(variant_curve)
                rankings.append(
                    _factory_ranking(
                        variant_weapon,
                        entry_kind="variant",
                        curve=variant_curve,
                        ammo=ammo,
                        stock_bands=base_summary,
                        loadout_effects=summarize_loadout_effects(base_state, variant_state),
                        gun_price=gun_price,
                    )
                )
                seen_signatures.add(_signature(variant_summary, ammo_item_id))

            # ---- 起枪状态池：束搜索合法配装（仅影响 TTK 的插槽参与）× 本款弹 ----
            # 与 base/变体出厂态同 TTK 签名（同弹）的状态已由其行覆盖，跳过。
            try:
                beam = beam_solver.enumerate_loadouts(base_key, beam_width=beam_width)
            except eg.ScenarioError as exc:
                excluded.append(_exclude(base_key, base_weapon, exc))
                continue

            scored: List[tuple] = []
            for loadout in beam:
                try:
                    state_mounted = solver.resolver.resolve(base_key, loadout=loadout, tuning=None)
                except eg.ScenarioError:
                    continue
                state_curve = eg.ttk_curve(
                    state_mounted, ammo, solver.armor, solver.probabilities, distances
                )
                scored.append((loadout, state_mounted, state_curve, eg.band_summary(state_curve)))
            scored.sort(key=lambda item: tuple(item[3][b]["mean_ms"] for b in BAND_NAMES if b in item[3]))

            for loadout_choice, state_mounted_choice, state_curve, state_summary in scored:
                signature = _signature(state_summary, ammo_item_id)
                if signature in seen_signatures:
                    continue  # TTK 与已列状态（同弹）相同 → 不属于"会影响 TTK 的情况"
                seen_signatures.add(signature)
                rankings.append(
                    _factory_ranking(
                        base_weapon,
                        entry_kind="state",
                        curve=state_curve,
                        ammo=ammo,
                        stock_bands=base_summary,
                        loadout_effects=summarize_loadout_effects(
                            base_state, state_mounted_choice
                        ),
                        loadout=loadout_choice,
                        gun_price=gun_price,
                    )
                )

    for entry in rankings:
        if entry.bands:
            entry.overall_mean_ms = sum(b.mean_ms for b in entry.bands.values()) / len(entry.bands)

    thresholds: Dict[str, Dict[str, float]] = {}
    for band in BAND_NAMES:
        present = [r for r in rankings if band in r.bands]
        present.sort(key=lambda r: r.bands[band].mean_ms)
        for index, entry in enumerate(present, start=1):
            entry.bands[band].rank = index
        # 已按 mean_ms 升序排好，直接复用给 assign_tiers，避免对同一分布再排一次
        thresholds[band] = assign_tiers(
            rankings, band, sorted_values=[r.bands[band].mean_ms for r in present]
        )

    return rankings, thresholds, excluded
