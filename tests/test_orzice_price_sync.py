"""orzice 行情采集：解析 / 匹配 / 翻页 / 幂等 / 部分保存单测（离线，不联网）。

夹具为 6 个真实页面样本（2026-09-30 实地抓取，位于 tests/fixtures/orzice/）：
- orzice_zhanbei.html / _p2.html：战备页第 1、2 页（均为配件/装备条目）；
- orzice_ammo.html / _p2.html / _p6.html：弹药页第 1、2、6 页；
- orzice_ammo_p11.html：越界空页（站点 404 文案页，无条目行），测翻页终止。
"""

import json
import os
import shutil
import urllib.error
from pathlib import Path

import pytest

from src.collectors import orzice_price_sync as mod
from src.collectors.orzice_price_sync import (
    assert_public_https,
    build_ammo_name_map,
    crawl_pages,
    match_ammo_prices,
    match_weapon_prices,
    norm_name,
    parse_price,
    parse_rows,
    strip_condition_suffix,
    sync,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "orzice"
REPO_ROOT = Path(__file__).parent.parent
ZHANBEI = "/v/zhanbei"
AMMO = "/v/ammo"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _noop_sleep(seconds: float) -> None:
    pass


def _page_fetcher(pages: dict, calls: list, fail: dict = None):
    """构造注入用抓取函数：``{(path, page): html}``；``fail[(path, page)] = 异常工厂``。"""

    def fetch(path: str, page: int) -> str:
        calls.append((path, page))
        if fail and (path, page) in fail:
            raise fail[(path, page)]()
        return pages[(path, page)]

    return fetch


def _make_output_dir(tmp_path: Path) -> Path:
    """临时输出根：拷贝官方目录 data/game（含 weapons.json 与 ammo.json）。"""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "data" / "game", root / "data" / "game")
    return root


def _weapon_row(name: str, price: str, object_id: str) -> str:
    """仿真实页面行结构的最小 HTML（ui-tname + 当前价 + pic 官方 objectID）。"""
    return (
        '<tr><td><div class="ui-item"><div class="ui-tname">' + name + "</div></div></td>"
        '<td><div class="ui-cell-gold"><span class="icon-gold ui-num">' + price + "</span></div></td>"
        '<td @click="GoLinesV3(\'x\',{pic:\'https://playerhub.df.qq.com/playerhub/60004/object/'
        + object_id + ".png'})\"></td></tr>"
    )


# ---- 价格解析：两种形态与千分位 ----

def test_parse_price_forms_and_thousands():
    assert parse_price("68,035") == 68035
    assert parse_price("1,300,059") == 1300059
    assert parse_price("479") == 479
    assert parse_price("{{NumQfw(25630)}}") == 25630
    assert parse_price(" {{NumQfw( 479 )}} ") == 479
    assert parse_price("") is None
    assert parse_price("无价") is None
    assert parse_price("0") is not None  # parse_price 只管解析；0 的过滤在 parse_rows/match 层


def test_parse_rows_takes_first_price_cell_only():
    """当前价 = 行内第一个 icon-gold ui-num；3日/7日/30日列不误采。"""
    rows = parse_rows(_fixture("orzice_zhanbei.html"))
    assert len(rows) == 10
    first = rows[0]
    assert first["name"] == "QJB201新式獠牙短枪管"
    assert first["price"] == 68035  # 千分位 "68,035"，不是 30 日列的 791334
    assert first["object_id"] == "13020000529"
    assert "881774" not in [r["price"] for r in rows]


def test_parse_rows_zhanbei_names_prices_object_ids():
    rows = parse_rows(_fixture("orzice_zhanbei.html"))
    assert [r["name"] for r in rows][:5] == [
        "QJB201新式獠牙短枪管",
        "新式尖兵轻型握把",
        "AK重塔握把",
        "H70 精英头盔",  # 成色后缀已剥离
        "HA-2重型防弹衣",
    ]
    assert [r["price"] for r in rows] == [
        68035, 24936, 43575, 1300059, 1159295, 79036, 87450, 21052, 56470, 42413,
    ]
    assert [r["object_id"] for r in rows] == [
        "13020000529", "13030000180", "13030000167", "11010006002", "11050006002",
        "13390000002", "11080005001", "13110000087", "13020000564", "13420000002",
    ]


