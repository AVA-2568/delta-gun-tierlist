"""官方 candidateMetrics 全量复现验证。

用本引擎（``load_game_data`` + ``WeaponStateResolver`` + ``build_context_from_state``）
重算 ``data/game/validation_samples.json`` 的全部样本（21 情景 / 1338 候选 / 3774 点），
输出分级精度统计与偏差明细，作为修复收敛的度量基线。

用法：
    python tools/verify_official_reproduction.py                 # 汇总到 stdout
    python tools/verify_official_reproduction.py --tol 1e-9 --report .probe/repro.json
    python tools/verify_official_reproduction.py --scenario armor-3-ammo-3-center

    # 白盒对拍模式：用官方 dynamic 情景自声明的 damageModel 参数独立重算残余点，
    # 输出「官方参数 vs 官方 E」矛盾点清单（见 run_official_param_audit）。
    python tools/verify_official_reproduction.py --official-param-audit
    python tools/verify_official_reproduction.py --official-param-audit \
        --record-residual-conclusion "<结论>"   # 落盘时把对拍分桶并入残余记录

    # 数据文件经合法途径（重跑同步器、审计修复再生成）更新后，重钉
    # provenance.outputs 哈希（tests/test_data_integrity.py 的回归基线）。
    python tools/verify_official_reproduction.py --refresh-output-hashes

退出码：0=全部 |Δ|≤tol 达标（对拍模式=无未归类矛盾点）；1=存在超差/未归类点。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_SAMPLES = os.path.join(ROOT, "data", "game", "validation_samples.json")
DEFAULT_TOL = 1e-9
DEFAULT_CACHE_DIR = os.path.join(ROOT, ".cache", "dfttk")
SOURCE_BASE = "https://dfttk.com/data/v3/"
USER_AGENT = "Mozilla/5.0 (compatible; delta-gun-tierlist)"

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


# ---------------------------------------------------------------------------
# 白盒对拍（official param audit）
#
# 背景：全量复现收敛后残余 765 点（≤0.0245，全部位于 center/default 混合命中
# 情景），经白盒对拍证明为官方上游侧自相矛盾——用官方
# ``rankings/firefight/dynamic/*.json`` 自声明的 ``weaponDamageResult.damageModel``
# （伤害 / 部位倍率 / 衰减段 / 穿甲修正 / 防具耐久与覆盖）直接驱动本引擎 DP，
# 765 点的官方参数重算值全部与本地引擎值逐位一致，而官方 candidateMetrics 仍
# 偏离 → 官方 E 与官方自己的参数表矛盾（本地无归零路径）。按官方 dynamic 是否
# 声明 ``ammo.perPart`` 细分：未声明 698 点（含全部 >1e-2 点）、声明 67 点
# （37260400002/37260500002）。
# 该模式把 ``.probe/validate_ballistics_full.py`` 的对拍逻辑并入正式工具，供
# 刷新 ``--record-residual-conclusion`` 残余记录时引用。命中分布为双方共用的
# 输入（与官方声明一致），取自验证样本，不属于被对拍的伤害参数。
# ---------------------------------------------------------------------------


def _official_conv_matrix(armor_correction: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """官方 ``ammoInteractions[*].armorCorrection`` → 引擎穿透矩阵口径。"""
    return {
        str(level): {
            "body_health_rate": v["bodyHealthRate"],
            "helmet_health_rate": v["helmetHealthRate"],
            "body_durability_rate": v["bodyDurabilityRate"],
            "helmet_durability_rate": v["helmetDurabilityRate"],
            "penetrates": v["penetrates"],
        }
        for level, v in armor_correction.items()
    }


def _official_rate_at(segments: Sequence[Mapping[str, Any]], distance: float) -> float:
    """官方 ``damageFalloffSegments``：``[fromM, toM)`` 分段线性衰减率。"""
    for seg in segments:
        if seg["fromM"] <= distance < seg["toM"]:
            return float(seg["rate"])
    return float(segments[-1]["rate"]) if segments else 1.0


def _locate_official_dynamic_file(base: str, cache_dir: str) -> str:
    """定位官方 dynamic 情景文件：缓存 → .probe 遗留产物 → 按 Task 1 下载模式联网取。"""
    filename = f"rankings__firefight__dynamic__{base}.json"
    for path in (os.path.join(cache_dir, filename), os.path.join(ROOT, ".probe", filename)):
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    url = f"{SOURCE_BASE}rankings/firefight/dynamic/{base}.json"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=40) as response:
        payload = response.read()
    os.makedirs(cache_dir, exist_ok=True)
    target = os.path.join(cache_dir, filename)
    with open(target, "wb") as fh:
        fh.write(payload)
    return target


def run_official_param_audit(
    tol: float = DEFAULT_TOL,
    samples_path: str = DEFAULT_SAMPLES,
    cache_dir: str = DEFAULT_CACHE_DIR,
    match_tol: float = 1e-9,
    verification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """白盒对拍：用官方自声明参数独立重算全部残余点，输出矛盾点清单。

    先取（或现跑）:func:`run_verification` 的残余点（|Δ|>tol），再对每个残余点：

    1. 从官方 dynamic 文件取该候选的 ``damageModel`` 与 ``ammoInteractions``，
       构造官方口径弹药（含 ``perPart``，若官方有声明），驱动 ``DamageContext``
       独立重算 audit 值；
    2. 分类（基线 765 残余点的实测分桶为 698/67/0）：
       - ``param_contradiction_no_perpart``（698）：audit 值与本地引擎值逐位一致
         （≤match_tol）而官方 E 仍偏离，且官方 dynamic **未**声明 ``ammo.perPart``
         → 官方 E 与官方参数表自相矛盾（含全部 >1e-2 点）；
       - ``param_contradiction_with_perpart``（67）：同上逐位一致且 E 偏离，但官方
         dynamic **声明了** ``ammo.perPart``（37260400002/37260500002）→ 官方 E
         与含 perPart 的官方参数表同样矛盾；
       - ``unclassified``：以上皆非（audit 与本地不一致等）→ 需人工复查（退出码 1）。

    注意：provenance 残余记录 conclusion 文字中「67 点官方 dynamic 声明缺
    ammo.perPart」的表述与数据实际相反——67 点恰是 dynamic **声明了** perPart
    的点（未声明者为 698），698/67 计数本身与记录一致。

    用途与用法见模块 docstring；联网仅在缓存与 .probe 均缺失 dynamic 文件时发生。
    返回字典含 ``residual_points`` / ``buckets`` / ``bucket_examples`` /
    ``max_conflict_delta`` / ``unclassified_detail`` 与内部 ``verification``
    （供 ``--record-residual-conclusion`` 同源落盘）。
    """
    from src.engine.ballistics import DamageContext

    if verification is None:
        verification = run_verification(tol=tol, samples_path=samples_path)
    with open(samples_path, encoding="utf-8") as fh:
        samples = json.load(fh)["samples"]

    by_base: Dict[str, List[Dict[str, Any]]] = {}
    for item in verification["deviations"]:
        by_base.setdefault(item["scenario"].rsplit("-", 1)[0], []).append(item)

    bucket_counts: Counter = Counter()
    bucket_examples: Dict[str, List[Dict[str, Any]]] = {}
    unclassified_detail: List[Dict[str, Any]] = []
    max_conflict_delta = 0.0
    audit_value_max: Dict[str, Optional[Dict[str, Any]]] = {
        "param_contradiction_no_perpart": None,
        "param_contradiction_with_perpart": None,
    }
    contradiction_buckets = tuple(audit_value_max)

    for base, items in sorted(by_base.items()):
        with open(_locate_official_dynamic_file(base, cache_dir), encoding="utf-8") as fh:
            dyn = json.load(fh)
        dyn_by_cand = {c["candidateId"]: c for c in dyn["candidates"]}
        for item in items:
            entry = dyn_by_cand.get(item["candidate"])
            reason = None
            if entry is None:
                reason = "candidate_not_in_dynamic"
            else:
                wdr = entry["weaponDamageResult"]
                corr = (dyn.get("ammoInteractions") or {}).get(entry["ammoItemId"])
                if corr is None:
                    reason = "ammo_not_in_interactions"
            if reason is not None:
                bucket_counts["unclassified"] += 1
                unclassified_detail.append({**item, "reason": reason})
                continue

            dm = wdr["damageModel"]
            scenario = samples[item["scenario"]]["scenario"]
            per_part = (wdr.get("ammo") or {}).get("perPart") or {}
            ammo = {
                "flesh_damage_multiplier": dm["damageMultiplier"],
                "armor_damage_multiplier": dm["armorDamageMultiplier"],
                "penetration_matrix": _official_conv_matrix(corr["armorCorrection"]),
                "per_part": per_part,
            }
            ctx = DamageContext(
                base_flesh=dm["baseFleshDamage"],
                base_armor=dm["baseArmorDamage"],
                hitbox_multipliers=dm["weaponHitMultipliers"],
                ammo=ammo,
                armor_level=int(dyn["defensePresetKey"]),
                helmet_durability=dyn["defense"]["helmetDurability"],
                armor_durability=dyn["defense"]["armorDurability"],
                helmet_covered=dyn["defense"]["helmet"]["coveredHitAreas"],
                armor_covered=dyn["defense"]["armor"]["coveredHitAreas"],
                hit_probabilities=scenario["hit_probabilities"],
                falloff=_official_rate_at(dm["damageFalloffSegments"], item["distance"]),
            )
            audit_val = ctx.expected_kill_shots()

            if abs(audit_val - item["local"]) <= match_tol:
                # 官方参数重算 = 本地，而官方 E 仍偏离 → 官方自相矛盾；
                # 按官方 dynamic 是否声明 perPart 细分（基线 698/67）
                bucket = (
                    "param_contradiction_with_perpart" if per_part
                    else "param_contradiction_no_perpart"
                )
            else:
                bucket = "unclassified"
                unclassified_detail.append(
                    {**item, "audit": audit_val, "reason": "audit_mismatch_local"}
                )
            bucket_counts[bucket] += 1
            conflict = abs(item["official"] - audit_val)
            if bucket in contradiction_buckets:
                max_conflict_delta = max(max_conflict_delta, conflict)
            record = {
                "scenario": item["scenario"],
                "candidate": item["candidate"],
                "distance": item["distance"],
                "official": item["official"],
                "local": item["local"],
                "audit": audit_val,
            }
            bucket_examples.setdefault(bucket, [])
            if len(bucket_examples[bucket]) < 5:
                bucket_examples[bucket].append(record)
            if bucket in audit_value_max:
                cur = audit_value_max[bucket]
                if cur is None or conflict > cur["conflict"]:
                    audit_value_max[bucket] = {**record, "conflict": conflict}

    return {
        "tol": tol,
        "residual_points": verification["fail_count"],
        "total_points": verification["total_points"],
        "worst": verification["worst"],
        "verification": verification,
        "buckets": {
            "param_contradiction_no_perpart": bucket_counts.get(
                "param_contradiction_no_perpart", 0
            ),
            "param_contradiction_with_perpart": bucket_counts.get(
                "param_contradiction_with_perpart", 0
            ),
            "unclassified": bucket_counts.get("unclassified", 0),
        },
        "bucket_examples": bucket_examples,
        "max_conflict_delta": max_conflict_delta,
        "audit_value_max": audit_value_max,
        "unclassified_detail": unclassified_detail,
        "bases": sorted(by_base),
    }


def _print_audit_report(audit: Dict[str, Any]) -> None:
    print("=" * 84)
    print("白盒对拍：官方 dynamic 自声明参数独立重算 vs 官方 candidateMetrics")
    print("=" * 84)
    print(f"  总点数            : {audit['total_points']}")
    print(f"  残余点(|Δ|>{audit['tol']:g}) : {audit['residual_points']}")
    b = audit["buckets"]
    print(f"  矛盾点：官方参数重算=本地(逐位)而官方 E 偏离，dynamic 未声明 perPart : {b['param_contradiction_no_perpart']}")
    print(f"  矛盾点：同上，但 dynamic 声明了 perPart(37260400002/37260500002)      : {b['param_contradiction_with_perpart']}")
    print(f"  未归类(需人工复查)                                                   : {b['unclassified']}")
    print(f"  矛盾点最大冲突幅度 |官方E − 官方参数重算| : {audit['max_conflict_delta']:.6g}")
    w = audit["worst"]
    print(f"  残余最差点 : {w['delta']:.6g} @ {w['scenario']} / {w['candidate']} / d={w['distance']}")
    for bucket in (
        "param_contradiction_no_perpart",
        "param_contradiction_with_perpart",
        "unclassified",
    ):
        for ex in audit["bucket_examples"].get(bucket, [])[:3]:
            print(
                f"    [{bucket}] {ex['scenario']} {ex['candidate']} @{ex['distance']}m "
                f"E={ex['official']:.9f} local={ex['local']:.9f} audit={ex['audit']:.9f}"
            )
    for item in audit["unclassified_detail"]:
        print(f"    [unclassified] {item}")


def record_residual(
    provenance_path: str,
    result: Dict[str, Any],
    conclusion: str,
) -> None:
    """把复验残余写入 ``provenance.json`` 的 ``integrity.official_reproduction_residual``。

    不允许静默放过无法归零的点：点数、最大 |Δ|、情景分布、>1e-2 点清单、
    结论与理由一并落盘。注意 ``grade_counts`` 为**互斥**分桶（五档之和 = 总点数）。
    """
    with open(provenance_path, encoding="utf-8") as fh:
        provenance = json.load(fh)
    gt_tol_points = sorted(
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
    residual = {
        "verify_tol": result["tol"],
        "residual_points": result["fail_count"],
        "total_points": result["total_points"],
        "max_abs_delta": result["worst"]["delta"],
        "grade_counts": result["grades"],
        "grade_counts_note": "互斥分桶：五档之和 = total_points",
        "scenario_distribution": _scenario_distribution(result["deviations"]),
        "gt_1e-2_points": gt_tol_points,
        "conclusion": conclusion,
    }
    provenance.setdefault("integrity", {})["official_reproduction_residual"] = residual
    with open(provenance_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(provenance, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    print(f"  残余记录已写入 : {provenance_path} (integrity.official_reproduction_residual)")


def refresh_output_hashes(
    provenance_path: str,
    data_dir: str = os.path.join(ROOT, "data", "game"),
    confirm: bool = False,
) -> None:
    """按 ``_write_json`` 同款规范化口径重算并重钉 ``provenance.outputs`` 哈希。

    用途：数据文件经合法途径（重跑同步器、审计修复再生成）更新后，把
    ``provenance.json`` 的 ``outputs`` 逐文件 SHA256 重钉为当前内容——
    ``tests/test_data_integrity.py::test_provenance_output_hashes_match`` 以此为
    回归基线。CLI：``python tools/verify_official_reproduction.py
    --refresh-output-hashes [--confirm]``。禁止用它掩盖未审查的数据改动（改动应先经
    全量复现验证与本测试套件确认）。

    护栏：不带 ``--confirm`` 时只打印将修改的文件与原因并拒绝写入——
    重钉会改写回归基线，口径或内容有误时会把错误固化（曾因此误钉）。
    """
    import hashlib

    with open(provenance_path, encoding="utf-8") as fh:
        provenance = json.load(fh)
    outputs = provenance.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise SystemExit(f"{provenance_path} 缺少 outputs 哈希记录，无从重钉")
    pending: list = []
    for name in sorted(outputs):
        path = os.path.join(data_dir, name)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != outputs[name]:
            pending.append((name, outputs[name], digest))
            outputs[name] = digest
    if not pending:
        print("  全部 outputs 哈希已与当前文件一致，无需重钉")
        return
    if not confirm:
        print("  拒绝重钉：缺少 --confirm。本次将修改：")
        for name, old, new in pending:
            print(f"    {provenance_path} :: {name}  {old[:12]}… → {new[:12]}…")
        print("  原因：重钉会改写 provenance.outputs 回归基线；若口径或内容有误，")
        print("  会把错误基线固化并掩盖未审查的数据改动。确认数据文件已经")
        print("  全量复现验证与测试套件审查后，加 --confirm 重跑。")
        raise SystemExit(2)
    with open(provenance_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(provenance, fh, ensure_ascii=False, indent=1, sort_keys=False)
        fh.write("\n")
    print(f"  已重钉 {len(pending)}/{len(outputs)} 个哈希 → {provenance_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description="官方 candidateMetrics 全量复现验证")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL, help="达标阈值（默认 1e-9）")
    ap.add_argument("--report", default=None, help="偏差明细 JSON 输出路径")
    ap.add_argument("--samples", default=DEFAULT_SAMPLES, help="验证样本路径")
    ap.add_argument("--scenario", default=None, help="仅验证指定情景（逗号分隔 id）")
    ap.add_argument(
        "--official-param-audit",
        action="store_true",
        help="白盒对拍模式：用官方 dynamic 自声明参数独立重算残余点，输出矛盾点清单"
        "（耗时较长，不进常规测试；用法见模块 docstring）",
    )
    ap.add_argument(
        "--record-residual-conclusion",
        default=None,
        help="存在超差点时，把残余统计与该结论写入 provenance.json（需配合 --provenance）",
    )
    ap.add_argument(
        "--refresh-output-hashes",
        action="store_true",
        help="按 _write_json 口径重钉 provenance.outputs 哈希为当前 data/game 文件内容"
        "（数据文件经合法途径再生成后使用，用法见 refresh_output_hashes docstring）",
    )
    ap.add_argument("--provenance", default=os.path.join(ROOT, "data", "game", "provenance.json"))
    args = ap.parse_args()

    if args.refresh_output_hashes:
        refresh_output_hashes(args.provenance)
        return 0

    if args.official_param_audit:
        audit = run_official_param_audit(tol=args.tol, samples_path=args.samples)
        _print_audit_report(audit)
        print()
        if args.report:
            os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
            with open(args.report, "w", encoding="utf-8") as fh:
                json.dump(audit, fh, ensure_ascii=False, indent=1)
            print(f"  对拍明细已写入 : {args.report}")
        if args.record_residual_conclusion:
            b = audit["buckets"]
            conclusion = (
                f"{args.record_residual_conclusion}"
                f"（白盒对拍：官方参数重算与本地逐位一致而官方 E 偏离 "
                f"{b['param_contradiction_no_perpart'] + b['param_contradiction_with_perpart']} 点，"
                f"其中官方 dynamic 未声明 perPart {b['param_contradiction_no_perpart']} 点、"
                f"声明了 perPart {b['param_contradiction_with_perpart']} 点；"
                f"未归类 {b['unclassified']} 点）"
            )
            record_residual(args.provenance, audit["verification"], conclusion)
        unclassified = audit["buckets"]["unclassified"]
        if unclassified:
            print(f"  结果：{unclassified} 个未归类矛盾点（退出码 1）")
            return 1
        print("  结果：残余点全部可归因为官方上游侧自相矛盾（退出码 0）")
        return 0

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
    print("  分级精度（五档互斥，和 = 总点数）：")
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
