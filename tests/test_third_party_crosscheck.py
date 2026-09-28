"""第三方交叉核验：moligod 官方对象 ID 与本项目武器池互证（离线，不联网）。

守护 README 的可信度声明。原为 tools/crosscheck_third_party.py，
下沉为测试以保住声明的可验证性；脚本原 `--catalog` 可选项依赖本地缓存快照，
不属 CI 可复现范围，故不纳入。
"""

import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_PATH = os.path.join(ROOT, "data", "reference", "moligod_weapons.json")
WEAPONS_PATH = os.path.join(ROOT, "data", "game", "weapons.json")

_OBJECT_ID_RE = re.compile(r"/object/(\d+)\.png")


def _object_id(url: str):
    match = _OBJECT_ID_RE.search(url or "")
    return match.group(1) if match else None


@pytest.fixture(scope="module")
def reference():
    with open(REF_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def our_weapons():
    with open(WEAPONS_PATH, encoding="utf-8") as fh:
        return json.load(fh)["weapons"]


def test_reference_entries_are_self_consistent(reference):
    """参照条目自身的 object_id 必须等于其 image_url 中抽出的官方对象 ID。"""
    for entry in reference["weapons"]:
        assert _object_id(entry.get("image_url")) == entry["object_id"], entry["object_id"]


def test_overlap_ids_hit_our_pool_with_names(reference, our_weapons):
    """与本项目武器池的交集：ID 必须命中，且命中条目必须有名称。"""
    our_ids = {str(w["weapon_id"]) for w in our_weapons}
    our_names = {str(w["weapon_id"]): w.get("name", "") for w in our_weapons}

    overlap = [w for w in reference["weapons"] if w["object_id"] in our_ids]
    assert overlap, "参照条目与本项目武器池交集为空——参照数据或武器池可能已失配"
    for entry in overlap:
        assert our_names.get(entry["object_id"]), f"武器池命中但无名称：{entry['object_id']}"


def test_declared_verification_arithmetic_holds(reference):
    """verification_result 的三项计数必须自洽（README 声明的来源）。

    该文件为人工维护的核验存证（retrieved_at=2026-09-20）。重新采集会合法地
    改变这些数字，届时需同步更新 README 的「26/26」声明。
    """
    vr = reference["verification_result"]
    assert (
        vr["image_url_byte_identical"] + len(vr["explained_divergence"])
        == vr["entries_with_object_id"]
    ), "verification_result 计数不自洽：逐字节一致数 + 已解释差异数 != 有 objectID 的条目数"
    assert vr["name_match"] == vr["entries_with_object_id"]