def test_parse_rows_ammo_generic_pics_without_object_id():
    """弹药页泛口径图条目无 objectID；带官方 objectID 的条目（45-70/箭矢）可提取。"""
    rows = parse_rows(_fixture("orzice_ammo_p2.html"))
    by_name = {r["name"]: r for r in rows}
    assert by_name["9x19mm AP6.3"]["object_id"] is None
    assert by_name["12.7x55mm PS12"]["object_id"] is None
    assert by_name["45-70 Govt FMJ"]["object_id"] == "37290400001"
    assert by_name["45-70 Govt FTX"]["object_id"] == "37290500001"
    assert by_name["45-70 Govt RN"]["object_id"] == "37290300001"
    assert by_name["12.7x55mm PS12"]["price"] == 1942


def test_condition_suffix_variants():
    assert strip_condition_suffix("H70 精英头盔 (几乎全新)") == "H70 精英头盔"
    assert strip_condition_suffix("HA-2重型防弹衣 (破损)") == "HA-2重型防弹衣"
    assert strip_condition_suffix("M870（全新）") == "M870"
    assert strip_condition_suffix("AKS-74U（几乎全新）") == "AKS-74U"
    assert strip_condition_suffix("M4A1") == "M4A1"
    assert strip_condition_suffix("DT-AVS防弹衣（几乎全新）（破损）") == "DT-AVS防弹衣"


# ---- 翻页：空页终止 / 404 / 403 重试一次 / 部分结果 ----

def test_crawl_stops_on_empty_page():
    calls = []
    fetch = _page_fetcher({(AMMO, 1): _fixture("orzice_ammo.html"), (AMMO, 2): _fixture("orzice_ammo_p11.html")}, calls)
    rows, complete = crawl_pages(AMMO, fetch, interval=0, sleep=_noop_sleep)
    assert complete is True
    assert len(rows) == 10
    assert calls == [(AMMO, 1), (AMMO, 2)]


def test_crawl_stops_on_http_404():
    calls = []
    fail = {(AMMO, 2): lambda: urllib.error.HTTPError("https://orzice.com/v/ammo?p=2", 404, "Not Found", None, None)}
    fetch = _page_fetcher({(AMMO, 1): _fixture("orzice_ammo.html")}, calls, fail)
    rows, complete = crawl_pages(AMMO, fetch, interval=0, sleep=_noop_sleep)
    assert complete is True  # 404 = 列表耗尽，正常终止
    assert len(rows) == 10
    assert calls == [(AMMO, 1), (AMMO, 2)]


def test_crawl_403_retries_once_then_returns_partial():
    calls = []
    fail = {(ZHANBEI, 1): lambda: urllib.error.HTTPError("https://orzice.com/v/zhanbei?p=1", 403, "Forbidden", None, None)}
    fetch = _page_fetcher({}, calls, fail)
    rows, complete = crawl_pages(ZHANBEI, fetch, interval=0, backoff_403_s=0, sleep=_noop_sleep)
    assert complete is False  # 重试一次仍 403 → 停止，返回已获部分
    assert rows == []
    assert calls == [(ZHANBEI, 1), (ZHANBEI, 1)]  # 恰好重试一次，不高频


def test_crawl_403_on_later_page_keeps_earlier_rows():
    calls = []
    fail = {(ZHANBEI, 3): lambda: urllib.error.HTTPError("https://orzice.com/v/zhanbei?p=3", 403, "Forbidden", None, None)}
    fetch = _page_fetcher(
        {(ZHANBEI, 1): _fixture("orzice_zhanbei.html"), (ZHANBEI, 2): _fixture("orzice_zhanbei_p2.html")},
        calls, fail,
    )
    rows, complete = crawl_pages(ZHANBEI, fetch, interval=0, backoff_403_s=0, sleep=_noop_sleep)
    assert complete is False
    assert len(rows) == 20  # 前两页数据保留
    assert calls == [(ZHANBEI, 1), (ZHANBEI, 2), (ZHANBEI, 3), (ZHANBEI, 3)]


