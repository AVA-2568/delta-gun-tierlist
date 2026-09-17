import json
import os

def test_base_guns_file_exists_and_valid():
    path = "data/base_guns.json"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) >= 6
    for gun in data:
        assert "id" in gun
        assert "rpm" in gun and gun["rpm"] > 0
        assert "caliber" in gun
        assert "dropoffs" in gun and len(gun["dropoffs"]) > 0

def test_baseline_ammo_prices_exists_and_valid():
    path = "data/baseline_ammo_prices.json"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) >= 6
    for ammo in data:
        assert ammo["level"] in [4, 5]
        assert ammo["price_per_round"] > 0

def test_default_builds_exists_and_valid():
    path = "data/default_builds.json"
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) >= 6
    for build in data:
        assert "gun_id" in build
        assert "build_code" in build
        assert build["mod_cost"] > 0

def test_data_relational_integrity():
    with open("data/base_guns.json", "r", encoding="utf-8") as f:
        guns = json.load(f)
    with open("data/baseline_ammo_prices.json", "r", encoding="utf-8") as f:
        ammo = json.load(f)
    with open("data/default_builds.json", "r", encoding="utf-8") as f:
        builds = json.load(f)

    gun_ids = {g["id"] for g in guns}
    build_gun_ids = {b["gun_id"] for b in builds}
    # 确保每把枪都有默认改装方案
    for gid in gun_ids:
        assert gid in build_gun_ids, f"Weapon {gid} missing default build"

    ammo_keys = {(a["caliber"], a["level"]) for a in ammo}
    # 确保每把枪的口径都有 4 级和 5 级弹药价格
    for g in guns:
        cal = g["caliber"]
        assert (cal, 4) in ammo_keys, f"Caliber {cal} missing Level 4 ammo price"
        assert (cal, 5) in ammo_keys, f"Caliber {cal} missing Level 5 ammo price"
