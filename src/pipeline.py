"""纯 TTK 榜单管线：官方数据 → 最优配装求解 → 分层 → 渲染 → 导出。

用法::

    python -m src.pipeline                      # 默认 5 个情景（见 DEFAULT_SCENARIOS）
    python -m src.pipeline --all                # 全部 21 个官方情景（含理论聚焦预设）
    python -m src.pipeline --scenario 5-5       # 单个甲弹组合的实战情景
    python -m src.pipeline --limit 8            # 快速冒烟（前 8 把枪）
    python -m src.pipeline --render-only        # 不重算，从已有榜单 JSON 重渲染文档

输出：

- ``data/榜单/护甲X弹药Y-<预设>.json`` —— 机器可读榜单（含层级阈值）
- ``docs/榜单/<情景名>-<距离带>.md`` —— 每情景 4 份独立距离榜（主榜前缀 ``主榜``）
- ``README.md`` —— 首页：口径 + 主榜速览（每带 Top 5）+ 导航
- ``docs/改枪指南.md`` —— 改枪指南（不进 TTK 的维度）

内部 ``scenario_id``（如 ``armor-5-ammo-5-default``）保持英文稳定不变，
仅**落盘文件名**经 :func:`src.renderers.ttk_report.scenario_doc_stem` 中文化。
重计算耗时（束搜索），推荐在 GitHub Actions 上跑（``workflow_dispatch``）；
本地只建议 ``--render-only`` 做廉价重渲染。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

from src.engine import tiering
from src.engine.ammo_pricing import load_ammo_prices
from src.engine.game_data import DEFAULT_DATA_DIR, load_game_data
from src.engine.loadout import LoadoutSolver
from src.renderers.ttk_report import (
    BAND_ORDER,
    band_doc_name,
    main_band_doc_prefix,
    render_band_doc,
    render_gunsmith_guide,
    render_readme,
    scenario_doc_stem,
)

logger = logging.getLogger(__name__)

# 主榜情景：官方默认情景（defaultScenarioId）
MAIN_SCENARIO = "armor-5-ammo-5-default"

#: 弹药当日价表（由 src.collectors.ammo_price_sync 每日自动抓取维护，与 data/game/* 物理隔离）
AMMO_PRICE_TABLE = "data/reference/ammo_prices.json"

# 产物目录（生成产物中文化；data/game/ 官方源数据保持上游原名，勿动）
DOCS_SCENARIO_DIR = os.path.join("docs", "榜单")
DATA_SCENARIO_DIR = os.path.join("data", "榜单")
GUNSMITH_GUIDE_PATH = os.path.join("docs", "改枪指南.md")

# 默认出榜情景（口径已确认）：甲弹组合不含 3 级弹（3-3 / 4-3 不做）；
# 命中分布只用实战预设 default（center / chest-only 为官方理论聚焦预设，需 --all 才出）。
DEFAULT_SCENARIOS: tuple = (
    "armor-4-ammo-4-default",
    "armor-4-ammo-5-default",
    "armor-5-ammo-4-default",
    "armor-5-ammo-5-default",
    "armor-6-ammo-5-default",
)


SLOT_ZH = {
    "barrel": "枪管件",
    "muzzle": "枪口件",
    "foregrip": "前握把件",
    "rearGrip": "后握把件",
    "stock": "枪托件",
    "handguard": "护木件",
    "magazine": "弹匣件",
    "scope": "瞄准镜件",
    "gasSystem": "导气件",
    "functional": "功能件",
    "bolt": "枪机件",
    "trigger": "扳机件",
}


def _part_names(game_data: Any) -> Dict[str, str]:
    """构造 item_id → 展示名。

    官方数据集里约有 355 个配件（多为原厂内置件）没有本地化名称，同步层以
    「内部配件 <id>」兜底。这里改用**槽位名**兜底，至少能告诉玩家它装在哪个位置。
    """
    names: Dict[str, str] = {}
    for item_id, part in (game_data.parts or {}).items():
        name = str(part.get("name") or item_id)
        if name.startswith("内部配件 "):
            slot = str(part.get("slot") or "")
            name = f"{SLOT_ZH.get(slot, '内置件')} {item_id}"
        names[str(item_id)] = name
    return names


def _scenario_index(game_data: Any) -> List[Dict[str, Any]]:
    return [
        {
            "scenario_id": s["scenario_id"],
            "label": s.get("label") or s["scenario_id"],
            "armor_level": s.get("armor_level"),
            "ammo_level": s.get("ammo_level"),
            "probability_preset": s.get("probability_preset"),
            "helmet_durability": s.get("helmet_durability"),
            "armor_durability": s.get("armor_durability"),
        }
        for s in game_data.scenarios_raw.get("scenarios", [])
    ]


def _repo_slug() -> Optional[str]:
    """从 git remote 推导 ``owner/repo``；取不到时返回 ``None``（README 不出徽章）。"""
    import re
    import subprocess

    try:
        url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return None
    match = re.search(r"github\.com[:/](.+?)(?:\.git)?/?$", url)
    return match.group(1) if match else None


def _scenario_payload_path(output_dir: str, scenario_meta: Mapping[str, Any]) -> str:
    """情景榜单 JSON 的落盘路径（data/榜单/<中文名>.json）。"""
    return os.path.join(
        output_dir, DATA_SCENARIO_DIR, f"{scenario_doc_stem(scenario_meta)}.json"
    )


def _load_payloads_from_disk(
    output_dir: str,
    targets: Sequence[str],
    scenario_meta_all: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """``--render-only``：从已有榜单 JSON 读回 payload（缺文件则报错指路）。"""
    payloads: Dict[str, Dict[str, Any]] = {}
    for sid in targets:
        path = _scenario_payload_path(output_dir, scenario_meta_all[sid])
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"缺少 {path}：--render-only 只重渲染、不重算，"
                "请先完整跑一次管线（或在 GitHub Actions 上触发刷新）生成榜单数据"
            )
        with open(path, encoding="utf-8") as fh:
            payloads[sid] = json.load(fh)
    return payloads


def _render_outputs(
    payloads: Mapping[str, Mapping[str, Any]],
    output_dir: str,
    game_data: Any,
    part_names: Mapping[str, str],
) -> List[str]:
    """把 payload 渲染落盘：情景 JSON + 每情景 4 份距离榜 + README + 改枪指南。

    所有情景一律按距离带拆分独立榜单（主榜前缀 ``主榜``，其余用情景中文名），
    不再产出 4 带合订版。
    """
    scenario_meta_all = {s["scenario_id"]: s for s in _scenario_index(game_data)}
    files_written: List[str] = []

    for sid, payload in payloads.items():
        meta = scenario_meta_all[sid]
        prefix = main_band_doc_prefix() if sid == MAIN_SCENARIO else scenario_doc_stem(meta)

        json_path = _scenario_payload_path(output_dir, meta)
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        files_written.append(json_path)

        docs_dir = os.path.join(output_dir, DOCS_SCENARIO_DIR)
        os.makedirs(docs_dir, exist_ok=True)
        for band in BAND_ORDER:
            if band not in (payload.get("band_definitions") or {}):
                continue
            if not any(band in (w.get("bands") or {}) for w in payload["weapons"]):
                continue
            band_path = os.path.join(docs_dir, band_doc_name(prefix, band))
            with open(band_path, "w", encoding="utf-8") as fh:
                fh.write(render_band_doc(payload, band, meta, part_names, prefix=prefix))
            files_written.append(band_path)

    main_payload = payloads.get(MAIN_SCENARIO)
    if main_payload is not None:
        readme_path = os.path.join(output_dir, "README.md")
        with open(readme_path, "w", encoding="utf-8") as fh:
            fh.write(
                render_readme(
                    main_payload,
                    scenario_meta_all[MAIN_SCENARIO],
                    game_data.provenance,
                    part_names,
                    # 只索引实际生成了榜单文件的情景，避免 README 出现死链
                    scenario_index=[
                        s for s in _scenario_index(game_data) if s["scenario_id"] in payloads
                    ],
                    repo_slug=_repo_slug(),
                )
            )
        files_written.append(readme_path)

    guide_path = os.path.join(output_dir, GUNSMITH_GUIDE_PATH)
    os.makedirs(os.path.dirname(guide_path), exist_ok=True)
    with open(guide_path, "w", encoding="utf-8") as fh:
        fh.write(render_gunsmith_guide(game_data, game_data.provenance))
    files_written.append(guide_path)

    return files_written


def run_pipeline(
    output_dir: str = ".",
    scenarios: Optional[Sequence[str]] = None,
    all_scenarios: bool = False,
    limit: Optional[int] = None,
    beam_width: int = 48,
    write: bool = True,
    render_only: bool = False,
) -> Dict[str, Any]:
    """执行完整管线。

    Args:
        output_dir: 输出根目录。
        scenarios: 指定情景 ID 列表（完整 ID，如 ``armor-5-ammo-5-default``）；
            ``None`` 且 ``all_scenarios=False`` 时用 :data:`DEFAULT_SCENARIOS`。
        all_scenarios: 为全部官方情景（含 center / chest-only 理论聚焦预设）各出一份榜单。
        limit: 仅处理前 N 把枪（调试用）。
        beam_width: 起枪状态束搜索宽度（决定每枪枚举的状态数上限）。
        write: 是否写盘（False 时仅返回结果，便于测试）。
        render_only: 不重算，直接从 ``data/榜单/*.json`` 读回 payload 重渲染文档
            （束搜索耗时长，重算交给 GitHub Actions；本地只做廉价渲染）。
    """
    game_data = load_game_data(os.path.join(output_dir, DEFAULT_DATA_DIR))
    part_names = _part_names(game_data)
    scenario_meta_all = {s["scenario_id"]: s for s in _scenario_index(game_data)}

    if all_scenarios:
        targets = list(scenario_meta_all.keys())
    elif scenarios:
        targets = list(scenarios)
    else:
        targets = list(DEFAULT_SCENARIOS)
    for sid in targets:
        if sid not in scenario_meta_all:
            raise KeyError(f"未收录的情景：{sid}")

    if render_only:
        payloads = _load_payloads_from_disk(output_dir, targets, scenario_meta_all)
    else:
        price_table = load_ammo_prices(os.path.join(output_dir, AMMO_PRICE_TABLE))
        keys = [w["profile_key"] for w in game_data.weapons]
        if limit:
            keys = keys[:limit]

        payloads: Dict[str, Dict[str, Any]] = {}
        for sid in targets:
            solver = LoadoutSolver(game_data, sid)
            rankings, thresholds, excluded = tiering.rank_weapons_for_scenario(
                game_data, sid, solver=solver, beam_width=beam_width,
                profile_keys=keys, price_table=price_table,
            )
            payload = tiering.to_export(rankings, thresholds, sid, excluded, price_table=price_table)
            payloads[sid] = payload
            logger.info(
                "情景 %s 完成：可参赛 %d 把，排除 %d 把（口径无该等级弹药）",
                sid, len(rankings), len(excluded),
            )

    files_written = _render_outputs(payloads, output_dir, game_data, part_names) if write else []

    return {
        "scenarios": targets,
        "weapon_count": len(keys) if not render_only else 0,
        "payloads": payloads,
        "files_written": files_written,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="纯 TTK 枪械强度榜管线")
    parser.add_argument("--output-dir", default=".", help="输出根目录（默认当前目录）")
    parser.add_argument("--all", action="store_true", help="全部 21 个官方情景（含理论聚焦预设）")
    parser.add_argument("--scenario", default=None, help="单甲弹组合，如 5-5（用其 default 实战情景）")
    parser.add_argument("--limit", type=int, default=None, help="仅处理前 N 把枪（调试）")
    parser.add_argument("--beam-width", type=int, default=48, help="起枪状态束搜索宽度")
    parser.add_argument("--dry-run", action="store_true", help="只计算不写盘")
    parser.add_argument(
        "--render-only", action="store_true",
        help="不重算：从 data/榜单/*.json 读回榜单数据，只重渲染全部文档（本地廉价刷新）",
    )
    args = parser.parse_args()

    scenarios = None
    if args.scenario:
        armor, ammo = args.scenario.split("-")
        scenarios = [f"armor-{armor}-ammo-{ammo}-default"]

    result = run_pipeline(
        output_dir=args.output_dir,
        scenarios=scenarios,
        all_scenarios=args.all,
        limit=args.limit,
        beam_width=args.beam_width,
        write=not args.dry_run,
        render_only=args.render_only,
    )
    print(
        f"完成：情景 {len(result['scenarios'])} 个，武器 {result['weapon_count']} 把，"
        f"写出 {len(result['files_written'])} 个文件"
    )


if __name__ == "__main__":
    main()