def test_crawl_other_error_returns_partial():
    calls = []
    fail = {(AMMO, 2): lambda: RuntimeError("连接被重置")}
    fetch = _page_fetcher({(AMMO, 1): _fixture("orzice_ammo.html")}, calls, fail)
    rows, complete = crawl_pages(AMMO, fetch, interval=0, sleep=_noop_sleep)
    assert complete is False
    assert len(rows) == 10


def test_crawl_respects_max_pages_cap():
    pages = {("x", p): _fixture("orzice_ammo.html") for p in range(1, 5)}
    calls = []
    fetch = _page_fetcher(pages, calls)
    rows, complete = crawl_pages("x", fetch, interval=0, max_pages=3, sleep=_noop_sleep)
    assert complete is False  # 达到页数上限 → 视为不完整
    assert len(rows) == 30
    assert calls == [("x", 1), ("x", 2), ("x", 3)]


# ---- 弹药名称映射：唯一键构建与撞名剔除 ----

def test_build_ammo_name_map_drops_colliding_keys():
    catalog = {
        "a": {"caliber": ".45 ACP", "name": "FMJ"},
        "b": {"caliber": ".45-ACP", "name": "FMJ"},  # 连字符变体归一后与 a 撞名 → 整组弃用
        "c": {"caliber": "5.56x45mm", "name": "RRLP"},
    }
    name_map = build_ammo_name_map(catalog)
    assert ".45acpfmj" not in name_map
    assert name_map[norm_name("5.56x45mm RRLP")] == "c"


def test_norm_name_bridges_mm_and_hyphen_variants():
    """官方口径 ``12.7x55`` vs orzice 展示 ``12.7x55mm PS12``；``.45-ACP`` vs ``.45 ACP``。"""
    assert norm_name("12.7x55mm PS12") == norm_name("12.7x55 PS12")
    assert norm_name(".45-ACP FMJ") == norm_name(".45 ACP FMJ")
    assert norm_name("7.62x51mm\xa0Ultra\xa0Nosler") == "7.62x51ultranosler"


def test_build_ammo_name_map_real_catalog_collision_free():
    catalog = mod.load_ammo_catalog(str(REPO_ROOT / "data" / "game" / "ammo.json"))
    name_map = build_ammo_name_map(catalog)
    assert len(name_map) == len(catalog)  # 现行官方目录无撞名键（mm 剔除不产生碰撞）


# ---- 弹药匹配：objectID 优先 + 名称全等唯一，缺价不猜测 ----

def test_match_ammo_prices_on_fixtures():
    catalog = mod.load_ammo_catalog(str(REPO_ROOT / "data" / "game" / "ammo.json"))
    name_map = build_ammo_name_map(catalog)
    rows = []
    for name in ("orzice_ammo.html", "orzice_ammo_p2.html", "orzice_ammo_p6.html"):
        rows.extend(parse_rows(_fixture(name)))
    prices, notes = match_ammo_prices(rows, catalog, name_map)

    assert len(prices) == 30  # 30 个条目名：.300BLK_3 仅对齐常驻 V-Max（V-SUB 作为 S8 限定排除），_5 对齐 5 级弹
    # 名称全等匹配（含 mm 归一化桥接）
    assert prices["37160400001"] == 1942  # 12.7x55mm PS12
    assert all(p > 0 for p in prices.values())  # 有正价才入价
    # objectID 精确匹配（45-70 系 / 箭矢）
    assert "37290400001" in prices and "37290500001" in prices and "37290300001" in prices
    assert "37270300001" in prices  # 玻纤柳叶箭矢
    # .300BLK_3 合并行仅对齐常驻 3 级弹 V-Max，过往赛季限定弹 V-SUB（S8）被排除
    assert prices["37280300001"] == 497 and "37280300002" not in prices
    # .300BLK_5 → TAC-TX 组内唯一 → ``<口径>_N`` 等级键入价
    assert prices["37280500001"] == 4968


def test_match_ammo_prices_skips_zero_and_missing_price():
    catalog = {"1": {"caliber": "9x19mm", "name": "FMJ"}}
    name_map = build_ammo_name_map(catalog)
    rows = [
        {"name": "9x19mm FMJ", "price": None, "object_id": None},  # 缺价
        {"name": "9x19mm FMJ", "price": 0, "object_id": None},  # 0 价
    ]
    assert match_ammo_prices(rows, catalog, name_map) == ({}, {})


