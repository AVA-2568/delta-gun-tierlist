"""官方 candidateMetrics 全量复现回归（P0 审计修复固化）。

阈值 1e-9。断言为**分级断言**而非朴素 fail_count==0：全量 3774 点收敛后仍残余
765 点（≤0.0245），经白盒对拍（``tools/verify_official_reproduction.py
--official-param-audit``）证明为官方上游侧自相矛盾（官方 dynamic 自声明参数
独立重算与本地逐位一致，官方 candidateMetrics 的 E 值自相矛盾），已裁定为上游
事实并记录于 ``data/game/provenance.json`` → ``integrity.official_reproduction_residual``。

因此本测试把复验结果与该记录逐项对齐：任何一侧漂移（数据被改、引擎被改）都会
使两者对不齐而 fail。provenance 缺少该记录时直接 fail（记录是收敛固化的必需品，
不许静默 skip）。数据缺失/为空时 skip 并说明（本地无网络不应误报）。
"""

import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL = 1e-9
SAMPLES_PATH = os.path.join(ROOT, "data", "game", "validation_samples.json")
PROVENANCE_PATH = os.path.join(ROOT, "data", "game", "provenance.json")


def _samples_path():
    if not os.path.exists(SAMPLES_PATH):
        pytest.skip("validation_samples.json 不存在")
    return SAMPLES_PATH


def _residual_record():
    """读取 provenance 的残余收敛记录；缺失即 fail（不许 skip）。"""
    if not os.path.exists(PROVENANCE_PATH):
        pytest.fail("provenance.json 不存在：残余收敛记录无处对齐")
    with open(PROVENANCE_PATH, encoding="utf-8") as fh:
        integrity = json.load(fh).get("integrity", {})
    record = integrity.get("official_reproduction_residual")
    if not record:
        pytest.fail(
            "provenance.json 缺少 integrity.official_reproduction_residual："
            "请运行 python tools/verify_official_reproduction.py "
            "--record-residual-conclusion '<结论>' 生成（不许静默 skip）"
        )
    return record


def test_official_candidate_metrics_reproduced():
    from tools.verify_official_reproduction import run_verification

    result = run_verification(tol=TOL, samples_path=_samples_path())
    record = _residual_record()
    worst = result["worst"]

    # 防样本缩水：总点数必须与收敛记录一致
    assert result["total_points"] == record["total_points"], (
        f"总点数漂移：现 {result['total_points']}，收敛记录 {record['total_points']}"
        f"（样本被改动？）"
    )

    # 残余点数（>tol 的超差点）与收敛记录一致
    assert result["fail_count"] == record["residual_points"], (
        f"残余点数漂移：现 {result['fail_count']}，收敛记录 {record['residual_points']}；"
        f"最差 {worst['delta']:.4f} @ {worst['scenario']}/{worst['candidate']}/{worst['distance']}m"
    )

    # 最差 |Δ| 与收敛记录一致（浮点比较用绝对差）
    assert abs(worst["delta"] - record["max_abs_delta"]) < 1e-9, (
        f"最差 |Δ| 漂移：现 {worst['delta']!r}，收敛记录 {record['max_abs_delta']!r} "
        f"@ {worst['scenario']}/{worst['candidate']}/{worst['distance']}m"
    )

    # 五档互斥分桶（和 = 总点数）逐档对齐
    assert result["grades"] == record["grade_counts"], (
        f"分级分桶漂移：现 {result['grades']}，收敛记录 {record['grade_counts']}"
    )

    # >1e-2 清单（scenario/candidate/distance/delta）与收敛记录一致
    gt_tol = sorted(
        (
            {
                "scenario": d["scenario"],
                "candidate": d["candidate"],
                "distance": d["distance"],
                "delta": d["delta"],
            }
            for d in result["deviations"]
            if d["delta"] > 1e-2
        ),
        key=lambda p: (-p["delta"], p["scenario"], p["candidate"], p["distance"]),
    )
    assert gt_tol == record["gt_1e-2_points"], (
        f">1e-2 点清单漂移：现 {gt_tol}，收敛记录 {record['gt_1e-2_points']}"
    )
