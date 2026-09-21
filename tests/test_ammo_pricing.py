"""弹药均价表加载与查价测试。"""

import json

from src.engine.ammo_pricing import DEFAULT_CURRENCY, AmmoPriceTable, load_ammo_prices


def _write(tmp_path, payload):
    path = tmp_path / "ammo_prices.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _valid_payload():
    return {
        "schema": "ammo-price-avg-30d",
        "currency": "哈夫币",
        "window": {"from": "2026-08-23", "to": "2026-09-21", "days": 30},
        "updated_at": "2026-09-21",
        "ammo": [
            {"ammo_item_id": "37100500001", "caliber": "5.56x45mm", "name": "M995",
             "penetration_level": 5, "price_avg_30d": 4579},
            {"ammo_item_id": "37100400001", "caliber": "5.56x45mm", "name": "M855A1",
             "penetration_level": 4, "price_avg_30d": None},
        ],
    }


def test_loads_prices_and_meta(tmp_path):
    table = load_ammo_prices(_write(tmp_path, _valid_payload()))
    assert table.currency == "哈夫币"
    assert table.window["days"] == 30
    assert table.updated_at == "2026-09-21"
    assert table.price_for("37100500001") == 4579
    assert not table.is_empty


def test_null_price_is_treated_as_missing(tmp_path):
    table = load_ammo_prices(_write(tmp_path, _valid_payload()))
    assert table.price_for("37100400001") is None


def test_unknown_item_returns_none(tmp_path):
    table = load_ammo_prices(_write(tmp_path, _valid_payload()))
    assert table.price_for("does-not-exist") is None


def test_missing_file_yields_empty_table(tmp_path):
    table = load_ammo_prices(str(tmp_path / "nope.json"))
    assert table.is_empty
    assert table.price_for("37100500001") is None
    assert table.currency == DEFAULT_CURRENCY
    assert table.updated_at == ""
    assert table.window == {}


def test_invalid_json_yields_empty_table(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_ammo_prices(str(path)).is_empty


def test_gbk_encoded_file_yields_empty_table(tmp_path):
    """价格表是含中文的手工维护文件，本机 Windows 下「记事本另存为 ANSI/GBK」是现实路径。

    ``UnicodeDecodeError`` 是 ``ValueError`` 子类；若 ``load_ammo_prices`` 未覆盖它，
    会直接抛异常让管线与 CI 崩溃。这里断言：GBK 编码的文件 → 返回空表且**不抛异常**。
    """
    path = tmp_path / "ammo_prices.json"
    # valid_payload 含中文（currency=哈夫币），以 GBK 写出模拟 ANSI 另存场景
    payload = _valid_payload()
    path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("gbk"))
    table = load_ammo_prices(str(path))
    assert table.is_empty
    assert table.currency == DEFAULT_CURRENCY
    assert table.price_for("37100500001") is None


def test_wrong_schema_yields_empty_table(tmp_path):
    payload = _valid_payload()
    payload["schema"] = "something-else"
    assert load_ammo_prices(_write(tmp_path, payload)).is_empty


def test_invalid_prices_are_dropped(tmp_path):
    payload = _valid_payload()
    payload["ammo"] = [
        {"ammo_item_id": "a", "price_avg_30d": 0},
        {"ammo_item_id": "b", "price_avg_30d": -5},
        {"ammo_item_id": "c", "price_avg_30d": "123"},
        {"ammo_item_id": "d", "price_avg_30d": 100.5},
        {"ammo_item_id": "e", "price_avg_30d": True},
        {"ammo_item_id": "f", "price_avg_30d": 7},
    ]
    table = load_ammo_prices(_write(tmp_path, payload))
    for bad in ("a", "b", "c", "d", "e"):
        assert table.price_for(bad) is None, bad
    assert table.price_for("f") == 7


def test_frozen_table_is_immutable():
    table = AmmoPriceTable()
    assert table.currency == DEFAULT_CURRENCY
    assert table.is_empty
    try:
        table.currency = "x"  # type: ignore[misc]
    except Exception as exc:
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("AmmoPriceTable 应为不可变")