def test_match_weapon_prices_filters_by_catalog_and_positive_price():
    catalog = mod.load_weapon_catalog(str(REPO_ROOT / "data" / "game" / "weapons.json"))
    # 真实战备页夹具均为配件/装备 → 全部过滤掉
    rows = parse_rows(_fixture("orzice_zhanbei.html")) + parse_rows(_fixture("orzice_zhanbei_p2.html"))
    assert match_weapon_prices(rows, set(catalog)) == {}
    # 命中 weapon_id 的枪械条目保留；缺价/0 价/未知 id 不入
    rows = [
        {"name": "M4A1", "price": 69535, "object_id": "18010000001"},
        {"name": "AKM", "price": None, "object_id": "18010000006"},
        {"name": "未知枪", "price": 999, "object_id": "99999999999"},
        {"name": "M870", "price": 0, "object_id": "18020000001"},
    ]
    assert match_weapon_prices(rows, set(catalog)) == {"18010000001": 69535}


# ---- URL 与输出目录安全校验 ----

def test_assert_public_https_rejects_bad_urls():
    with pytest.raises(ValueError):
        assert_public_https("http://orzice.com/v/ammo?p=1")  # 非 https
    with pytest.raises(ValueError):
        assert_public_https("https://evil.com/v/ammo?p=1")  # host 不在允许名单
    with pytest.raises(ValueError):
        assert_public_https("https://orzice.com.evil.com/v/ammo?p=1")
    with pytest.raises(ValueError):
        assert_public_https("https://localhost/v/ammo?p=1")
    with pytest.raises(ValueError):
        assert_public_https("https://127.0.0.1/v/ammo?p=1")


def test_assert_public_https_rejects_private_dns_resolution():
    def fake_resolve(host, port):
        return [(2, 1, 6, "", ("10.0.0.8", port))]

    with pytest.raises(ValueError):
        assert_public_https("https://orzice.com/v/ammo?p=1", resolve=fake_resolve)


def test_assert_public_https_accepts_public_resolution():
    def fake_resolve(host, port):
        return [(2, 1, 6, "", ("93.184.216.34", port))]

    assert_public_https("https://orzice.com/v/ammo?p=1", resolve=fake_resolve)


def test_safe_output_root_rejects_traversal():
    with pytest.raises(ValueError):
        mod._safe_output_root("../outside")
    with pytest.raises(ValueError):
        mod._safe_output_root("a/../../b")
    assert os.path.isabs(mod._safe_output_root("."))


# ---- sync 编排：写表 / 幂等 / 403 部分保存 ----

def _make_sync_fetch(weapon_extra_html: str, ammo_fixtures: list):
    """战备页：夹具两页 + 合成枪械页；弹药页：夹具若干页 + 空页终止。"""
    zhanbei_pages = {
        1: _fixture("orzice_zhanbei.html"),
        2: _fixture("orzice_zhanbei_p2.html"),
        3: weapon_extra_html,  # 合成页：夹具页序之后的枪械条目
        4: _fixture("orzice_ammo_p11.html"),  # 空页终止
    }
    ammo_pages = {i + 1: _fixture(name) for i, name in enumerate(ammo_fixtures)}
    ammo_pages[len(ammo_fixtures) + 1] = _fixture("orzice_ammo_p11.html")

    def fetch(path: str, page: int) -> str:
        if path == ZHANBEI:
            return zhanbei_pages[page]
        return ammo_pages[page]

    return fetch


