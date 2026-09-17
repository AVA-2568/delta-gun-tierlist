"""Unit tests for data collectors, metadata loaders, and 3-tier fallback resilience."""

import json
import os
import pytest
from src.models import GunMeta, AmmoPrice, WeaponBuild, DataSourceStatus


def test_load_all_guns():
    """Verify loading and validating gun metadata from standard dataset."""
    from src.collectors.gun_loader import load_all_guns

    guns = load_all_guns()
    assert len(guns) >= 6
    assert all(isinstance(g, GunMeta) for g in guns)
    assert all(g.rpm > 0 for g in guns)
    assert any(g.id == "m4a1" for g in guns)


def test_load_all_guns_custom_valid_path(tmp_path):
    """Verify loading guns from a custom file path."""
    from src.collectors.gun_loader import load_all_guns

    custom_data = [
        {
            "id": "test_gun",
            "name": "测试枪",
            "category": "突击步枪",
            "caliber": "5.56x45mm",
            "rpm": 600,
            "bullet_velocity": 700.0,
            "base_price": 20000,
            "default_mag_size": 30,
            "ads_time_ms": 200,
            "recoil_control": 50.0,
            "stability": 50.0,
            "dropoffs": [
                {"max_distance": 50.0, "chest_damage": 30.0, "armor_damage": 25.0}
            ],
        }
    ]
    file_path = tmp_path / "custom_guns.json"
    file_path.write_text(json.dumps(custom_data), encoding="utf-8")

    guns = load_all_guns(data_path=str(file_path))
    assert len(guns) == 1
    assert guns[0].id == "test_gun"


def test_load_all_guns_file_not_found():
    """Verify error raised when gun metadata file does not exist."""
    from src.collectors.gun_loader import load_all_guns

    with pytest.raises(FileNotFoundError):
        load_all_guns(data_path="data/non_existent_guns.json")


def test_load_all_guns_invalid_schema(tmp_path):
    """Verify validation error when gun data violates GunMeta schema."""
    from src.collectors.gun_loader import load_all_guns
    from pydantic import ValidationError

    bad_data = [{"id": "bad_gun", "rpm": -10}]
    file_path = tmp_path / "bad_guns.json"
    file_path.write_text(json.dumps(bad_data), encoding="utf-8")

    with pytest.raises((ValidationError, ValueError)):
        load_all_guns(data_path=str(file_path))


