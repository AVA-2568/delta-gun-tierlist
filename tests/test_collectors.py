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
    assert not hasattr(builds["m4a1"], "build_code")
    assert not hasattr(builds["m4a1"], "code_status")
    assert builds["m4a1"].stability_bonus >= 0.0
    assert len(builds["m4a1"].tuning_instructions) > 0


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


def test_fetch_weapon_builds_without_cap_and_share_code(tmp_path):
    """Verify builds preserve true mod_cost exceeding 80k and have no share code."""
    from src.collectors.build_collector import (
        fetch_weapon_builds,
        normalize_weapon_build,
    )

    raw_build = {
        "gun_id": "test_rifle",
        "build_name": "顶级实战改",
        "mod_cost": 150000,
        "ads_modifier_ms": -10,
        "recoil_bonus": 20.0,
        "stability_bonus": 15.0,
        "velocity_bonus_pct": 0.05,
        "mag_size_bonus": 15,
        "attachments": ["枪托: CTR战术枪托", "枪口: 战术消音器"],
        "tuning_instructions": ["枪托: 配重右拉满(+50g，垂直/水平后坐-6%)"],
    }
    file_path = tmp_path / "custom_builds.json"
    file_path.write_text(json.dumps([raw_build]), encoding="utf-8")

    builds = fetch_weapon_builds(data_path=str(file_path))
    b = builds["test_rifle"]

    assert b.mod_cost == 150000  # No 80k artificial truncation!
    assert not hasattr(b, "build_code")
    assert not hasattr(b, "code_status")
    assert b.recoil_bonus == 20.0
    assert b.stability_bonus == 15.0
    assert len(b.tuning_instructions) == 1

    # Also verify normalize_weapon_build preserves full build
    norm = normalize_weapon_build(b)
    assert norm.mod_cost == 150000
    assert not hasattr(norm, "build_code")


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


def test_official_sync_build_dataset_and_sync(monkeypatch, tmp_path):
    """Verify official_sync module builds weapon dataset and writes to disk correctly."""
    from src.collectors import official_sync

    mock_weapons = {
        "objects": {
            "w_m4": {
                "categoryId": "assaultRifle",
                "ammoTypeId": "ammo_556",
                "combatSummaryByMode": {
                    "sol": {
                        "fireRateRpm": 750,
                        "baseFleshDamage": 32.0,
                        "baseArmorDamage": 30.0,
                        "muzzleVelocityMps": 650.0,
                        "damageFalloffSegments": [
                            {"toM": 30.0, "rate": 1.0},
                            {"toM": 60.0, "rate": 0.85},
                        ],
                    }
                },
            },
            "w_p90": {
                "categoryId": "submachineGun",
                "ammoTypeId": "ammo_57",
                "combatSummaryByMode": {
                    "sol": {
                        "fireRateRpm": 900,
                        "baseFleshDamage": 26.0,
                        "baseArmorDamage": 28.0,
                        "muzzleVelocityMps": 500.0,
                    }
                },
            },
            "w_pkm": {
                "categoryId": "lightMachineGun",
                "ammoTypeId": "ammo_54r",
                "combatSummaryByMode": {
                    "sol": {
                        "fireRateRpm": 650,
                        "baseFleshDamage": 38.0,
                        "baseArmorDamage": 42.0,
                        "muzzleVelocityMps": 600.0,
                    }
                },
            },
            "w_svd": {
                "categoryId": "marksmanRifle",
                "ammoTypeId": "ammo_54r",
                "combatSummaryByMode": {
                    "sol": {
                        "fireRateRpm": 300,
                        "baseFleshDamage": 55.0,
                        "baseArmorDamage": 58.0,
                        "muzzleVelocityMps": 700.0,
                    }
                },
            },
            "w_pistol": {
                "categoryId": "sidearm",
            },
            "w_no_sol": {
                "categoryId": "assaultRifle",
                "ammoTypeId": "ammo_556",
                "combatSummaryByMode": {},
            },
            "w_no_locale": {
                "categoryId": "assaultRifle",
                "ammoTypeId": "ammo_556",
                "combatSummaryByMode": {"sol": {}},
            },
        }
    }

    mock_ammo = {
        "ammo": {
            "a1": {"ammoTypeId": "ammo_556", "caliber": "5.56*45mm"},
            "a2": {"ammoTypeId": "ammo_57", "caliber": "5.7*28mm"},
            "a3": {"ammoTypeId": "ammo_54r", "caliber": "7.62*54R"},
        }
    }

    mock_locale = {
        "items": {
            "w_m4": "M4A1",
            "w_p90": "P90",
            "w_pkm": "PKM",
            "w_svd": "SVD",
            "w_pistol": "G17",
            "w_no_sol": "BrokenGun",
        }
    }

    monkeypatch.setattr(
        official_sync,
        "fetch_official_raw_data",
        lambda: (mock_weapons, mock_ammo, mock_locale),
    )

    guns = official_sync.build_official_guns_dataset()
    assert len(guns) == 4
    # M4A1
    m4 = next(g for g in guns if g["id"] == "m4a1")
    assert m4["category"] == "突击步枪"
    assert m4["caliber"] == "5.56x45mm"
    assert len(m4["dropoffs"]) == 2

    # P90
    p90 = next(g for g in guns if g["id"] == "p90")
    assert p90["category"] == "冲锋枪"
    assert p90["default_mag_size"] == 50
    assert len(p90["dropoffs"]) == 3  # Fallback dropoffs

    # PKM
    pkm = next(g for g in guns if g["id"] == "pkm")
    assert pkm["category"] == "轻机枪"
    assert pkm["caliber"] == "7.62x54mmR"
    assert pkm["default_mag_size"] == 75

    # SVD
    svd = next(g for g in guns if g["id"] == "svd")
    assert svd["category"] == "精确射手步枪"
    assert svd["default_mag_size"] == 10

    # Test sync_to_file
    out_file = tmp_path / "synced_guns.json"
    count = official_sync.sync_to_file(output_path=str(out_file))
    assert count == 4
    assert out_file.exists()


def test_fetch_official_raw_data_network_mock(monkeypatch):
    """Verify fetch_official_raw_data parses json from urllib requests."""
    from src.collectors import official_sync
    import io

    class MockHttpResp:
        def __init__(self, data):
            self._data = json.dumps(data).encode("utf-8")

        def read(self):
            return self._data

    def mock_urlopen(req, timeout=10):
        url = req.full_url
        if "weapons" in url:
            return MockHttpResp({"objects": {}})
        elif "ammo" in url:
            return MockHttpResp({"ammo": {}})
        else:
            return MockHttpResp({"items": {}})

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
    w, a, l = official_sync.fetch_official_raw_data()
    assert "objects" in w
    assert "ammo" in a
    assert "items" in l


