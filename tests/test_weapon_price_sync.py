"""枪械价格同步：解析与幂等逻辑单测（离线，不联网）。"""

import json
import os

import pytest

from src.collectors.weapon_price_sync import (
    PRICE_SCHEMA,
    build_table,
    load_catalog_ids,
    parse_prices,
    sync,
)

# 仿真实行情页结构：o_ 市场全览块（本体裸枪价，primary_class=weapon）、
# t_ 制作利润干扰块、变体改件（attachment 分类，不得混入）、非枪械分类
PAGE = """
<html><body><script>
var data = {
 "t_18010000001":{"objectID":"18010000001","itemName":"M4A1突击步枪","zzsj":"8:00:00",
   "pic":"https://img/x.png","price":"70000","price_hour":"500","type":"2"},
 "o_18010000001":{"id":"1395","objectID":"18010000001","itemName":"M4A1突击步枪",
   "grade":"0","primary_class":"weapon","secondary_class":"rifle",
   "pic":"https://img/x.png","preview_picture":"https://img/y.png",
   "length":"5","width":"2","weight":"3.88","updatetime":"1755261432",
   "bg_color":"#0E151A","price":"87591","price2":"87,591",
   "rank3":{"pw":2,"paixuzhi":1410,"bfb":"+14.1"}},
 "o_18010000006":{"id":"1396","objectID":"18010000006","itemName":"AKM突击步枪",
   "grade":"0","primary_class":"weapon","secondary_class":"rifle",
   "price":79513,"price2":"79,513"},
 "o_13020000173":{"id":"1400","objectID":"13020000173","itemName":"AR特勤一体消音组合",
   "grade":"5","primary_class":"attachment","secondary_class":"barrel","price":"70937"},
 "o_11050004003":{"id":"500","objectID":"11050004003","itemName":"DT-AVS防弹衣",
   "grade":"4","primary_class":"armor","price":"72147"}
};
</script></body></html>
"""

CATALOG = {
    "weapons": [
        {"weapon_id": "18010000001", "name": "M4A1", "category": "突击步枪",
         "caliber": "5.56x45mm", "is_variant": False, "variant_item_id": None},
        {"weapon_id": "18010000006", "name": "AKM", "category": "突击步枪",
         "caliber": "7.62x39mm", "is_variant": False, "variant_item_id": None},
        {"weapon_id": "18010000006V", "name": "AKM-消音组合", "category": "突击步枪",
         "caliber": "7.62x39mm", "is_variant": True, "variant_item_id": "13020000173"},
    ]
}


