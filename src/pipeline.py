"""纯 TTK 榜单管线：官方数据 → 最优配装求解 → 分层 → 渲染 → 导出。

用法::

    python -m src.pipeline                      # 默认 5 个情景（见 DEFAULT_SCENARIOS）
    python -m src.pipeline --all                # 全部 21 个官方情景（含理论聚焦预设）
    python -m src.pipeline --scenario 5-5       # 单个甲弹组合的实战情景
    python -m src.pipeline --limit 8            # 快速冒烟（前 8 把枪）
    python -m src.pipeline --render-only        # 不重算，从已有榜单 JSON 重渲染文档
    python -m src.pipeline --price-only         # 不重算 TTK：只刷新价格列并重渲染文档
    python -m src.pipeline --check-stale        # 校验 TTK 输入指纹（不一致退出 1，CI 条件重算入口）

输出：

- ``data/榜单/护甲X弹药Y-<预设>.json`` —— 机器可读榜单（含层级阈值）
- ``docs/榜单/<情景名>-<距离带>.md`` —— 每情景 4 份独立距离榜（主榜前缀 ``主榜``）
- ``README.md`` —— 首页：口径 + 主榜速览（每带 Top 5）+ 导航
- ``docs/改枪指南.md`` —— 改枪指南（不进 TTK 的维度）

内部 ``scenario_id``（如 ``armor-5-ammo-5-default``）保持英文稳定不变，
仅**落盘文件名**经 :func:`src.renderers.ttk_report.scenario_doc_stem` 中文化。
重计算耗时（束搜索），CI 按 :func:`compute_inputs_fingerprint` 条件触发：
``--check-stale`` 新鲜时短路跳过重算，只跑 ``--price-only`` 刷新每日价格列；
本地只建议 ``--render-only`` / ``--price-only`` 做廉价刷新。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from src.engine import ranking, tierlist_export
from src.engine.ammo_pricing import load_ammo_prices
from src.engine.game_data import DEFAULT_DATA_DIR, load_game_data
from src.engine.loadout import LoadoutSolver
from src.engine.tiering import (
    SPARE_AMMO_ROUNDS,
    compute_full_price,
    compute_kill_cost,
)
from src.engine.weapon_pricing import load_weapon_prices
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

#: 枪械本体裸枪当日价表（由 src.collectors.weapon_price_sync 每日自动抓取维护，与弹药价同源同频率）
WEAPON_PRICE_TABLE = "data/reference/weapon_prices.json"

# 产物目录（生成产物中文化；data/game/ 官方源数据保持上游原名，勿动）
DOCS_SCENARIO_DIR = os.path.join("docs", "榜单")
DATA_SCENARIO_DIR = os.path.join("data", "榜单")
GUNSMITH_GUIDE_PATH = os.path.join("docs", "改枪指南.md")

# TTK 数据指纹的输入域（相对 output_dir 的 POSIX 路径段）：决定 TTK 数值的一切输入。
# 价格表（data/reference/*）**不在**指纹内——它们每日变动，只触发价格列刷新，
# 不应触发束搜索重算（这是 --check-stale 短路跳过重算的前提）。
FINGERPRINT_TABLES_DIR = ("data", "tables")
FINGERPRINT_ENGINE_DIR = ("src", "engine")
FINGERPRINT_PIPELINE_FILE = ("src", "pipeline.py")

#: 榜单 JSON 顶层记录输入指纹的键名
INPUTS_FINGERPRINT_KEY = "inputs_fingerprint"

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


def compute_inputs_fingerprint(output_dir: str = ".") -> str:
    """计算 TTK 榜单输入的数据指纹（SHA256 十六进制串）。

    指纹覆盖 :data:`FINGERPRINT_TABLES_DIR` 下**全部文件内容**、
    :data:`FINGERPRINT_ENGINE_DIR` 各 ``*.py`` 与 :data:`FINGERPRINT_PIPELINE_FILE`
    的内容——即决定 TTK 数值的一切输入；每日变动的价格表不在其中。

    稳定性约定：相对路径按 ``/`` 归一并参与哈希（按路径排序后拼接），文件按
    **字节**读入；配合仓库 ``* text=auto eol=lf`` 策略，Windows 与 Linux 产物
    指纹一致。
    """
    root = Path(output_dir)
    rel_paths: List[Path] = []
    tables_dir = root.joinpath(*FINGERPRINT_TABLES_DIR)
    if tables_dir.is_dir():
        rel_paths.extend(p for p in tables_dir.rglob("*") if p.is_file())
    engine_dir = root.joinpath(*FINGERPRINT_ENGINE_DIR)
    if engine_dir.is_dir():
        rel_paths.extend(p for p in engine_dir.glob("*.py"))
    pipeline_file = root.joinpath(*FINGERPRINT_PIPELINE_FILE)
    if pipeline_file.is_file():
        rel_paths.append(pipeline_file)

    digest = hashlib.sha256()
    for rel in sorted((p.relative_to(root) for p in rel_paths), key=lambda p: p.as_posix()):
        digest.update(rel.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / rel).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _scan_ranking_files(output_dir: str) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """扫描 ``data/榜单/*.json``，按 payload 自报的 ``scenario_id`` 建索引。

    返回 ``{scenario_id: (文件路径, payload)}``；目录缺失返回空表。
    按 payload 内部 ``scenario_id``（而非文件名推导）索引，使 ``--price-only``
    与 ``--check-stale`` 无需加载官方数据即可定位产物。
    """
    ranking_dir = os.path.join(output_dir, DATA_SCENARIO_DIR)
    if not os.path.isdir(ranking_dir):
        return {}
    index: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for name in sorted(os.listdir(ranking_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(ranking_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError) as exc:
            logger.warning("榜单 JSON 无法读取（%s）：%s", path, exc)
            continue
        sid = payload.get("scenario_id") if isinstance(payload, dict) else None
        if sid:
            index[str(sid)] = (path, payload)
    return index


def _load_payloads_from_disk(
    output_dir: str,
    targets: Sequence[str],
    scenario_meta_all: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """``--render-only``：从已有榜单 JSON 读回 payload（缺文件则报错指路）。"""
    current_fp = compute_inputs_fingerprint(output_dir)
    payloads: Dict[str, Dict[str, Any]] = {}
    for sid in targets:
        path = _scenario_payload_path(output_dir, scenario_meta_all[sid])
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"缺少 {path}：--render-only 只重渲染、不重算，"
                "请先完整跑一次管线（或在 GitHub Actions 上触发刷新）生成榜单数据"
            )
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        recorded = payload.get(INPUTS_FINGERPRINT_KEY)
        if not recorded:
            logger.warning(
                "情景 %s：榜单 JSON（%s）无输入指纹（旧产物），无法校验文档与数据是否同步",
                sid, path,
            )
        elif recorded != current_fp:
            logger.warning(
                "情景 %s：榜单 JSON（%s）输入指纹与当前不一致——TTK 输入已变化，"
                "文档可能与数据不同步，建议尽快全量重算",
                sid, path,
            )
        payloads[sid] = payload
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
        Path(json_path).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        files_written.append(json_path)

        docs_dir = os.path.join(output_dir, DOCS_SCENARIO_DIR)
        os.makedirs(docs_dir, exist_ok=True)
        for band in BAND_ORDER:
            if band not in (payload.get("band_definitions") or {}):
                continue
            if not any(band in (w.get("bands") or {}) for w in payload["weapons"]):
                continue
            band_path = os.path.join(docs_dir, band_doc_name(prefix, band))
            Path(band_path).write_text(render_band_doc(payload, band, meta, part_names, prefix=prefix), encoding="utf-8", newline="\n")
            files_written.append(band_path)

    main_payload = payloads.get(MAIN_SCENARIO)
    if main_payload is not None:
        readme_path = os.path.join(output_dir, "README.md")
        Path(readme_path).write_text(
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
            ),
            encoding="utf-8",
            newline="\n",
        )
        files_written.append(readme_path)

    guide_path = os.path.join(output_dir, GUNSMITH_GUIDE_PATH)
    os.makedirs(os.path.dirname(guide_path), exist_ok=True)
    Path(guide_path).write_text(render_gunsmith_guide(game_data, game_data.provenance), encoding="utf-8", newline="\n")
    files_written.append(guide_path)

    return files_written


def _compute_scenario(args: tuple) -> tuple:
    """单情景完整计算（供串行/并行两路复用；子进程内自带数据加载）。"""
    sid, output_dir, keys, beam_width = args
    game_data = load_game_data(os.path.join(output_dir, DEFAULT_DATA_DIR))
    price_table = load_ammo_prices(os.path.join(output_dir, AMMO_PRICE_TABLE))
    weapon_price_table = load_weapon_prices(os.path.join(output_dir, WEAPON_PRICE_TABLE))
    solver = LoadoutSolver(game_data, sid)
    rankings, thresholds, excluded = ranking.rank_weapons_for_scenario(
        game_data, sid, solver=solver, beam_width=beam_width,
        profile_keys=keys, price_table=price_table,
        weapon_price_table=weapon_price_table,
    )
    payload = tierlist_export.to_export(
        rankings, thresholds, sid, excluded,
        price_table=price_table, weapon_price_table=weapon_price_table,
    )
    return sid, payload, len(rankings), len(excluded)


def refresh_payload_prices(
    payload: Dict[str, Any],
    ammo_table: Any,
    weapon_table: Any,
) -> None:
    """就地刷新 payload 的价格相关字段（纯函数，CLI 与测试共用）；TTK 字段一律不动。

    刷新范围（与全量重算 ``to_export`` 的序列化形状同构）：

    - 顶层 ``ammo_price_meta`` / ``weapon_price_meta``（币种 / 窗口 / 更新时间 / 可用性）；
    - 每状态行 ``ammo.price_daily``、``gun_price_daily``、``full_price_180rd``；
    - 每带 ``kill_cost``。

    计算口径与 :mod:`src.engine.tiering` 完全一致——直接复用
    :func:`src.engine.tiering.compute_kill_cost` 与
    :func:`src.engine.tiering.compute_full_price`，禁止复刻公式。
    缺价一律置 ``None``（引擎"不猜测、不兜底"口径）；``inputs_fingerprint``
    **不改动**——价格刷新不代表 TTK 输入新鲜，是否过期由 ``--check-stale`` 判定。
    """
    payload["ammo_price_meta"] = {
        "currency": ammo_table.currency,
        "window": dict(ammo_table.window),
        "updated_at": ammo_table.updated_at,
        "available": not ammo_table.is_empty,
    }
    payload["weapon_price_meta"] = {
        "currency": weapon_table.currency,
        "window": dict(weapon_table.window),
        "updated_at": weapon_table.updated_at,
        "available": not weapon_table.is_empty,
        "spare_ammo_rounds": SPARE_AMMO_ROUNDS,
    }
    for row in payload.get("weapons") or []:
        ammo = row.get("ammo") or {}
        ammo_price = ammo_table.price_for(str(ammo.get("ammo_item_id") or ""))
        # 变体/改装状态行与本体共用裸枪价（weapon_id 即本体主键，见 ranking 层口径）
        gun_price = weapon_table.price_for(str(row.get("weapon_id") or ""))
        ammo["price_daily"] = ammo_price
        row["gun_price_daily"] = gun_price
        row["full_price_180rd"] = compute_full_price(gun_price, ammo_price)
        for band in (row.get("bands") or {}).values():
            band["kill_cost"] = compute_kill_cost(band.get("mean_expected_shots"), ammo_price)


def refresh_prices(
    output_dir: str = ".",
    scenarios: Optional[Sequence[str]] = None,
    all_scenarios: bool = False,
    write: bool = True,
) -> Dict[str, Any]:
    """轻量价格刷新（``--price-only``）：只重算价格列并重渲染文档，不重算 TTK。

    读取现有 ``data/榜单/*.json``，用当前价格表刷新各状态行价格字段后重写
    JSON，并经既有渲染层重出 ``docs/榜单/*.md`` 与 ``README.md``（与全量重算
    产物同构）。某情景 JSON 缺失或无 ``inputs_fingerprint``（旧产物）时报错
    跳过——需先全量重算一次；其余 TTK 字段（mean/worst/expected_shots 等）
    一律保持原值不动。
    """
    ammo_table = load_ammo_prices(os.path.join(output_dir, AMMO_PRICE_TABLE))
    weapon_table = load_weapon_prices(os.path.join(output_dir, WEAPON_PRICE_TABLE))
    index = _scan_ranking_files(output_dir)

    if all_scenarios:
        targets = sorted(index)
    elif scenarios:
        targets = list(scenarios)
    else:
        targets = list(DEFAULT_SCENARIOS)

    payloads: Dict[str, Dict[str, Any]] = {}
    skipped: List[str] = []
    for sid in targets:
        found = index.get(sid)
        if found is None:
            logger.error(
                "情景 %s 缺少榜单 JSON（data/榜单/）：--price-only 不重算 TTK，"
                "请先全量重算（python -m src.pipeline）",
                sid,
            )
            skipped.append(sid)
            continue
        path, payload = found
        if not payload.get(INPUTS_FINGERPRINT_KEY):
            logger.error(
                "情景 %s 的榜单 JSON（%s）无输入指纹（旧产物）："
                "请先全量重算一次以写入指纹，本次跳过该情景",
                sid, path,
            )
            skipped.append(sid)
            continue
        refresh_payload_prices(payload, ammo_table, weapon_table)
        payloads[sid] = payload

    files_written: List[str] = []
    if write and payloads:
        game_data = load_game_data(os.path.join(output_dir, DEFAULT_DATA_DIR))
        meta_all = {s["scenario_id"]: s for s in _scenario_index(game_data)}
        renderable = {sid: p for sid, p in payloads.items() if sid in meta_all}
        for sid in sorted(set(payloads) - set(renderable)):
            logger.warning("情景 %s 不在官方情景索引中，无法渲染，跳过写盘", sid)
        if renderable:
            files_written = _render_outputs(
                renderable, output_dir, game_data, _part_names(game_data),
            )

    return {
        "scenarios": targets,
        "refreshed": sorted(payloads),
        "skipped": skipped,
        "payloads": payloads,
        "files_written": files_written,
    }


def check_stale(
    output_dir: str = ".",
    scenarios: Optional[Sequence[str]] = None,
    all_scenarios: bool = False,
) -> List[str]:
    """比较当前输入指纹与榜单 JSON 记录的指纹，返回需重算的原因列表（空 = 新鲜）。

    - 情景榜单 JSON 缺失 → 过期；
    - JSON 无 ``inputs_fingerprint``（旧产物）→ 过期（首次上线触发一次全量重算，属预期）；
    - 指纹与 :func:`compute_inputs_fingerprint` 当前值不一致 → 过期；
    - 全部一致 → 新鲜（CI 短路跳过束搜索重算）。

    检查范围与全量重算的产出范围一致：显式 ``scenarios`` 或
    :data:`DEFAULT_SCENARIOS`；``all_scenarios=True`` 时覆盖 data/榜单/ 全部产物。
    """
    index = _scan_ranking_files(output_dir)
    if all_scenarios:
        targets = sorted(index)
    elif scenarios:
        targets = list(scenarios)
    else:
        targets = list(DEFAULT_SCENARIOS)

    current_fp = compute_inputs_fingerprint(output_dir)
    reasons: List[str] = []
    for sid in targets:
        found = index.get(sid)
        if found is None:
            reasons.append(f"{sid}: 缺少榜单 JSON（data/榜单/）")
            continue
        path, payload = found
        recorded = payload.get(INPUTS_FINGERPRINT_KEY)
        if not recorded:
            reasons.append(f"{sid}: {path} 无输入指纹（旧产物）")
        elif recorded != current_fp:
            reasons.append(f"{sid}: {path} 指纹与当前输入不一致")
    return reasons


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

    多情景重算按情景粒度并行（每情景相互独立，worker 各自加载数据）；
    单情景或 limit 调试模式直接串行，省去进程开销。
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
        keys_count = 0
    else:
        keys = [w["profile_key"] for w in game_data.weapons]
        if limit:
            keys = keys[:limit]
        keys_count = len(keys)

        jobs = [(sid, output_dir, keys, beam_width) for sid in targets]
        payloads: Dict[str, Dict[str, Any]] = {}
        if len(jobs) == 1:
            results = [_compute_scenario(jobs[0])]
        else:
            from concurrent.futures import ProcessPoolExecutor

            workers = min(len(jobs), os.cpu_count() or 1)
            logger.info("情景并行计算：%d 个情景 × %d 进程", len(jobs), workers)
            with ProcessPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(_compute_scenario, jobs))
        for sid, payload, n_ranked, n_excluded in results:
            payloads[sid] = payload
            logger.info(
                "情景 %s 完成：可参赛 %d 把，排除 %d 把（口径无该等级弹药）",
                sid, n_ranked, n_excluded,
            )
        # 全量重算：把当前输入指纹写入每个榜单 JSON 顶层，供 --check-stale / --price-only 判定
        fingerprint = compute_inputs_fingerprint(output_dir)
        for payload in payloads.values():
            payload[INPUTS_FINGERPRINT_KEY] = fingerprint

    files_written = _render_outputs(payloads, output_dir, game_data, part_names) if write else []

    return {
        "scenarios": targets,
        "weapon_count": keys_count,
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
    parser.add_argument(
        "--price-only", action="store_true",
        help="不重算 TTK：用当前价格表刷新榜单价格列（击杀成本/起枪价）并重出文档",
    )
    parser.add_argument(
        "--check-stale", action="store_true",
        help="只校验 TTK 输入指纹：全部一致退出 0（新鲜），任一不一致或 JSON 缺失退出 1（需重算）",
    )
    args = parser.parse_args()

    scenarios = None
    if args.scenario:
        armor, ammo = args.scenario.split("-")
        scenarios = [f"armor-{armor}-ammo-{ammo}-default"]

    if args.check_stale:
        reasons = check_stale(
            output_dir=args.output_dir, scenarios=scenarios, all_scenarios=args.all,
        )
        if reasons:
            for reason in reasons:
                print(f"需重算：{reason}")
            sys.exit(1)
        print("TTK 输入指纹全部一致，榜单新鲜（跳过重算）")
        return

    if args.price_only:
        result = refresh_prices(
            output_dir=args.output_dir,
            scenarios=scenarios,
            all_scenarios=args.all,
            write=not args.dry_run,
        )
        print(
            f"价格刷新完成：刷新情景 {len(result['refreshed'])} 个，"
            f"跳过 {len(result['skipped'])} 个（缺 JSON 或无指纹，需全量重算），"
            f"写出 {len(result['files_written'])} 个文件"
        )
        if not result["refreshed"]:
            sys.exit(1)
        return

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
