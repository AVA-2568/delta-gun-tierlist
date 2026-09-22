"""枪械价格表加载与查价测试。"""

import json

from src.engine.weapon_pricing import (
    DEFAULT_CURRENCY,
    WeaponPriceTable,
    load_weapon_prices,
)


def _write(tmp_path, payload):
    path = tmp_path / "weapon_prices.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _valid_payload():
    return {
        "schema": "weapon-price-daily",
        "currency": "哈夫币",
        "window": {"from": "2026-09-22", "to": "2026-09-22", "days": 1},
        "updated_at": "2026-09-22",
        "weapons": [
            {"weapon_id": "18010000001", "name": "M4A1", "category": "突击步枪",
             "caliber": "5.56x45mm", "price_daily": 87591},
            {"weapon_id": "18010000051", "name": "MDR", "category": "突击步枪",
             "caliber": "5.56x45mm", "price_daily": None},
        ],
    }


def test_loads_prices_and_meta(tmp_path):
    table = load_weapon_prices(_write(tmp_path, _valid_payload()))
    assert table.currency == "哈夫币"
    assert table.window["days"] == 1
    assert table.updated_at == "2026-09-22"
    assert table.price_for("18010000001") == 87591
    assert not table.is_empty


def test_null_price_is_treated_as_missing(tmp_path):
    table = load_weapon_prices(_write(tmp_path, _valid_payload()))
    assert table.price_for("18010000051") is None


def test_unknown_weapon_returns_none(tmp_path):
    table = load_weapon_prices(_write(tmp_path, _valid_payload()))
    assert table.price_for("does-not-exist") is None


def test_missing_file_yields_empty_table(tmp_path):
    table = load_weapon_prices(str(tmp_path / "nope.json"))
    assert table.is_empty
    assert table.price_for("18010000001") is None
    assert table.currency == DEFAULT_CURRENCY
    assert table.updated_at == ""
    assert table.window == {}


def test_invalid_json_yields_empty_table(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_weapon_prices(str(path)).is_empty


def test_gbk_encoded_file_yields_empty_table(tmp_path):
    """GBK 编码（Windows「ANSI 另存」）不得让管线崩溃——返回空表。"""
    path = tmp_path / "weapon_prices.json"
    payload = _valid_payload()
    path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("gbk"))
    table = load_weapon_prices(str(path))
    assert table.is_empty
    assert table.currency == DEFAULT_CURRENCY


def test_wrong_schema_yields_empty_table(tmp_path):
    payload = _valid_payload()
    payload["schema"] = "ammo-price-daily"  # 别种价格表误放
    assert load_weapon_prices(_write(tmp_path, payload)).is_empty


def test_invalid_prices_are_dropped(tmp_path):
    payload = _valid_payload()
    payload["weapons"] = [
        {"weapon_id": "a", "price_daily": 0},
        {"weapon_id": "b", "price_daily": -5},
        {"weapon_id": "c", "price_daily": "123"},
        {"weapon_id": "d", "price_daily": 100.5},
        {"weapon_id": "e", "price_daily": True},
        {"weapon_id": "f", "price_daily": 7},
    ]
    table = load_weapon_prices(_write(tmp_path, payload))
    for bad in ("a", "b", "c", "d", "e"):
        assert table.price_for(bad) is None, bad
    assert table.price_for("f") == 7


def test_frozen_table_is_immutable():
    table = WeaponPriceTable()
    assert table.currency == DEFAULT_CURRENCY
    assert table.is_empty
    try:
        table.currency = "x"  # type: ignore[misc]
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("WeaponPriceTable 应为不可变")
