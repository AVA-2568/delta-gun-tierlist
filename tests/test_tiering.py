"""分层与距离带聚合测试（Task #6）。

口径：起枪状态榜——每行 = 一个起枪配置状态（本体裸枪 / 变体出厂预装态 /
束搜索枚举的改装状态），全部一起排名分层。
"""

import os

import pytest

from src.engine import engagement as eg
from src.engine.engagement import BAND_NAMES
from src.engine.game_data import load_game_data
from src.engine.ranking import rank_weapons_for_scenario
from src.engine.tiering import (
    TIER_QUANTILES,
    BandResult,
    GunRanking,
    _quantile,
    assign_tiers,
    extract_loadout_part_ids,
)
from src.engine.tierlist_export import to_export

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def gd():
    return load_game_data(os.path.join(ROOT, "data", "game"))


def _entry(name: str, ms: float) -> GunRanking:
    return GunRanking(
        profile_key=f"{name}:base",
        weapon_id=name,
        display_name=name,
        base_name=name,
        category="突击步枪",
        loadout={},
        tuning={},
        bands={"贴脸": BandResult(band="贴脸", mean_ms=ms, worst_ms=ms, best_ms=ms)},
    )


def test_quantile_matches_linear_interpolation():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _quantile(values, 0.0) == 1.0
    assert _quantile(values, 1.0) == 5.0
    assert _quantile(values, 0.5) == 3.0
    assert _quantile(values, 0.25) == pytest.approx(2.0)
    assert _quantile(values, 0.15) == pytest.approx(1.6)


def test_quantile_handles_single_value():
    assert _quantile([7.5], 0.9) == 7.5
    assert _quantile([], 0.5) == 0.0


def test_assign_tiers_uses_quantiles_and_covers_all():
    entries = [_entry(f"g{i}", float(i * 10)) for i in range(1, 11)]  # 10..100
    thresholds = assign_tiers(entries, "贴脸")
    assert set(thresholds) == {"T0", "T1", "T2"}
    # 单调：T0 阈值 < T1 阈值 < T2 阈值
    assert thresholds["T0"] < thresholds["T1"] < thresholds["T2"]
    # 每把枪都必须拿到层级，且最慢的落在 T3
    tiers = [e.bands["贴脸"].tier for e in entries]
    assert all(tiers)
    assert tiers[-1] == "T3"
    assert "T0" in tiers


def test_tier_quantiles_are_declared():
    assert TIER_QUANTILES == (0.15, 0.40, 0.70)


def test_band_definitions_match_engine():
    assert list(BAND_NAMES) == ["贴脸", "近距", "中距", "远距"]
    assert eg.DISTANCE_BANDS["远距"] == (50.0, 80.0)


def test_unsupported_caliber_is_excluded(gd):
    """12Ga 无 5 级弹 → M1014 在 5-5 情景应被排除（与官方 excluded 口径一致）。"""
    rankings, _thresholds, excluded = rank_weapons_for_scenario(
        gd,
        "armor-5-ammo-5-default",
        beam_width=8,
        profile_keys=["18030000001:base"],  # M1014
    )
    assert rankings == []
    assert len(excluded) == 1
    assert excluded[0]["profile_key"] == "18030000001:base"
    assert "5" in excluded[0]["reason"]


def test_ranking_produces_bands_and_thresholds(gd):
    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd,
        "armor-5-ammo-5-default",
        beam_width=8,
        profile_keys=["18050000003:base", "18030000001:base"],  # VSS 可用 / M1014 被排除
    )
    assert rankings
    assert len(excluded) == 1
    for entry in rankings:
        assert entry.weapon_id == "18050000003"
    base_rows = [e for e in rankings if e.entry_kind == "base"]
    assert len(base_rows) == 1
    entry = base_rows[0]
    for band in BAND_NAMES:
        assert band in entry.bands
        assert entry.bands[band].mean_ms > 0
        assert entry.bands[band].worst_ms >= entry.bands[band].mean_ms - 1e-9
    assert set(thresholds) == set(BAND_NAMES)
    assert entry.bands["贴脸"].tier in {"T0", "T1", "T2", "T3"}


def test_states_deduplicated_and_all_ranked(gd):
    """同一把枪的多状态行：TTK 互异（签名去重），且全部有排名与层级。"""
    rankings, thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=16, profile_keys=["18020000012:base"]  # MK4
    )
    assert len(rankings) >= 2  # 至少裸枪 + 一个改装状态
    kinds = {e.entry_kind for e in rankings}
    assert "base" in kinds
    signatures = [
        tuple(round(e.bands[b].mean_ms, 6) for b in BAND_NAMES) for e in rankings
    ]
    assert len(signatures) == len(set(signatures))  # 四带签名互异
    for entry in rankings:
        for band in BAND_NAMES:
            assert entry.bands[band].tier  # 同枪全部配置共享该枪层级
            if entry.bands[band].is_best:
                assert entry.bands[band].rank > 0
            else:
                assert entry.bands[band].rank == 0  # 非最优配置不占榜单行
    # 每带恰有一行代表该枪（is_best）
    for band in BAND_NAMES:
        assert sum(1 for e in rankings if e.bands[band].is_best) == 1