def _write_catalog(root):
    path = os.path.join(root, "data", "game", "weapons.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(CATALOG, fh, ensure_ascii=False)
    return path


def test_parse_prices_only_market_overview_weapons():
    """只取 o_ 块（市场全览）且 primary_class=weapon 的对象；price 即本体裸枪价。"""
    prices = parse_prices(PAGE)
    assert prices["18010000001"] == 87591       # 市场全览真实当日价
    assert prices["18010000006"] == 79513       # 无引号数字形态，不换算
    # t_ 块（制作利润口径）不得混入
    assert prices["18010000001"] != 70000
    # 变体改件按 attachment 分类出售 → 不入枪价表
    assert "13020000173" not in prices
    # 非枪械分类（护甲）不入
    assert "11050004003" not in prices


def test_parse_prices_yields_positive_only():
    page = '"o_18010000009":{"primary_class":"weapon","price":"0"}'
    assert parse_prices(page) == {}


def test_load_catalog_ids_skips_variants(tmp_path):
    catalog = load_catalog_ids(_write_catalog(str(tmp_path)))
    assert set(catalog) == {"18010000001", "18010000006"}  # 变体条目不入骨架
    assert catalog["18010000001"]["name"] == "M4A1"
    assert catalog["18010000001"]["caliber"] == "5.56x45mm"


def test_build_table_covers_catalog_and_marks_missing(tmp_path):
    prices = {"18010000001": 87591}
    catalog = load_catalog_ids(_write_catalog(str(tmp_path)))
    table = build_table(
        {wid: {"name": meta["name"], "category": meta["category"], "caliber": meta["caliber"]}
         for wid, meta in catalog.items()},
        prices,
        "2026-09-22",
    )
    assert table["schema"] == PRICE_SCHEMA
    assert table["window"] == {"from": "2026-09-22", "to": "2026-09-22", "days": 1}
    rows = {r["weapon_id"]: r["price_daily"] for r in table["weapons"]}
    assert rows == {"18010000001": 87591, "18010000006": None}
    # 条目按 weapon_id 排序（确定性输出）
    ids = [r["weapon_id"] for r in table["weapons"]]
    assert ids == sorted(ids)


def test_sync_writes_and_is_idempotent(tmp_path):
    root = str(tmp_path)
    _write_catalog(root)
    result = sync(output_dir=root, fetch=lambda timeout: PAGE, zxfps_fetch=lambda a, ids: {})
    assert result["changed"] is True
    assert result["matched"] == 2

    table_path = os.path.join(root, "data", "reference", "weapon_prices.json")
    first = open(table_path, encoding="utf-8").read()

    # 再次同步同一页面：价格一致 → 不重写（幂等）
    result2 = sync(output_dir=root, fetch=lambda timeout: PAGE, zxfps_fetch=lambda a, ids: {})
    assert result2["changed"] is False
    assert open(table_path, encoding="utf-8").read() == first

    # 价格变化 → 重写
    changed_page = PAGE.replace('"price":"87591"', '"price":"90000"')
    result3 = sync(output_dir=root, fetch=lambda timeout: changed_page, zxfps_fetch=lambda a, ids: {})
    assert result3["changed"] is True
    updated = json.load(open(table_path, encoding="utf-8"))
    rows = {r["weapon_id"]: r["price_daily"] for r in updated["weapons"]}
    assert rows["18010000001"] == 90000


def test_fallback_fills_missing_weapons(tmp_path):
    """onebiji 缺价的本体（MDR 等）由 zxfps 回填，且标注补全来源。"""
    root = str(tmp_path)
    _write_catalog(root)
    page = PAGE.replace('"price":79513', '"price":0')  # AKM 主源缺价
    result = sync(
        output_dir=root, fetch=lambda timeout: page,
        zxfps_fetch=lambda a, ids: {"18010000006": 79513},
    )
    assert result["fallback"] == 1
    table = json.load(open(os.path.join(root, "data", "reference", "weapon_prices.json"), encoding="utf-8"))
    rows = {r["weapon_id"]: r["price_daily"] for r in table["weapons"]}
    assert rows["18010000006"] == 79513
    assert "zxfps" in table["source"]


def test_fallback_failure_is_graceful(tmp_path):
    """回填源崩溃不得影响主源数据（缺价保持 null）。"""
    root = str(tmp_path)
    _write_catalog(root)
    page = PAGE.replace('"price":79513', '"price":0')
    def boom(a, ids):
        raise RuntimeError("网络炸了")
    result = sync(output_dir=root, fetch=lambda timeout: page, zxfps_fetch=boom)
    assert result["fallback"] == 0
    assert result["changed"] is True
    table = json.load(open(os.path.join(root, "data", "reference", "weapon_prices.json"), encoding="utf-8"))
    rows = {r["weapon_id"]: r["price_daily"] for r in table["weapons"]}
    assert rows["18010000006"] is None
    assert rows["18010000001"] == 87591


def test_no_fallback_flag(tmp_path):
    """use_fallback=False：缺价条目不回填。"""
    root = str(tmp_path)
    _write_catalog(root)
    page = PAGE.replace('"price":79513', '"price":0')
    result = sync(
        output_dir=root, fetch=lambda timeout: page,
        use_fallback=False, zxfps_fetch=lambda a, ids: {"18010000006": 79513},
    )
    assert result["fallback"] == 0
    table = json.load(open(os.path.join(root, "data", "reference", "weapon_prices.json"), encoding="utf-8"))
    rows = {r["weapon_id"]: r["price_daily"] for r in table["weapons"]}
    assert rows["18010000006"] is None


def test_sync_rejects_empty_catalog(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "data", "game"), exist_ok=True)
    with open(os.path.join(root, "data", "game", "weapons.json"), "w", encoding="utf-8") as fh:
        json.dump({"weapons": []}, fh)
    with pytest.raises(RuntimeError):
        sync(output_dir=root, fetch=lambda timeout: PAGE)