def test_sync_writes_both_tables(tmp_path):
    root = _make_output_dir(tmp_path)
    weapon_page = (
        "<table>" + _weapon_row("M4A1", "69,535", "18010000001")
        + _weapon_row("AKM", "{{NumQfw(71286)}}", "18010000006") + "</table>"
    )
    fetch = _make_sync_fetch("<html>" + weapon_page + "</html>", ["orzice_ammo.html"])

    result = sync(
        output_dir=str(root), fetch=fetch, sleep=_noop_sleep,
    )
    assert result["complete"] is True
    assert result["weapon"]["changed"] is True
    assert result["weapon"]["matched"] == 2
    assert result["weapon"]["catalog"] == 68  # manifest.weaponPacks 全量收录
    assert result["ammo"]["changed"] is True
    assert result["ammo"]["matched"] == 10  # 弹药夹具第 1 页 10 条，.300BLK_3 仅对齐常驻 V-Max（V-SUB 为 S8 排除）

    weapon_table = json.loads((root / "data" / "reference" / "weapon_prices.json").read_text(encoding="utf-8"))
    assert weapon_table["schema"] == "weapon-price-daily"
    assert weapon_table["currency"] == "哈夫币"
    assert weapon_table["window"]["days"] == 1
    assert weapon_table["window"]["from"] == weapon_table["updated_at"] == weapon_table["window"]["to"]
    assert "orzice" in weapon_table["source"] and "小涛查" in weapon_table["source"]
    ids = [row["weapon_id"] for row in weapon_table["weapons"]]
    assert ids == sorted(ids) and len(ids) == 68
    by_id = {row["weapon_id"]: row["price_daily"] for row in weapon_table["weapons"]}
    assert by_id["18010000001"] == 69535
    assert by_id["18010000006"] == 71286  # 模板形态
    entry = next(row for row in weapon_table["weapons"] if row["weapon_id"] == "18010000001")
    assert set(entry) == {"weapon_id", "name", "category", "caliber", "price_daily"}

    ammo_table = json.loads((root / "data" / "reference" / "ammo_prices.json").read_text(encoding="utf-8"))
    assert ammo_table["schema"] == "ammo-price-daily"
    assert "orzice" in ammo_table["source"] and "小涛查" in ammo_table["source"]
    ammo_ids = [row["ammo_item_id"] for row in ammo_table["ammo"]]
    assert ammo_ids == sorted(ammo_ids) and len(ammo_ids) == 113
    assert "37250400005" not in ammo_ids  # 合并条目（DART→箭型弹）不进骨架
    ammo_by_id = {row["ammo_item_id"]: row["price_daily"] for row in ammo_table["ammo"]}
    assert ammo_by_id["37100300001"] > 0  # 5.56x45mm M855（夹具第 1 页）
    assert ammo_by_id["37280300001"] == 497  # .300BLK_3 对齐入价
    assert set(ammo_table["ammo"][0]) == {
        "ammo_item_id", "caliber", "name", "penetration_level", "price_daily",
    }


def test_sync_is_idempotent_when_prices_unchanged(tmp_path):
    root = _make_output_dir(tmp_path)
    weapon_page = "<html><table>" + _weapon_row("M4A1", "69,535", "18010000001") + "</table></html>"
    fetch_factory = lambda: _make_sync_fetch(weapon_page, ["orzice_ammo.html"])

    first = sync(output_dir=str(root), fetch=fetch_factory(), sleep=_noop_sleep)
    assert first["weapon"]["changed"] is True and first["ammo"]["changed"] is True
    weapon_bytes = (root / "data" / "reference" / "weapon_prices.json").read_bytes()
    ammo_bytes = (root / "data" / "reference" / "ammo_prices.json").read_bytes()
    weapon_mtime = (root / "data" / "reference" / "weapon_prices.json").stat().st_mtime_ns

    second = sync(output_dir=str(root), fetch=fetch_factory(), sleep=_noop_sleep)
    assert second["complete"] is True
    assert second["weapon"]["changed"] is False  # 价格一致不重写（git 无 diff）
    assert second["ammo"]["changed"] is False
    assert (root / "data" / "reference" / "weapon_prices.json").read_bytes() == weapon_bytes
    assert (root / "data" / "reference" / "ammo_prices.json").read_bytes() == ammo_bytes
    assert (root / "data" / "reference" / "weapon_prices.json").stat().st_mtime_ns == weapon_mtime


def test_sync_rewrites_only_changed_table(tmp_path):
    root = _make_output_dir(tmp_path)

    def weapon_page(price: str) -> str:
        return "<html>" + _weapon_row("M4A1", price, "18010000001") + "</html>"

    sync(output_dir=str(root), fetch=_make_sync_fetch(weapon_page("69,535"), ["orzice_ammo.html"]), sleep=_noop_sleep)
    weapon_bytes = (root / "data" / "reference" / "weapon_prices.json").read_bytes()
    ammo_bytes = (root / "data" / "reference" / "ammo_prices.json").read_bytes()

    result = sync(
        output_dir=str(root),
        fetch=_make_sync_fetch(weapon_page("70,000"), ["orzice_ammo.html"]),
        sleep=_noop_sleep,
    )
    assert result["weapon"]["changed"] is True  # 价格变了 → 重写
    assert result["ammo"]["changed"] is False  # 弹药没变 → 不重写
    assert (root / "data" / "reference" / "weapon_prices.json").read_bytes() != weapon_bytes
    assert (root / "data" / "reference" / "ammo_prices.json").read_bytes() == ammo_bytes