def test_load_all_guns_non_list_json(tmp_path):
    """Verify error when JSON root is not a list."""
    from src.collectors.gun_loader import load_all_guns

    file_path = tmp_path / "dict_guns.json"
    file_path.write_text(json.dumps({"guns": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a JSON list"):
        load_all_guns(data_path=str(file_path))


def test_fetch_ammo_prices_fallback_chain(monkeypatch):
    """Simulate network failure and verify fallback to snapshot or baseline library."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    def mock_failed_get(*args, **kwargs):
        raise ConnectionError("Network blocked by WAF")

    monkeypatch.setattr("requests.get", mock_failed_get)
    prices, status = fetch_ammo_prices()
    assert len(prices) > 0
    assert status.source in ["snapshot", "baseline"]
    assert status.is_fallback is True
    assert status.fallback_tier in [1, 2]
    assert all(isinstance(p, AmmoPrice) for p in prices.values())


def test_fetch_ammo_prices_live_success(monkeypatch, tmp_path):
    """Simulate successful live price fetch from zxfps and verify snapshot update."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    sample_live_data = [
        {
            "caliber": "5.56x45mm",
            "level": 4,
            "name": "5.56x45mm M855A1",
            "penetration": 42,
            "price_per_round": 1250,
            "source": "zxfps_live",
            "updated_at": "2026-09-17T12:00:00Z",
        },
        {
            "caliber": "9x19mm",
            "level": 4,
            "name": "9x19mm AP 6.3",
            "penetration": 40,
            "price_per_round": 900,
            "source": "zxfps_live",
            "updated_at": "2026-09-17T12:00:00Z",
        },
    ]

    class MockResponse:
        status_code = 200
        text = json.dumps(sample_live_data)

        def json(self):
            return sample_live_data

    def mock_success_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("requests.get", mock_success_get)

    snapshot_file = tmp_path / "snapshot_prices.json"
    prices, status = fetch_ammo_prices(
        live=True,
        snapshot_path=str(snapshot_file),
        baseline_path="data/baseline_ammo_prices.json",
    )

    assert status.source == "zxfps_live"
    assert status.is_fallback is False
    assert status.fallback_tier == 0
    assert "5.56x45mm_4" in prices
    assert prices["5.56x45mm_4"].price_per_round == 1250
    # Verify snapshot file was created atomically
    assert snapshot_file.exists()
    saved_data = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert len(saved_data) == 2


def test_fetch_ammo_prices_live_dict_wrapper(monkeypatch, tmp_path):
    """Verify live fetch handles nested JSON dictionary wrapper (e.g. {'data': [...]})."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    dict_payload = {
        "status": "success",
        "data": [
            {
                "caliber": "9x19mm",
                "level": 4,
                "name": "9x19mm AP 6.3",
                "penetration": 40,
                "price_per_round": 920,
            }
        ],
    }

    class MockResponse:
        status_code = 200
        text = json.dumps(dict_payload)

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: MockResponse())
    snapshot_file = tmp_path / "snapshot_dict.json"
    prices, status = fetch_ammo_prices(live=True, snapshot_path=str(snapshot_file))

    assert status.source == "zxfps_live"
    assert "9x19mm_4" in prices
    assert prices["9x19mm_4"].price_per_round == 920


def test_fetch_ammo_prices_live_html_table(monkeypatch, tmp_path):
    """Verify live fetch parses HTML table when endpoint returns HTML."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    html_content = """
    <html>
      <body>
        <table class="ammo-list">
          <tr><th>名称</th><th>口径</th><th>等级</th><th>穿透</th><th>价格</th></tr>
          <tr><td>5.56x45mm M855A1</td><td>5.56x45mm</td><td>4</td><td>42</td><td>1300</td></tr>
          <tr><td>7.62x51mm M80</td><td>7.62x51mm</td><td>4</td><td>44</td><td>1600</td></tr>
        </table>
      </body>
    </html>
    """

    class MockHtmlResponse:
        status_code = 200
        text = html_content

    monkeypatch.setattr("requests.get", lambda *args, **kwargs: MockHtmlResponse())
    snapshot_file = tmp_path / "snapshot_html.json"
    prices, status = fetch_ammo_prices(live=True, snapshot_path=str(snapshot_file))

    assert status.source == "zxfps_live"
    assert "5.56x45mm_4" in prices
    assert prices["5.56x45mm_4"].price_per_round == 1300
    assert "7.62x51mm_4" in prices
    assert prices["7.62x51mm_4"].price_per_round == 1600


def test_fetch_ammo_prices_tier1_snapshot_fallback(monkeypatch, tmp_path):
    """Verify fallback to Tier 1 (snapshot cache) when live request fails (e.g. 403 WAF)."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    class Mock403Response:
        status_code = 403
        text = "403 Forbidden - WAF Challenge"

    def mock_403_get(*args, **kwargs):
        return Mock403Response()

    monkeypatch.setattr("requests.get", mock_403_get)

    snapshot_data = [
        {
            "caliber": "5.56x45mm",
            "level": 4,
            "name": "5.56x45mm M855A1",
            "penetration": 42,
            "price_per_round": 1180,
            "source": "snapshot",
            "updated_at": "2026-09-17T06:00:00Z",
        }
    ]
    snapshot_file = tmp_path / "snapshot_prices.json"
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    prices, status = fetch_ammo_prices(
        live=True,
        snapshot_path=str(snapshot_file),
        baseline_path="data/baseline_ammo_prices.json",
    )

    assert status.source == "snapshot"
    assert status.is_fallback is True
    assert status.fallback_tier == 1
    assert "5.56x45mm_4" in prices
    assert prices["5.56x45mm_4"].price_per_round == 1180


def test_fetch_ammo_prices_tier2_baseline_fallback(monkeypatch, tmp_path):
    """Verify fallback to Tier 2 (baseline library) when live fails and snapshot is absent."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    def mock_timeout_get(*args, **kwargs):
        raise TimeoutError("Connection timed out after 5000ms")

    monkeypatch.setattr("requests.get", mock_timeout_get)

    non_existent_snapshot = tmp_path / "non_existent_snapshot.json"
    prices, status = fetch_ammo_prices(
        live=True,
        snapshot_path=str(non_existent_snapshot),
        baseline_path="data/baseline_ammo_prices.json",
    )

    assert status.source == "baseline"
    assert status.is_fallback is True
    assert status.fallback_tier == 2
    assert len(prices) >= 14
    assert "5.56x45mm_4" in prices


def test_fetch_ammo_prices_corrupted_snapshot_falls_to_baseline(monkeypatch, tmp_path):
    """Verify corrupted snapshot JSON triggers graceful degradation to baseline."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    def mock_failed_get(*args, **kwargs):
        raise ConnectionError("Network error")

    monkeypatch.setattr("requests.get", mock_failed_get)

    corrupted_snapshot = tmp_path / "corrupted_snapshot.json"
    corrupted_snapshot.write_text("{invalid_json: true", encoding="utf-8")

    prices, status = fetch_ammo_prices(
        live=True,
        snapshot_path=str(corrupted_snapshot),
        baseline_path="data/baseline_ammo_prices.json",
    )

    assert status.source == "baseline"
    assert status.is_fallback is True
    assert status.fallback_tier == 2
    assert len(prices) > 0


def test_fetch_ammo_prices_live_false(tmp_path):
    """Verify live=False directly bypasses network requests and loads local snapshot or baseline."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    snapshot_data = [
        {
            "caliber": "7.62x51mm",
            "level": 4,
            "name": "7.62x51mm M80",
            "penetration": 44,
            "price_per_round": 1500,
            "source": "snapshot",
            "updated_at": "2026-09-17T08:00:00Z",
        }
    ]
    snapshot_file = tmp_path / "snapshot_prices.json"
    snapshot_file.write_text(json.dumps(snapshot_data), encoding="utf-8")

    prices, status = fetch_ammo_prices(
        live=False,
        snapshot_path=str(snapshot_file),
        baseline_path="data/baseline_ammo_prices.json",
    )

    assert status.source == "snapshot"
    assert status.is_fallback is True
    assert status.fallback_tier == 1
    assert "7.62x51mm_4" in prices


def test_fetch_ammo_prices_all_tiers_missing_raises_error(monkeypatch, tmp_path):
    """Verify FileNotFoundError or RuntimeError when all sources are unavailable."""
    from src.collectors.ammo_collector import fetch_ammo_prices

    def mock_failed_get(*args, **kwargs):
        raise ConnectionError("No connection")

    monkeypatch.setattr("requests.get", mock_failed_get)

    with pytest.raises((FileNotFoundError, RuntimeError)):
        fetch_ammo_prices(
            live=True,
            snapshot_path=str(tmp_path / "missing_snap.json"),
            baseline_path=str(tmp_path / "missing_base.json"),
        )


def test_fetch_weapon_builds():
    """Verify loading default weapon builds indexed by gun_id."""
    from src.collectors.build_collector import fetch_weapon_builds

    builds = fetch_weapon_builds()
    assert len(builds) >= 6
    assert "m4a1" in builds
    assert isinstance(builds["m4a1"], WeaponBuild)
    assert builds["m4a1"].mod_cost > 0
    assert builds["m4a1"].build_code != ""


def test_fetch_weapon_builds_file_not_found():
    """Verify FileNotFoundError when build file is not found."""
    from src.collectors.build_collector import fetch_weapon_builds

    with pytest.raises(FileNotFoundError):
        fetch_weapon_builds(data_path="data/missing_builds.json")


def test_fetch_weapon_builds_non_list_json(tmp_path):
    """Verify error when weapon build file is not a list."""
    from src.collectors.build_collector import fetch_weapon_builds

    bad_file = tmp_path / "bad_builds.json"
    bad_file.write_text(json.dumps({"build": "m4a1"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a JSON list"):
        fetch_weapon_builds(data_path=str(bad_file))


def test_fetch_weapon_builds_overprice_normalization(tmp_path):
    """Verify overprice normalizer caps excessive costs and replaces luxury parts."""
    from src.collectors.build_collector import (
        fetch_weapon_builds,
        normalize_weapon_build,
        DEFAULT_OVERPRICED_REPLACEMENTS,
    )

    # 1. Test replacement of overpriced luxury attachment
    raw_build = {
        "gun_id": "test_rifle",
        "build_name": "天价奢华改",
        "build_code": "TEST-LUXURY-001",
        "mod_cost": 150000,
        "ads_modifier_ms": -10,
        "recoil_bonus": 20.0,
        "attachments": ["天价碳纤维枪托", "战术消音器", "奢华直角握把"],
    }
    file_path = tmp_path / "luxury_builds.json"
    file_path.write_text(json.dumps([raw_build]), encoding="utf-8")

    builds = fetch_weapon_builds(data_path=str(file_path), max_mod_cost=80000)
    normalized = builds["test_rifle"]

    assert normalized.mod_cost <= 80000
    assert "天价碳纤维枪托" not in normalized.attachments
    assert "CTR战术枪托" in normalized.attachments
    assert "奢华直角握把" not in normalized.attachments
    assert "RK-0垂直前握把" in normalized.attachments


def test_collectors_init_exports():
    """Verify package level exports in src.collectors."""
    import src.collectors as collectors

    assert hasattr(collectors, "load_all_guns")
    assert hasattr(collectors, "fetch_ammo_prices")
    assert hasattr(collectors, "fetch_weapon_builds")


def test_collectors_integration_with_ranker():
    """End-to-end integration test connecting collectors directly with the ranker engine."""
    from src.collectors import load_all_guns, fetch_ammo_prices, fetch_weapon_builds
    from src.engine.ranker import rank_weapons

    guns = load_all_guns()
    builds = fetch_weapon_builds()
    ammo_prices, status = fetch_ammo_prices(live=False)

    ranked_results = rank_weapons(
        guns=guns,
        builds=builds,
        ammo_prices=ammo_prices,
        armor_level=4,
        ammo_level=4,
        distance_m=15,
    )

    assert len(ranked_results) == len(guns)
    assert ranked_results[0].composite_score >= ranked_results[-1].composite_score
    assert all(r.composite_score > 0 for r in ranked_results)

    # 4 armor, 5 ammo scenario contains T0 / T1 tier weapons
    ranked_45 = rank_weapons(
        guns=guns,
        builds=builds,
        ammo_prices=ammo_prices,
        armor_level=4,
        ammo_level=5,
        distance_m=15,
    )
    assert any(r.tier == "T0" for r in ranked_45)