def test_ttk_by_distance_samples_cover_official_range(gd):
    """每状态携带 0–80m 每 10m 采样 TTK（距离维度明细）。"""
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=16, profile_keys=["18020000012:base"]
    )
    for entry in rankings:
        assert set(entry.ttk_by_distance_ms) == {str(d) for d in range(0, 81, 10)}
        values = list(entry.ttk_by_distance_ms.values())
        assert all(v > 0 for v in values)


def test_to_export_payload_shape(gd):
    rankings, thresholds, excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=8, profile_keys=["18050000003:base"]
    )
    payload = to_export(rankings, thresholds, "armor-5-ammo-5-default", excluded)
    assert payload["scenario_id"] == "armor-5-ammo-5-default"
    assert payload["ranking_key"] == "band_mean_ttk_ms"
    assert payload["robustness_key"] == "band_worst_ttk_ms"
    # eligible 计全部参赛状态行（含未发布的 T2/T3）；落盘只含 T0/T1
    assert payload["published_entry_count"] == len(payload["weapons"])
    assert payload["eligible_weapon_count"] >= payload["published_entry_count"]
    assert payload["excluded_weapon_count"] == 0
    assert payload["weapon_pool_count"] == payload["eligible_weapon_count"]
    assert payload["ranked_entry_count"] == len(rankings)
    assert all(
        any(b["tier"] in ("T0", "T1") for b in w["bands"].values())
        for w in payload["weapons"]
    )
    assert "贴脸" in payload["tier_thresholds_ms"]
    weapon = payload["weapons"][0]
    for key in ("profile_key", "name", "loadout", "overall_mean_ms", "bands",
                "expected_shots_0m", "rpm", "ads_ms_reference", "muzzle_velocity_mps",
                "stock_bands", "loadout_effects", "entry_kind", "ttk_by_distance_ms"):
        assert key in weapon


def test_effective_loadout_drops_defaults():
    """配装只列玩家需要改装的件；与默认件相同的选择不列出。"""
    from src.engine.tiering import _effective_loadout

    weapon = {"default_items": {"2": "stock_barrel", "6": "stock_muzzle"}}
    assert _effective_loadout({"2": "stock_barrel", "6": "silencer"}, weapon) == {"6": "silencer"}
    assert _effective_loadout({"2": "stock_barrel"}, weapon) == {}
    assert _effective_loadout({"2": "long_barrel"}, weapon) == {"2": "long_barrel"}


def test_variant_entries_do_not_form_standalone_rows(gd):
    """上游「官方变体」（本体 + 单件配件）不是独立起枪状态，不单独成行。

    AKM 性能枪管组合 = AKM + 该枪管；MK4 击剑手枪管 = MK4 + 该手枪管。
    其效果由改装状态行承载，另列一行只会重复计入同一配置。
    """
    rankings, thresholds, _excluded = rank_weapons_for_scenario(
        gd,
        "armor-5-ammo-5-default",
        profile_keys=["18010000006:base"],
    )
    assert not any(r.entry_kind == "variant" for r in rankings)
    states = [r for r in rankings if "13020000355" in r.loadout.values()]
    assert states, "AKM 装性能枪管组合的改装状态应被枚举"
    assert states[0].bands["贴脸"].tier
    assert thresholds["贴脸"]


def test_real_qjb201_states_have_no_internal_parts(gd):
    """真实数据校验：QJB201 的改装状态行不应装配原厂内部件。"""
    rankings, _thresholds, _excluded = rank_weapons_for_scenario(
        gd, "armor-5-ammo-5-default", beam_width=16, profile_keys=["18040000004:base"]
    )
    weapon = gd.get_weapon("18040000004:base")
    defaults = {str(v) for v in (weapon.get("default_items") or {}).values()}
    for entry in rankings:
        for item_id in entry.loadout.values():
            assert item_id not in defaults, f"配装里出现了默认件 {item_id}"



def test_extract_loadout_part_ids_covers_base_state():
    """配件提取口径：base→[]；state→loadout 件。

    榜单只有 base / state 两种 entry_kind：上游「官方变体」不单独成行。
    """

    def entry(kind, **overrides):
        kwargs = dict(
            profile_key="w1:base",
            weapon_id="w1",
            display_name="w1",
            base_name="w1",
            category="突击步枪",
            loadout={},
            tuning={},
            entry_kind=kind,
        )
        kwargs.update(overrides)
        return GunRanking(**kwargs)

    assert extract_loadout_part_ids(entry("base")) == []
    assert extract_loadout_part_ids(
        entry("state", loadout={"2": "p1", "6": "p2"})
    ) == ["p1", "p2"]

    # Mapping 路径（榜单 JSON 行）同口径
    assert extract_loadout_part_ids({"entry_kind": "base", "loadout": {}}) == []
    assert extract_loadout_part_ids(
        {"entry_kind": "state", "loadout": {"2": "p1"}}
    ) == ["p1"]
