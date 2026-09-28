"""官方 candidateMetrics 全量复现验证。

用本引擎（``load_game_data`` + ``WeaponStateResolver`` + ``build_context_from_state``）
重算 ``data/game/validation_samples.json`` 的全部样本（21 情景 / 1338 候选 / 3774 点），
输出分级精度统计与偏差明细，作为修复收敛的度量基线。

用法：
    python tools/verify_official_reproduction.py                 # 汇总到 stdout
    python tools/verify_official_reproduction.py --tol 1e-9 --report .probe/repro.json
    python tools/verify_official_reproduction.py --scenario armor-3-ammo-3-center

退出码：0=全部 |Δ|≤tol 达标；1=存在超差点。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_SAMPLES = os.path.join(ROOT, "data", "game", "validation_samples.json")
DEFAULT_TOL = 1e-9

# 分级精度档位（升序）
GRADES: Tuple[Tuple[str, float], ...] = (
    ("bitwise", 0.0),
    ("le_1e-9", 1e-9),
    ("le_1e-5", 1e-5),
    ("le_1e-2", 1e-2),
)


def parse_candidate(candidate_id: str) -> Tuple[str, str, str, Dict[str, str]]:
    """解析候选 id：``weapon:profile:ammo[:slot=part...][:stock]`` → (weapon, profile, ammo, loadout)。

    ``:stock`` 裸段表示官方原厂候选（无任何改装），loadout 为空 dict。
    """
    parts = candidate_id.split(":")
    if len(parts) < 3:
        raise ValueError(f"候选 id 段数不足：{candidate_id}")
    weapon_id, profile_key, ammo_id = parts[0], parts[1], parts[2]
    loadout: Dict[str, str] = {}
    for seg in parts[3:]:
        # loadout 段可能含多个 slot=part 对（逗号分隔），如 ``2=13020000532,52=13420000002``
        for chunk in seg.split(","):
            if "=" not in chunk:
                if chunk == "stock":
                    continue  # 原厂无改装标记
                raise ValueError(f"候选 id 的 loadout 段缺少 '='：{chunk}（{candidate_id}）")
            slot, part = chunk.split("=", 1)
            loadout[slot] = part
    return weapon_id, profile_key, ammo_id, loadout


def build_armor_definition(
    game_data: Any,
    scenario: Mapping[str, Any],
) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """从样本 ``scenario`` 组装引擎侧护甲定义（snake_case）与护甲等级。

    优先使用样本内官方 preset 的 ``maxDurability`` / ``coveredHitAreas``（官方 preset
    耐久可能低于 max），缺失的槽位回退到 ``armor.json`` 该等级默认值——但**不**用
    默认值覆盖样本已声明的字段。
    """
    defense = scenario.get("defense") or {}
    level_raw = scenario.get("armor_level")
    if level_raw is None:
        level_raw = (defense.get("armor") or {}).get("level")
    if level_raw is None:
        raise ValueError(f"情景 {scenario.get('scenario_id')} 缺少护甲等级")
    level = int(level_raw)

    base = game_data.defense(level) or {}

    def _slot(name: str) -> Dict[str, Any]:
        src = defense.get(name) or base.get(name) or {}
        return {
            "level": int(src.get("level", level)),
            "max_durability": float(src.get("maxDurability", src.get("max_durability", 0.0))),
            "covered_hit_areas": list(src.get("coveredHitAreas", src.get("covered_hit_areas", []))),
        }

    return {"helmet": _slot("helmet"), "armor": _slot("armor")}, level


def _grade(delta: float) -> str:
    for name, bound in GRADES:
        if delta <= bound:
            return name
    return "gt_1e-2"


def run_verification(
    tol: float = DEFAULT_TOL,
    samples_path: str = DEFAULT_SAMPLES,
    scenario_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """全量重算验证样本，返回汇总与全量偏差明细（供回归测试直接调用）。

    返回至少含 ``total_points`` / ``pass_count`` / ``fail_count`` / ``worst``
    （``worst`` 为 ``{delta, scenario, candidate, distance}``），以及分级统计
    ``grades`` 与 ``deviations``（|Δ|>tol 全量，每点含
    scenario/candidate/distance/official/local/delta）。
    """
    from src.engine.ballistics import build_context_from_state
    from src.engine.game_data import load_game_data
    from src.engine.weapon_state import WeaponStateResolver

    gd = load_game_data(os.path.join(ROOT, "data", "game"))
    resolver = WeaponStateResolver(gd)
    with open(samples_path, encoding="utf-8") as fh:
        samples = json.load(fh)["samples"]

    scenario_ids = sorted(samples)
    if scenario_filter:
        wanted = set(scenario_filter.split(","))
        missing = wanted - set(scenario_ids)
        if missing:
            raise KeyError(f"样本中不存在的情景：{sorted(missing)}")
        scenario_ids = [sid for sid in scenario_ids if sid in wanted]

    state_cache: Dict[str, Any] = {}
    armor_cache: Dict[str, Tuple[Dict[str, Dict[str, Any]], int]] = {}

    total_points = 0
    pass_count = 0
    grade_counts: Counter = Counter()
    deviations: List[Dict[str, Any]] = []
    fail_by_weapon: Counter = Counter()
    worst = {"delta": -1.0, "scenario": "", "candidate": "", "distance": 0.0}

    for sid in scenario_ids:
        s = samples[sid]
        scenario = s["scenario"]
        probs = scenario["hit_probabilities"]
        armor_def, armor_level = armor_cache.setdefault(sid, build_armor_definition(gd, scenario))
        for cand_id, points in s["candidate_metrics"]:
            weapon_id, profile_key, ammo_id, loadout = parse_candidate(cand_id)
            state = state_cache.get(cand_id)
            if state is None:
                state = resolver.resolve(f"{weapon_id}:{profile_key}", loadout=loadout)
                state_cache[cand_id] = state
            ammo = gd.get_ammo(ammo_id)
            for dist, official in points:
                dist_f = float(dist)
                ctx = build_context_from_state(
                    state, ammo, armor_def, probs, dist_f, armor_level=armor_level
                )
                got = ctx.expected_kill_shots()
                delta = abs(got - float(official))
                total_points += 1
                grade_counts[_grade(delta)] += 1
                if delta <= tol:
                    pass_count += 1
                else:
                    fail_count_delta = 1
                    deviations.append(
                        {
                            "scenario": sid,
                            "candidate": cand_id,
                            "distance": dist_f,
                            "official": float(official),
                            "local": got,
                            "delta": delta,
                        }
                    )
                    fail_by_weapon[weapon_id] += fail_count_delta
                if delta > worst["delta"]:
                    worst = {
                        "delta": delta,
                        "scenario": sid,
                        "candidate": cand_id,
                        "distance": dist_f,
                    }

    fail_count = total_points - pass_count
    return {
        "scenario_count": len(scenario_ids),
        "total_points": total_points,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "worst": worst,
        "grades": {name: grade_counts.get(name, 0) for name, _ in GRADES}
        | {"gt_1e-2": grade_counts.get("gt_1e-2", 0)},
        "deviations": deviations,
        "fail_by_weapon": dict(fail_by_weapon),
        "tol": tol,
    }


def _scenario_distribution(deviations: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter = Counter()
    for item in deviations:
        # armor-4-ammo-3-center → armor-4-ammo-3（命中情景不影响伤害参数）
        counts[item["scenario"].rsplit("-", 1)[0]] += 1
    return dict(sorted(counts.items()))


def record_residual(
    provenance_path: str,
    result: Dict[str, Any],
    conclusion: str,
) -> None:
    """把复验残余写入 ``provenance.json`` 的 ``integrity.official_reproduction_residual``。

    不允许静默放过无法归零的点：点数、最大 |Δ|、情景分布、结论与理由一并落盘。
    """
    with open(provenance_path, encoding="utf-8") as fh:
        provenance = json.load(fh)
    residual = {
        "verify_tol": result["tol"],
        "residual_points": result["fail_count"],
        "total_points": result["total_points"],
        "max_abs_delta": result["worst"]["delta"],
        "grade_counts": result["grades"],
        "scenario_distribution": _scenario_distribution(result["deviations"]),
        "conclusion": conclusion,
    }
    provenance.setdefault("integrity", {})["official_reproduction_residual"] = residual
    with open(provenance_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(provenance, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    print(f"  残余记录已写入 : {provenance_path} (integrity.official_reproduction_residual)")


def main() -> int:
    ap = argparse.ArgumentParser(description="官方 candidateMetrics 全量复现验证")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL, help="达标阈值（默认 1e-9）")
    ap.add_argument("--report", default=None, help="偏差明细 JSON 输出路径")
    ap.add_argument("--samples", default=DEFAULT_SAMPLES, help="验证样本路径")
    ap.add_argument("--scenario", default=None, help="仅验证指定情景（逗号分隔 id）")
    ap.add_argument(
        "--record-residual-conclusion",
        default=None,
        help="存在超差点时，把残余统计与该结论写入 provenance.json（需配合 --provenance）",
    )
    ap.add_argument("--provenance", default=os.path.join(ROOT, "data", "game", "provenance.json"))
    args = ap.parse_args()

    result = run_verification(
        tol=args.tol, samples_path=args.samples, scenario_filter=args.scenario
    )

    print("=" * 84)
    print("官方 candidateMetrics 全量复现验证")
    print("=" * 84)
    print(f"  样本情景数 : {result['scenario_count']}")
    print(f"  总点数     : {result['total_points']}")
    print(f"  通过(≤{args.tol:g}) : {result['pass_count']}")
    print(f"  超差       : {result['fail_count']}")
    g = result["grades"]
    print(f"  逐位一致(Δ=0)   : {g['bitwise']}")
    print(f"  ≤1e-9           : {g['le_1e-9']}")
    print(f"  ≤1e-5           : {g['le_1e-5']}")
    print(f"  ≤1e-2           : {g['le_1e-2']}")
    print(f"  >1e-2           : {g['gt_1e-2']}")
    w = result["worst"]
    print(f"  最大偏差        : {w['delta']:.6g} @ {w['scenario']} / {w['candidate']} / d={w['distance']}")
    if result["fail_by_weapon"]:
        print("  超差武器分布    :")
        for wid, n in sorted(result["fail_by_weapon"].items(), key=lambda kv: -kv[1]):
            print(f"    {wid}: {n}")
    print()

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(
                {"summary": {k: v for k, v in result.items() if k != "deviations"}, "deviations": result["deviations"]},
                fh,
                ensure_ascii=False,
                indent=1,
            )
        print(f"  偏差明细已写入 : {args.report}")
        print()

    if args.record_residual_conclusion:
        record_residual(args.provenance, result, args.record_residual_conclusion)

    if result["fail_count"] > 0:
        print("  结果：存在超差点（退出码 1）")
        return 1
    print("  结果：全部达标（退出码 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