def test_sync_403_writes_partial_result_and_reports_incomplete(tmp_path):
    root = _make_output_dir(tmp_path)
    calls = []
    weapon_page = "<html>" + _weapon_row("M4A1", "69,535", "18010000001") + "</html>"

    def fetch(path: str, page: int) -> str:
        calls.append((path, page))
        if path == AMMO:
            # 弹药页两次请求（含 403 重试）都失败
            raise urllib.error.HTTPError("https://orzice.com/v/ammo", 403, "Forbidden", None, None)
        if path == ZHANBEI and page == 1:
            return _fixture("orzice_zhanbei.html")
        if path == ZHANBEI and page == 2:
            return weapon_page
        return _fixture("orzice_ammo_p11.html")  # 空页终止

    result = sync(
        output_dir=str(root), fetch=fetch, backoff_403_s=0, sleep=_noop_sleep,
    )
    assert result["complete"] is False  # 抓取不完整
    assert result["weapon"]["matched"] == 1 and result["weapon"]["changed"] is True
    assert result["ammo"]["matched"] == 0 and result["ammo"]["changed"] is True  # 部分结果仍落盘
    assert calls.count((AMMO, 1)) == 2  # 403 恰好重试一次

    ammo_table = json.loads((root / "data" / "reference" / "ammo_prices.json").read_text(encoding="utf-8"))
    assert all(row["price_daily"] is None for row in ammo_table["ammo"])


def test_sync_missing_catalog_raises(tmp_path):
    root = tmp_path / "empty"
    (root / "data" / "game").mkdir(parents=True)
    (root / "data" / "game" / "weapons.json").write_text('{"weapons": []}', encoding="utf-8")
    (root / "data" / "game" / "ammo.json").write_text('{"ammo": []}', encoding="utf-8")
    calls = []
    fetch = _page_fetcher({}, calls)
    with pytest.raises(RuntimeError):
        sync(output_dir=str(root), fetch=fetch, sleep=_noop_sleep)


def test_sync_output_dir_rejects_traversal(tmp_path):
    # 相对路径含上级目录分量（normpath 后仍保留 ".."）→ 拒绝
    fetch = _page_fetcher({}, [])
    with pytest.raises(ValueError):
        sync(output_dir="../escape", fetch=fetch, sleep=_noop_sleep)


# ---- CLI：中断时退出码 0 ----

def test_main_exits_zero_on_partial(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["orzice_price_sync", "--output-dir", "."],
    )
    monkeypatch.setattr(
        mod, "sync",
        lambda output_dir: {
            "complete": False,
            "weapon": {"changed": True, "matched": 1, "catalog": 43,
                       "table_path": "data/reference/weapon_prices.json"},
            "ammo": {"changed": True, "matched": 0, "catalog": 114,
                     "table_path": "data/reference/ammo_prices.json"},
        },
    )
    mod.main()  # 不抛 SystemExit → 退出码 0
    out = capsys.readouterr().out
    assert "部分" in out and "orzice" in out


def test_match_part_prices_from_zhanbei_fixture():
    """战备页夹具中包含枪管、握把等配件，验证能按 objectID 及名称正确提取价格。"""
    rows = parse_rows(_fixture("orzice_zhanbei.html"))
    part_catalog = mod.load_part_catalog(str(REPO_ROOT / "data" / "game" / "parts.json"))
    assert len(part_catalog) > 0
    name_map = mod.build_part_name_map(part_catalog)

    prices = mod.match_part_prices(rows, part_catalog, name_map)
    # 验证 fixture 中的 QJB201新式獠牙短枪管 (13020000529) 和 MK4深空镀铬枪管 (13020000564)
    assert prices.get("13020000529") == 68035
    assert prices.get("13020000564") == 56470
    assert prices.get("13030000180") == 24936  # 新式尖兵轻型握把

