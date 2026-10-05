"""配件价格表加载与整枪起枪价格计算测试。"""

from __future__ import annotations

import json
from pathlib import Path

from src.engine.part_pricing import (
    DEFAULT_CURRENCY,
    EXPECTED_SCHEMA,
    PartPriceTable,
    load_part_prices,
)
from src.engine.tiering import (
    SPARE_AMMO_ROUNDS,
    compute_full_price,
    compute_parts_price,
    extract_loadout_part_ids,
)


def test_load_part_prices_missing_file_returns_empty_table(tmp_path: Path) -> None:
    table = load_part_prices(str(tmp_path / "nonexistent.json"))
    assert isinstance(table, PartPriceTable)
    assert table.is_empty
    assert table.currency == DEFAULT_CURRENCY
    assert table.price_for("13020000563") is None


def test_load_part_prices_valid_table(tmp_path: Path) -> None:
    data = {
        "schema": EXPECTED_SCHEMA,
        "currency": "哈夫币",
        "window": {"from": "2026-10-05", "to": "2026-10-05", "days": 1},
        "updated_at": "2026-10-05",
        "parts": [
            {"part_id": "13020000563", "name": "MK4击剑手枪管", "price_daily": 56000},
            {"part_id": "13130000172", "name": "冲锋枪回声消音器", "price_daily": 32000},
            {"part_id": "13020000999", "name": "缺价枪管", "price_daily": None},
        ],
    }
    path = tmp_path / "parts.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    table = load_part_prices(str(path))
    assert not table.is_empty
    assert table.currency == "哈夫币"
    assert table.price_for("13020000563") == 56000
    assert table.price_for("13130000172") == 32000
    assert table.price_for("13020000999") is None
    assert table.price_for("unknown") is None


def test_extract_loadout_part_ids() -> None:
    # 1. 白板裸枪
    base_row = {"entry_kind": "base", "loadout": {}, "is_variant": False}
    assert extract_loadout_part_ids(base_row) == []

    # 2. 变体出厂态
    variant_row = {
        "entry_kind": "variant",
        "is_variant": True,
        "variant_item_id": "13020000563",
        "loadout": {},
    }
    assert extract_loadout_part_ids(variant_row) == ["13020000563"]

    # 3. 改装态（MK4 击剑手枪管 + 回声消音器）
    mod_row = {
        "entry_kind": "state",
        "is_variant": False,
        "loadout": {"2": "13020000563", "6": "13130000172"},
    }
    assert set(extract_loadout_part_ids(mod_row)) == {"13020000563", "13130000172"}


def test_compute_parts_price_and_full_price() -> None:
    table = PartPriceTable(
        prices={
            "13020000563": 56000,  # MK4击剑手枪管
            "13130000172": 32000,  # 冲锋枪回声消音器
        }
    )

    # 白板：无配件，配件价为 0，起枪价 = 裸枪 + 180 发备弹
    gun_price = 187343
    ammo_price = 4536
    assert compute_parts_price([], table) == 0
    base_full = compute_full_price(gun_price, ammo_price, rounds=180, parts_price=0)
    assert base_full == 187343 + 180 * 4536  # 1,003,823

    # 改装（MK4 击剑手枪管 + 回声消音器）：配件价 = 56000 + 32000 = 88000
    part_ids = ["13020000563", "13130000172"]
    parts_price = compute_parts_price(part_ids, table)
    assert parts_price == 88000
    mod_full = compute_full_price(gun_price, ammo_price, rounds=180, parts_price=parts_price)
    assert mod_full == 187343 + 180 * 4536 + 88000  # 1,091,823

    # 缺配件价：任一配件缺价，配件总价为 None，起枪总价也为 None
    part_ids_missing = ["13020000563", "99999999999"]
    parts_price_missing = compute_parts_price(part_ids_missing, table)
    assert parts_price_missing is None
    assert compute_full_price(gun_price, ammo_price, rounds=180, parts_price=parts_price_missing) is None

    # 空表：有配件但价格表为空时，返回 None（缺价不猜测）
    empty_table = PartPriceTable(prices={})
    assert compute_parts_price(["13020000563"], empty_table) is None
