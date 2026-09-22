"""zxfps 三角洲工具站行情采集测试（离线，不联网）。"""

import json

from src.collectors import zxfps_price_sync as zxfps


def test_sign_matches_reference_vectors():
    """签名公式与浏览器端 token.js（Node 实测钩子输出）逐位一致。"""
    cases = [
        ("a=gun&top=1-2&p=1&grade=-1", 1790073798, "e1ea43456aa20b82eb86163cc9490f83"),
        ("a=&top=", 1790073798, "66c7472d2c4613c64e636fc170c68aef"),
        ("id=12345", 1790073798, "1fdb720a0de6aaa556d6eef839357280"),
        ("", 1790073798, "ac9201aa6d44f8ad86cf74e67ad2ab5c"),
    ]
    for params, ts, expect in cases:
        assert zxfps.sign(params, ts) == expect, params


def test_object_id_of_extracts_from_pic():
    item = {"pic": "https://playerhub.df.qq.com/playerhub/60004/object/18010000051.png"}
    assert zxfps.object_id_of(item) == "18010000051"
    assert zxfps.object_id_of({"pic": ""}) is None
    assert zxfps.object_id_of({}) is None
    assert zxfps.object_id_of({"pic": "https://x/y.png"}) is None


class _FakeSession:
    """按脚本回放的假会话：校验 URL 签名、按页吐数据。"""

    def __init__(self, pages, timestamp=1790073798):
        self.pages = pages
        self.timestamp = timestamp
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if "/sjz/v/" in url:
            return f"<html>var TimeUnix = {self.timestamp} ;</html>"
        # 校验签名（拒绝错误签名，模拟服务端）
        assert f"token={zxfps.sign(url.split('?')[1].split('&token=')[0], self.timestamp)}" in url
        page = int(url.split("&p=")[1].split("&")[0])
        rows = self.pages.get(page, [])
        return json.dumps({"code": 0, "count": sum(len(v) for v in self.pages.values()), "data": rows})


def _item(oid, name, price):
    return {"name": name, "price": price, "pic": f"https://playerhub.df.qq.com/playerhub/60004/object/{oid}.png"}


def test_collect_missing_prices_stops_when_all_found():
    fillers = [_item(f"180100002{i:02d}", f"枪{i}", 1000 + i) for i in range(1, 10)]
    session = _FakeSession({
        1: fillers + [_item("18010000009", "X枪", 100)],   # 每页 10 条（真实分页口径）
        2: [_item("18010000051", "MDR突击步枪", 166523)],
    })
    result = zxfps.collect_missing_prices(
        "gun", ["18010000051", "18010000009"],
        session_factory=lambda a: session,
    )
    assert result == {"18010000009": 100, "18010000051": 166523}
    # 目标全部命中 → 早退，不发第 3 页请求
    list_calls = [u for u in session.urls if "item_list" in u]
    assert len(list_calls) == 2


def test_collect_stops_at_last_page_and_skips_bad_rows():
    session = _FakeSession({
        1: [_item("18010000051", "MDR突击步枪", 166523), {"name": "坏条目", "price": 100}, {"name": "零价", "price": 0}],
    })
    result = zxfps.collect_missing_prices("gun", ["18010000051"], session_factory=lambda a: session)
    assert result == {"18010000051": 166523}


def test_missing_target_exhausts_list_gracefully():
    session = _FakeSession({1: [_item("111", "甲", 1)], 2: [_item("222", "乙", 2)]})
    result = zxfps.collect_missing_prices("gun", ["999"], session_factory=lambda a: session)
    assert result == {}


def test_price_zero_or_negative_is_ignored():
    session = _FakeSession({1: [_item("18010000051", "MDR突击步枪", 0)]})
    assert zxfps.collect_missing_prices("gun", ["18010000051"], session_factory=lambda a: session) == {}
    session = _FakeSession({1: [_item("18010000051", "MDR突击步枪", -5)]})
    assert zxfps.collect_missing_prices("gun", ["18010000051"], session_factory=lambda a: session) == {}


def test_empty_wanted_short_circuits():
    calls = []
    def factory(a):
        calls.append(a)
        return _FakeSession({1: []})
    assert zxfps.collect_missing_prices("gun", []) == {}
    assert calls == []  # 没有目标 id → 不发任何请求
