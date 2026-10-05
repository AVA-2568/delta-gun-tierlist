"""输入指纹与轻量价格刷新（--price-only / --check-stale）测试。

覆盖三件套：

1. :func:`src.pipeline.compute_inputs_fingerprint` —— 稳定性（同输入同指纹）
   与敏感性（data/tables / 引擎 / 管线任一内容变化即变；价格表变化**不变**）；
2. :func:`src.pipeline.refresh_payload_prices` / ``refresh_prices`` —— 价格列
   数值口径与 ``compute_kill_cost`` / ``compute_full_price`` 直算一致，
   TTK 字段（mean/worst/expected_shots）保持原值；
3. :func:`src.pipeline.check_stale` —— 指纹一致新鲜、缺失 / 旧产物 / 不一致过期。
"""

import json
import logging
import os
import re
from pathlib import Path

from src import pipeline as pipeline_mod
from src.engine.tiering import compute_full_price, compute_kill_cost
from src.pipeline import (
    INPUTS_FINGERPRINT_KEY,
    _load_payloads_from_disk,
    _scenario_payload_path,
    check_stale,
    compute_inputs_fingerprint,
    refresh_payload_prices,
    refresh_prices,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SID = "armor-5-ammo-5-default"
OLD_AMMO_PRICE = 100
NEW_AMMO_PRICE = 200
OLD_GUN_PRICE = 1000
NEW_GUN_PRICE = 2000
SHOTS = 6.178526  # 取自真实榜单的带内平均期望发数


# --------------------------------------------------------------------------- #
# 迷你输入构造（tmp 副本，不触碰仓库产物）
# --------------------------------------------------------------------------- #

def _make_fp_tree(root: Path) -> None:
    """构造覆盖指纹全部输入域的迷你目录树（含不应参与指纹的价格表）。"""
    (root / "data" / "tables" / "parts").mkdir(parents=True)
    (root / "data" / "tables" / "ammo.json").write_bytes(b'{"a": 1}\n')
    (root / "data" / "tables" / "parts" / "p.json").write_bytes(b'{"b": 2}\n')
    (root / "data" / "reference").mkdir(parents=True)
    (root / "data" / "reference" / "ammo_prices.json").write_bytes(
        b'{"schema": "ammo-price-daily"}\n'
    )
    (root / "src" / "engine").mkdir(parents=True)
    (root / "src" / "engine" / "__init__.py").write_bytes(b"")
    (root / "src" / "engine" / "ballistics.py").write_bytes(b"A = 1\n")
    (root / "src" / "pipeline.py").write_bytes(b"B = 2\n")


class _FakeTable:
    """价格表桩：与 PriceTable 的查询接口同形（currency/window/updated_at/is_empty/price_for）。"""

    def __init__(self, prices, updated_at="2026-10-06"):
        self.currency = "哈夫币"
        self.window = {"from": updated_at, "to": updated_at, "days": 1}
        self.updated_at = updated_at
        self.prices = prices
        self.is_empty = not prices

    def price_for(self, key):
        return self.prices.get(str(key))


def _mini_payload(*, fingerprint="a" * 64):
    """迷你榜单 payload：单状态行、两距离带，价格列记录旧价。"""
    return {
        "scenario_id": SID,
        INPUTS_FINGERPRINT_KEY: fingerprint,
        "ammo_price_meta": {
            "currency": "哈夫币", "window": {}, "updated_at": "2026-10-01",
            "available": True,
        },
        "weapon_price_meta": {
            "currency": "哈夫币", "window": {}, "updated_at": "2026-10-01",
            "available": True, "spare_ammo_rounds": 180,
        },
        "band_definitions": {"近距": {"from_m": 0, "to_m": 50}},
        "weapons": [
            {
                "profile_key": "w1:base",
                "weapon_id": "w1",
                "name": "枪一",
                "ammo": {
                    "ammo_item_id": "ammo1", "name": "弹一",
                    "caliber": "5.56x45mm", "price_daily": OLD_AMMO_PRICE,
                },
                "gun_price_daily": OLD_GUN_PRICE,
                "full_price_180rd": OLD_GUN_PRICE + 180 * OLD_AMMO_PRICE,
                "bands": {
                    "近距": {
                        "rank": 1, "tier": "T0",
                        "mean_ms": 300.5, "worst_ms": 310.25, "best_ms": 295.0,
                        "mean_expected_shots": SHOTS,
                        "kill_cost": int(SHOTS * OLD_AMMO_PRICE + 0.5),
                    },
                    "远距": {
                        "rank": 2, "tier": "T3",
                        "mean_ms": 800.125, "worst_ms": 900.5, "best_ms": 700.0,
                        "mean_expected_shots": 9.5,
                        "kill_cost": int(9.5 * OLD_AMMO_PRICE + 0.5),
                    },
                },
            },
        ],
    }


def _write_price_tables(root: Path, ammo_price: int, gun_price: int,
                        updated_at: str = "2026-10-06") -> None:
    """按真实加载器的 schema 在 ``<root>/data/reference/`` 写价格表。"""
    ref = root / "data" / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    (ref / "ammo_prices.json").write_text(json.dumps({
        "schema": "ammo-price-daily",
        "currency": "哈夫币",
        "window": {"from": updated_at, "to": updated_at, "days": 1},
        "updated_at": updated_at,
        "ammo": [{"ammo_item_id": "ammo1", "price_daily": ammo_price}],
    }, ensure_ascii=False), encoding="utf-8")
    (ref / "weapon_prices.json").write_text(json.dumps({
        "schema": "weapon-price-daily",
        "currency": "哈夫币",
        "window": {"from": updated_at, "to": updated_at, "days": 1},
        "updated_at": updated_at,
        "weapons": [{"weapon_id": "w1", "price_daily": gun_price}],
    }, ensure_ascii=False), encoding="utf-8")


def _write_ranking_json(root: Path, payload) -> str:
    ranking_dir = root / "data" / "榜单"
    ranking_dir.mkdir(parents=True, exist_ok=True)
    path = ranking_dir / "护甲5弹药5-实战.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return str(path)


def _scenario_meta():
    return {
        "scenario_id": SID,
        "armor_level": 5, "ammo_level": 5, "probability_preset": "default",
    }


# --------------------------------------------------------------------------- #
# 1. 输入指纹
# --------------------------------------------------------------------------- #

def test_fingerprint_is_stable_for_same_inputs(tmp_path):
    _make_fp_tree(tmp_path)
    fp1 = compute_inputs_fingerprint(str(tmp_path))
    fp2 = compute_inputs_fingerprint(str(tmp_path))
    assert fp1 == fp2
    assert re.fullmatch(r"[0-9a-f]{64}", fp1)


def test_fingerprint_real_repo_is_stable_and_hex():
    """真实仓库（data/tables 约 5MB）两次计算一致，且为 SHA256 十六进制串。"""
    fp1 = compute_inputs_fingerprint(ROOT)
    fp2 = compute_inputs_fingerprint(ROOT)
    assert fp1 == fp2
    assert re.fullmatch(r"[0-9a-f]{64}", fp1)


def test_fingerprint_changes_when_any_table_file_changes(tmp_path):
    _make_fp_tree(tmp_path)
    fp_before = compute_inputs_fingerprint(str(tmp_path))

    table = tmp_path / "data" / "tables" / "ammo.json"
    table.write_bytes(b'{"a": 999}\n')
    assert compute_inputs_fingerprint(str(tmp_path)) != fp_before

    fp_mid = compute_inputs_fingerprint(str(tmp_path))
    # 新增文件同样改变指纹（目录内容整体参与）
    (tmp_path / "data" / "tables" / "parts" / "q.json").write_bytes(b'{"c": 3}\n')
    assert compute_inputs_fingerprint(str(tmp_path)) != fp_mid


def test_fingerprint_changes_when_engine_or_pipeline_changes(tmp_path):
    _make_fp_tree(tmp_path)
    fp_before = compute_inputs_fingerprint(str(tmp_path))

    (tmp_path / "src" / "engine" / "ballistics.py").write_bytes(b"A = 2\n")
    assert compute_inputs_fingerprint(str(tmp_path)) != fp_before

    fp_mid = compute_inputs_fingerprint(str(tmp_path))
    (tmp_path / "src" / "pipeline.py").write_bytes(b"B = 3\n")
    assert compute_inputs_fingerprint(str(tmp_path)) != fp_mid


def test_fingerprint_ignores_daily_price_tables(tmp_path):
    """核心性质：价格表每日变动**不**改变指纹（否则条件重算永远短路失效）。"""
    _make_fp_tree(tmp_path)
    fp_before = compute_inputs_fingerprint(str(tmp_path))
    (tmp_path / "data" / "reference" / "ammo_prices.json").write_bytes(
        b'{"schema": "ammo-price-daily", "changed": true}\n'
    )
    (tmp_path / "data" / "reference" / "weapon_prices.json").write_bytes(b"{}\n")
    assert compute_inputs_fingerprint(str(tmp_path)) == fp_before


# --------------------------------------------------------------------------- #
# 2. 价格列刷新（口径与 tiering 引擎一致，TTK 字段不动）
# --------------------------------------------------------------------------- #

def test_refresh_payload_prices_missing_price_yields_none():
    """缺价不猜测：弹药缺价 → 成本列全 None，指纹不被价格刷新改动。"""
    payload = _mini_payload()
    payload["weapons"][0]["ammo"]["ammo_item_id"] = "ammo_unknown"

    refresh_payload_prices(
        payload, _FakeTable({}), _FakeTable({"w1": NEW_GUN_PRICE})
    )

    row = payload["weapons"][0]
    assert row["ammo"]["price_daily"] is None
    assert row["gun_price_daily"] == NEW_GUN_PRICE
    assert row["full_price_180rd"] is None  # 缺弹药价 → 整列 None
    for band in row["bands"].values():
        assert band["kill_cost"] is None
    assert payload["inputs_fingerprint"] == "a" * 64
    assert payload["weapon_price_meta"]["updated_at"] == "2026-10-06"


def test_refresh_payload_prices_matches_engine_direct_computation():
    """刷新值必须与 compute_kill_cost / compute_full_price 直算完全一致。"""
    payload = _mini_payload()
    refresh_payload_prices(
        payload,
        _FakeTable({"ammo1": NEW_AMMO_PRICE}),
        _FakeTable({"w1": NEW_GUN_PRICE}),
    )
    row = payload["weapons"][0]
    assert row["ammo"]["price_daily"] == NEW_AMMO_PRICE
    assert row["gun_price_daily"] == NEW_GUN_PRICE
    assert row["full_price_180rd"] == compute_full_price(NEW_GUN_PRICE, NEW_AMMO_PRICE)
    assert row["full_price_180rd"] == NEW_GUN_PRICE + 180 * NEW_AMMO_PRICE
    origin = _mini_payload()["weapons"][0]
    for band_name, band in row["bands"].items():
        assert band["kill_cost"] == compute_kill_cost(
            band["mean_expected_shots"], NEW_AMMO_PRICE
        )
        # TTK 字段逐字节不动
        old = origin["bands"][band_name]
        for key in ("rank", "tier", "mean_ms", "worst_ms", "best_ms",
                    "mean_expected_shots"):
            assert band[key] == old[key]


def test_refresh_prices_on_disk(tmp_path):
    """端到端（tmp 目录）：改弹药价后重跑，kill_cost 变化而 mean_ms 不变。"""
    old_payload = _mini_payload()
    path = _write_ranking_json(tmp_path, old_payload)
    _write_price_tables(tmp_path, ammo_price=NEW_AMMO_PRICE, gun_price=NEW_GUN_PRICE)
    before = Path(path).read_bytes()

    result = refresh_prices(output_dir=str(tmp_path), scenarios=[SID], write=False)

    assert result["refreshed"] == [SID]
    assert result["skipped"] == []
    row = result["payloads"][SID]["weapons"][0]
    band = row["bands"]["近距"]
    # kill_cost 随新弹药价变化，且与 compute_kill_cost 直算一致
    assert band["kill_cost"] != old_payload["weapons"][0]["bands"]["近距"]["kill_cost"]
    assert band["kill_cost"] == compute_kill_cost(SHOTS, NEW_AMMO_PRICE)
    assert row["bands"]["远距"]["kill_cost"] == compute_kill_cost(9.5, NEW_AMMO_PRICE)
    # TTK 字段保持原值
    assert band["mean_ms"] == 300.5
    assert band["worst_ms"] == 310.25
    assert band["mean_expected_shots"] == SHOTS
    # 价格行与 meta 刷新
    assert row["gun_price_daily"] == NEW_GUN_PRICE
    assert row["full_price_180rd"] == NEW_GUN_PRICE + 180 * NEW_AMMO_PRICE
    assert result["payloads"][SID]["ammo_price_meta"]["updated_at"] == "2026-10-06"
    # write=False：磁盘 JSON 不动；指纹保持原值
    assert Path(path).read_bytes() == before
    assert result["payloads"][SID][INPUTS_FINGERPRINT_KEY] == "a" * 64


def test_refresh_prices_skips_missing_or_unfingerprinted(tmp_path, caplog):
    """JSON 缺失或无 inputs_fingerprint（旧产物）→ 报错跳过该情景。"""
    payload = _mini_payload()
    del payload[INPUTS_FINGERPRINT_KEY]
    _write_ranking_json(tmp_path, payload)
    _write_price_tables(tmp_path, ammo_price=NEW_AMMO_PRICE, gun_price=NEW_GUN_PRICE)

    with caplog.at_level(logging.ERROR, logger="src.pipeline"):
        result = refresh_prices(
            output_dir=str(tmp_path),
            scenarios=[SID, "armor-9-ammo-9-default"],
            write=False,
        )
    assert result["refreshed"] == []
    assert result["skipped"] == [SID, "armor-9-ammo-9-default"]
    assert any("全量重算" in r.getMessage() for r in caplog.records)


def test_refresh_prices_hands_refreshed_payloads_to_renderer(tmp_path, monkeypatch):
    """write=True：刷新后的 payload 交给既有渲染层落盘（产物与全量重算同构）。"""
    _write_ranking_json(tmp_path, _mini_payload())
    _write_price_tables(tmp_path, ammo_price=NEW_AMMO_PRICE, gun_price=NEW_GUN_PRICE)
    captured = {}

    def fake_render(payloads, output_dir, game_data, part_names):
        captured["payloads"] = payloads
        captured["output_dir"] = output_dir
        return ["fake.md"]

    monkeypatch.setattr(pipeline_mod, "_render_outputs", fake_render)

    class _FakeGameData:
        scenarios_raw = {"scenarios": [_scenario_meta()]}
        parts = {}
        provenance = {}

    monkeypatch.setattr(pipeline_mod, "load_game_data", lambda data_dir: _FakeGameData())

    result = refresh_prices(output_dir=str(tmp_path), scenarios=[SID], write=True)

    assert result["files_written"] == ["fake.md"]
    assert captured["output_dir"] == str(tmp_path)
    row = captured["payloads"][SID]["weapons"][0]
    assert row["bands"]["近距"]["kill_cost"] == compute_kill_cost(SHOTS, NEW_AMMO_PRICE)
    assert row["bands"]["近距"]["mean_ms"] == 300.5


# --------------------------------------------------------------------------- #
# 3. --check-stale 指纹比对
# --------------------------------------------------------------------------- #

def test_check_stale_fresh_when_fingerprint_matches(tmp_path):
    _write_ranking_json(tmp_path, _mini_payload(
        fingerprint=compute_inputs_fingerprint(str(tmp_path)),
    ))
    assert check_stale(output_dir=str(tmp_path), scenarios=[SID]) == []


def test_check_stale_reports_mismatch_missing_and_legacy(tmp_path):
    # 指纹不一致
    _write_ranking_json(tmp_path, _mini_payload(fingerprint="b" * 64))
    reasons = check_stale(output_dir=str(tmp_path), scenarios=[SID])
    assert len(reasons) == 1 and "指纹与当前输入不一致" in reasons[0]

    # 旧产物无指纹
    legacy = _mini_payload()
    del legacy[INPUTS_FINGERPRINT_KEY]
    _write_ranking_json(tmp_path, legacy)
    reasons = check_stale(output_dir=str(tmp_path), scenarios=[SID])
    assert len(reasons) == 1 and "无输入指纹" in reasons[0]

    # JSON 缺失（文件被删后 data/榜单/ 目录仍在但无此情景）
    (tmp_path / "data" / "榜单" / "护甲5弹药5-实战.json").unlink()
    assert check_stale(output_dir=str(tmp_path), scenarios=[SID]) == [
        f"{SID}: 缺少榜单 JSON（data/榜单/）"
    ]


# --------------------------------------------------------------------------- #
# 4. --render-only 读盘时的指纹警告
# --------------------------------------------------------------------------- #

def test_render_only_warns_when_fingerprint_missing_or_mismatched(tmp_path, caplog):
    path = _scenario_payload_path(str(tmp_path), _scenario_meta())
    os.makedirs(os.path.dirname(path), exist_ok=True)

    legacy = _mini_payload()
    del legacy[INPUTS_FINGERPRINT_KEY]
    Path(path).write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="src.pipeline"):
        payloads = _load_payloads_from_disk(
            str(tmp_path), [SID], {SID: _scenario_meta()}
        )
    assert payloads[SID]["scenario_id"] == SID
    assert any("无输入指纹" in r.getMessage() for r in caplog.records)

    stale = _mini_payload(fingerprint="b" * 64)
    Path(path).write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="src.pipeline"):
        _load_payloads_from_disk(str(tmp_path), [SID], {SID: _scenario_meta()})
    assert any("指纹与当前不一致" in r.getMessage() for r in caplog.records)

    fresh = _mini_payload(fingerprint=compute_inputs_fingerprint(str(tmp_path)))
    Path(path).write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="src.pipeline"):
        _load_payloads_from_disk(str(tmp_path), [SID], {SID: _scenario_meta()})
    assert not any("指纹" in r.getMessage() for r in caplog.records)
