"""泛型价格表加载（ammo/weapon 共用实现的直接测试）。"""

import json

from src.engine.price_table import DEFAULT_CURRENCY, PriceTable, load_price_table


def _write(tmp_path, payload, name="prices.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


PAYLOAD = {
    "schema": "demo-price-daily",
    "currency": "哈夫币",
    "window": {"from": "2026-09-22", "to": "2026-09-22", "days": 1},
    "updated_at": "2026-09-22",
    "demo": [
        {"demo_id": "a", "price_daily": 100},
        {"demo_id": "b", "price_daily": None},
    ],
}


def test_loads_with_custom_section_and_id_field(tmp_path):
    table = load_price_table(
        _write(tmp_path, PAYLOAD),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert isinstance(table, PriceTable)
    assert table.price_for("a") == 100
    assert table.price_for("b") is None
    assert table.updated_at == "2026-09-22"
    assert table.window["days"] == 1
    assert not table.is_empty


def test_table_cls_is_honoured(tmp_path):
    class DemoTable(PriceTable):
        pass

    table = load_price_table(
        _write(tmp_path, PAYLOAD),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
        table_cls=DemoTable,
    )
    assert isinstance(table, DemoTable)
    assert table.price_for("a") == 100


def test_missing_file_yields_empty_table(tmp_path):
    table = load_price_table(
        str(tmp_path / "nope.json"),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert table.is_empty
    assert table.currency == DEFAULT_CURRENCY
    assert table.updated_at == ""
    assert table.window == {}


def test_wrong_schema_yields_empty_table(tmp_path):
    payload = dict(PAYLOAD, schema="something-else")
    table = load_price_table(
        _write(tmp_path, payload),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert table.is_empty


def test_gbk_encoded_file_yields_empty_table(tmp_path):
    """与 ammo/weapon 同款：GBK 文件（Windows 记事本另存 ANSI）不抛异常。"""
    path = tmp_path / "gbk.json"
    path.write_bytes(json.dumps(PAYLOAD, ensure_ascii=False).encode("gbk"))
    table = load_price_table(
        str(path),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    assert table.is_empty
    assert table.currency == DEFAULT_CURRENCY


def test_invalid_prices_are_dropped(tmp_path):
    payload = dict(PAYLOAD, demo=[
        {"demo_id": "a", "price_daily": 0},
        {"demo_id": "b", "price_daily": -5},
        {"demo_id": "c", "price_daily": "123"},
        {"demo_id": "d", "price_daily": 100.5},
        {"demo_id": "e", "price_daily": True},
        {"demo_id": "f", "price_daily": 7},
    ])
    table = load_price_table(
        _write(tmp_path, payload),
        schema="demo-price-daily", section="demo", id_field="demo_id", label="示例表",
    )
    for bad in ("a", "b", "c", "d", "e"):
        assert table.price_for(bad) is None, bad
    assert table.price_for("f") == 7
