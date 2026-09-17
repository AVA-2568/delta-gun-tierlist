"""Official data synchronization module with DFTTK v3 and Delta Force official assets."""

import json
import logging
import urllib.request
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

DFTTK_MANIFEST_URL = "https://dfttk.com/data/v3/manifest.json"
DFTTK_WEAPONS_URL = "https://dfttk.com/data/v3/catalog/weapons.json"
DFTTK_AMMO_URL = "https://dfttk.com/data/v3/catalog/ammo.json"
DFTTK_LOCALE_ITEMS_URL = "https://dfttk.com/data/v3/locales/zh-CN/items.json"

VALID_PRIMARY_CATEGORIES: Dict[str, str] = {
    "assaultRifle": "突击步枪",
    "submachineGun": "冲锋枪",
    "marksmanRifle": "精确射手步枪",
    "lightMachineGun": "轻机枪",
}

# Real in-game base market acquisition price estimates (Hafu coins)
BASE_PRICES_BY_CATEGORY: Dict[str, int] = {
    "突击步枪": 42000,
    "冲锋枪": 32000,
    "精确射手步枪": 58000,
    "轻机枪": 62000,
}

CUSTOM_WEAPON_BASE_PRICES: Dict[str, int] = {
    "car15": 18000,
    "mp5": 24000,
    "smg45": 28000,
    "p90": 32000,
    "m14": 36000,
    "m4a1": 38000,
    "akm": 40000,
    "ak12": 42000,
    "vector": 42000,
    "qbz951": 46000,
    "g3": 48000,
    "aug": 52000,
    "vss": 54000,
    "qjb201": 56000,
    "pkm": 58000,
    "m249": 62000,
    "ash12": 62000,
    "asval": 65000,
    "scarh": 66000,
    "k416": 68000,
    "svd": 75000,
    "svch": 78000,
    "m7": 78000,
    "sr25": 82000,
    "m250": 85000,
}


def fetch_official_raw_data() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Download weapons catalog, ammo catalog, and Chinese locale dictionary from DFTTK v3."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    req_w = urllib.request.Request(DFTTK_WEAPONS_URL, headers=headers)
    weapons_data = json.loads(urllib.request.urlopen(req_w, timeout=10).read().decode("utf-8"))

    req_a = urllib.request.Request(DFTTK_AMMO_URL, headers=headers)
    ammo_data = json.loads(urllib.request.urlopen(req_a, timeout=10).read().decode("utf-8"))

    req_l = urllib.request.Request(DFTTK_LOCALE_ITEMS_URL, headers=headers)
    locale_data = json.loads(urllib.request.urlopen(req_l, timeout=10).read().decode("utf-8"))

    return weapons_data, ammo_data, locale_data


def build_official_guns_dataset() -> List[Dict[str, Any]]:
    """Compile official weapon physical parameters for all primary playable weapons."""
    weapons_data, ammo_data, locale_data = fetch_official_raw_data()

    objs = weapons_data["objects"]
    ammos = ammo_data["ammo"]
    items_locale = locale_data.get("items", {})

    # Map ammoTypeId to standardized caliber string
    ammo_type_to_cal: Dict[str, str] = {}
    for aid, a in ammos.items():
        atid = a.get("ammoTypeId")
        cal = a.get("caliber")
        if atid and cal and atid not in ammo_type_to_cal:
            clean_cal = cal.replace("*", "x")
            if clean_cal == "7.62x54R":
                clean_cal = "7.62x54mmR"
            ammo_type_to_cal[atid] = clean_cal

    guns_list: List[Dict[str, Any]] = []

    for wid, w in objs.items():
        cat_id = w.get("categoryId")
        if cat_id not in VALID_PRIMARY_CATEGORIES:
            continue

        name = items_locale.get(wid)
        if not name:
            continue

        sol = w.get("combatSummaryByMode", {}).get("sol", {})
        if not sol:
            continue

        atid = w.get("ammoTypeId")
        cal = ammo_type_to_cal.get(atid, "5.56x45mm")

        raw_rpm = sol.get("fireRateRpm", 600.0)
        rpm = int(round(float(raw_rpm)))
        base_flesh = float(sol.get("baseFleshDamage", 30.0))
        base_armor = float(sol.get("baseArmorDamage", 30.0))
        vel = float(sol.get("muzzleVelocityMps", 550.0))
        falloffs = sol.get("damageFalloffSegments", [])

        dropoffs = []
        if falloffs:
            for seg in falloffs:
                to_m = float(seg.get("toM", 100.0))
                rate = float(seg.get("rate", 1.0))
                dropoffs.append({
                    "max_distance": to_m,
                    "chest_damage": round(base_flesh * rate, 1),
                    "armor_damage": round(base_armor * rate, 1),
                })
        else:
            dropoffs = [
                {"max_distance": 25.0, "chest_damage": base_flesh, "armor_damage": base_armor},
                {"max_distance": 50.0, "chest_damage": round(base_flesh * 0.85, 1), "armor_damage": round(base_armor * 0.85, 1)},
                {"max_distance": 100.0, "chest_damage": round(base_flesh * 0.70, 1), "armor_damage": round(base_armor * 0.70, 1)},
            ]

        category = VALID_PRIMARY_CATEGORIES[cat_id]
        gun_id = name.lower().replace("-", "").replace(" ", "").replace("_", "")
        base_price = CUSTOM_WEAPON_BASE_PRICES.get(gun_id, BASE_PRICES_BY_CATEGORY.get(category, 45000))

        # Default weapon handling stats
        if category == "冲锋枪":
            ads_time = 160
            recoil = 78.0
            stability = 74.0
            mag_size = 30 if "p90" not in gun_id else 50
        elif category == "突击步枪":
            ads_time = 220
            recoil = 70.0
            stability = 68.0
            mag_size = 30
        elif category == "轻机枪":
            ads_time = 320
            recoil = 62.0
            stability = 65.0
            mag_size = 75 if "pkm" in gun_id or "m249" in gun_id else 50
        else:  # 精确射手步枪
            ads_time = 280
            recoil = 58.0
            stability = 78.0
            mag_size = 20 if "m14" in gun_id or "sr25" in gun_id else 10

        guns_list.append({
            "id": gun_id,
            "name": name,
            "category": category,
            "caliber": cal,
            "rpm": rpm,
            "bullet_velocity": vel,
            "base_price": base_price,
            "default_mag_size": mag_size,
            "ads_time_ms": ads_time,
            "recoil_control": recoil,
            "stability": stability,
            "dropoffs": dropoffs,
        })

    # Sort guns by category order and name
    cat_order = {"突击步枪": 1, "冲锋枪": 2, "轻机枪": 3, "精确射手步枪": 4}
    guns_list.sort(key=lambda g: (cat_order.get(g["category"], 9), g["name"]))
    return guns_list


def sync_to_file(output_path: str = "data/base_guns.json") -> int:
    """Synchronize official dataset directly into the local data file."""
    guns = build_official_guns_dataset()
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(guns, f, ensure_ascii=False, indent=2)
    logger.info("Synchronized %d official weapons to %s", len(guns), output_path)
    return len(guns)


if __name__ == "__main__":
    count = sync_to_file()
    print(f"Successfully synchronized {count} official primary weapons to data/base_guns.json!")
