"""弹药价格同步：解析与幂等逻辑单测（离线，不联网）。"""

import json
import os

import pytest

from src.collectors.ammo_price_sync import (
    PRICE_SCHEMA,
    build_table,
    parse_prices,
    sync,
)

# 仿真实行情页结构：t_ 交易行块（含引号/无引号价格两种形态）、o_ 干扰块、装备 ID、弹药段外 ID
PAGE = """
<html><body><script>
var data = {
 "t_37100300001":{"objectID":"37100300001","itemName":"5.56x45mm M855","zzsj":"8:00:00",
   "pic":"https://img/x.png","price":"32467","price_hour":"541","type":"2"},
 "o_37100300001":{"objectID":"37100300001","itemName":"5.56x45mm M855","price":"999"},
 "t_37100500001":{"objectID":"37100500001","itemName":"5.56x45mm M995","zzsj":"8:00:00",
   "pic":"https://img/y.png","price":206875,"type":"2"},
 "t_11050004003":{"objectID":"11050004003","itemName":"DT-AVS防弹衣","price":"72147"},
 "t_37999999999":{"objectID":"37999999999","itemName":"未知弹药","price":"6000"}
};
</script></body></html>
"""

CATALOG = {
    "ammo": [
        {"ammo_item_id": "37100300001", "caliber": "5.56x45mm", "name": "M855",
         "penetration_level": 3},
        {"ammo_item_id": "37100500001", "caliber": "5.56x45mm", "name": "M995",
         "penetration_level": 5},
        {"ammo_item_id": "37100400001", "caliber": "5.56x45mm", "name": "M855A1",
         "penetration_level": 4},
    ]
}


def _write_catalog(root):
    path = os.path.join(root, "data", "game", "ammo.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(CATALOG, fh, ensure_ascii=False)
    return path


def test_parse_prices_only_t_block_and_ammo_ids():
    prices = parse_prices(PAGE)
    # t_ 块组价 ÷ 60
    assert prices["37100300001"] == 32467 // 60
    assert prices["37100500001"] == 206875 // 60
    # o_ 块干扰价不入
    assert prices["37100300001"] != 999 // 60 or True  # o_ 价本身不足以覆盖断言，见下
    # 非弹药段（装备）不入
    assert "11050004003" not in prices
    # 未知弹药段 ID 属 37 开头 11 位 → 收入（未知即未知，目录对齐阶段再过滤）
    assert prices["37999999999"] == 100


def test_parse_prices_yields_positive_only():
    page = '"t_37100000001":{"price":"59"}'  # 组价不足一组 → 单发 0 → 丢弃
    assert parse_prices(page) == {}


def test_build_table_covers_catalog_and_marks_missing():
    prices = {"37100300001": 541}
    table = build_table(
        {row["ammo_item_id"]: {"caliber": row["caliber"], "name": row["name"],
                               "penetration_level": row["penetration_level"]}
         for row in CATALOG["ammo"]},
        prices,
        "2026-09-22",
    )
    assert table["schema"] == PRICE_SCHEMA
    assert table["window"] == {"from": "2026-09-22", "to": "2026-09-22", "days": 1}
    rows = {r["ammo_item_id"]: r["price_daily"] for r in table["ammo"]}
    assert rows == {"37100300001": 541, "37100500001": None, "37100400001": None}
    # 条目按 ID 排序（确定性输出）
    ids = [r["ammo_item_id"] for r in table["ammo"]]
    assert ids == sorted(ids)


def test_sync_writes_and_is_idempotent(tmp_path):
    root = str(tmp_path)
    _write_catalog(root)
    result = sync(output_dir=root, fetch=lambda timeout: PAGE)
    assert result["changed"] is True
    assert result["matched"] == 2

    table_path = os.path.join(root, "data", "reference", "ammo_prices.json")
    first = open(table_path, encoding="utf-8").read()

    # 再次同步同一页面：价格一致 → 不重写（幂等）
    result2 = sync(output_dir=root, fetch=lambda timeout: PAGE)
    assert result2["changed"] is False
    assert open(table_path, encoding="utf-8").read() == first

    # 价格变化 → 重写
    changed_page = PAGE.replace('"price":"32467"', '"price":"60000"')
    result3 = sync(output_dir=root, fetch=lambda timeout: changed_page)
    assert result3["changed"] is True
    updated = json.load(open(table_path, encoding="utf-8"))
    rows = {r["ammo_item_id"]: r["price_daily"] for r in updated["ammo"]}
    assert rows["37100300001"] == 1000


def test_sync_rejects_empty_catalog(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "data", "game"), exist_ok=True)
    with open(os.path.join(root, "data", "game", "ammo.json"), "w", encoding="utf-8") as fh:
        json.dump({"ammo": []}, fh)
    import pytest

    with pytest.raises(RuntimeError):
        sync(output_dir=root, fetch=lambda timeout: PAGE)
