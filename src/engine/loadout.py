"""配装枚举与最优精校求解（Task #3）。

目标：在官方插槽规则下枚举**合法**配装，并对每套配装求解**最优精校**，
使给定情景与距离口径下的实战 TTK 最小。

两个关键事实决定本模块的设计：

1. **只有少数插槽影响 TTK**。瞄准镜（瞳距/缩放）、弹匣、握把等只影响与击杀时间无关的量，
   一律固定为默认件，枚举空间因此指数级缩小。判定依据是配件的 ``effects`` / ``tunes.functions``
   是否触及 TTK 相关规则目标（开镜时间、射速、弹道/伤害档案、优势射程等）。
2. **精校曲线是分段线性的**（``RCIM_Linear``），每个滑块的最优取值必落在曲线控制点
   （``min`` / ``default`` / ``max``）上，因此滑块从「101 档」降为「≤3 个断点」，
   无需网格搜索。

插入式插槽（``provider_sockets``）只有在提供者配件被装载后才可选，故枚举按「根插槽 →
暴露出的插入插槽」分层进行，并对每层做束搜索（beam search）控制规模。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from src.engine import engagement as eg

# --------------------------------------------------------------------------- #
# 影响 TTK 的规则目标
# --------------------------------------------------------------------------- #
# TTK = (E[N] − 1) × 射击间隔，**不含开镜时间**（开镜是交战准备而非击杀过程）。
# 因此影响 TTK 的只有两类：改变 E[N]（伤害/弹道/有效射程）与改变射击间隔（射速）。
TTK_ATTR_INDEXES = frozenset({"2"})  # 2 = 优势射程（驱动伤害衰减分段缩放 → 改变 E[N]）

TTK_RULE_TARGETS = frozenset(
    {
        "GRateOfFire",
        "FireInterval",
        "FireCD",
        "FireRateMode",
        "FireDelayTime",
        "GFiremode",
        "ProjectileNumPerShot",
        "GBullet_Range",
        "GRange_OnlySpeed",
        "GBullet_OnlyRange",
    }
)
# 不纳入的项（均已在 engagement 模块的口径表中说明）：
# - ``GAiming_ADSTime``：开镜时间不进 TTK
# - ``GBullet_Velocity``：初速不进 TTK，其「长度」精校交由玩家自行权衡
# - 换弹（``ChangeClipTime`` / ``GReload_Time``）：官方击杀假设 ``singleMagazineNoReload``
TTK_RULE_PREFIXES = ("BulletFlyingId", "AttackerValueId")
_ATTR_PREFIXES = ("DisplayAttrValues.", "WeaponMainAttribute.MainAttrValues.")


def target_affects_ttk(target: Optional[str]) -> bool:
    """目标是否改变 TTK（射速 / 弹道与伤害档案 / 优势射程）。"""
    if not target:
        return False
    if target in TTK_RULE_TARGETS:
        return True
    if any(target == prefix or target.startswith(prefix + ".") for prefix in TTK_RULE_PREFIXES):
        return True
    for prefix in _ATTR_PREFIXES:
        if target.startswith(prefix):
            return target.rsplit(".", 1)[-1] in TTK_ATTR_INDEXES
    return False


def effect_affects_ttk(effect: Mapping[str, Any]) -> bool:
    """``effects`` 条目是否改变 TTK。

    零效果（``Mult_A/Mult_C 0``、``Addend 0``）一律忽略——大量配件会挂
    ``DisplayAttrValues.2 Mult_A 0.0`` 之类的占位声明，若不过滤会让枚举空间虚高。
    """
    target = effect.get("target")
    if not target_affects_ttk(target):
        return False
    if effect.get("modifier") == "Initial":
        return True
    value = effect.get("value")
    if value is None:
        return False
    try:
        return abs(float(value)) > 1e-12
    except (TypeError, ValueError):
        return False


def part_affects_ttk(part: Optional[Mapping[str, Any]]) -> bool:
    """配件是否在 TTK 相关目标上产生**有效**效果。"""
    if not part:
        return False
    for effect in part.get("effects") or []:
        if effect_affects_ttk(effect):
            return True
    for tune in part.get("tunes") or []:
        for func in tune.get("functions") or []:
            if target_affects_ttk(func.get("target")):
                return True
    return False


# --------------------------------------------------------------------------- #
# 插槽规格
# --------------------------------------------------------------------------- #
@dataclass
class SocketSpec:
    """一个参与枚举的插槽。``providers`` 为空表示根插槽（始终可选）。"""

    socket_id: str
    options: List[str]
    providers: Dict[str, List[str]] = field(default_factory=dict)  # provider_item_id -> options

    def options_for(self, mounted_items: Iterable[str]) -> Optional[List[str]]:
        """给定已装件，返回该插槽当前可选项；不可用返回 ``None``。"""
        if not self.providers:
            return self.options
        mounted = set(mounted_items)
        merged: List[str] = []
        seen = set()
        for provider, opts in self.providers.items():
            if provider not in mounted:
                continue
            for item in opts:
                if item not in seen:
                    seen.add(item)
                    merged.append(item)
        return merged or None


def _prune_options(
    game_data: Any,
    options: List[str],
    default_item: Optional[str],
    include_non_ttk: bool,
) -> List[str]:
    """只保留直接影响 TTK 的选项，并保证默认件在内（否则最优可能被剪掉）。"""
    if include_non_ttk:
        return list(options)
    kept: List[str] = []
    seen = set()
    for item in options:
        if item in seen or not part_affects_ttk(game_data.get_part(item)):
            continue
        seen.add(item)
        kept.append(item)
    if default_item and default_item not in seen:
        kept.insert(0, default_item)
    return kept


def build_socket_specs(
    game_data: Any, weapon: Mapping[str, Any], include_non_ttk: bool = False
) -> List[SocketSpec]:
    """构造参与枚举的插槽计划：先根插槽，后插入式插槽。

    选项按「直接影响 TTK」剪枝；剪枝后只剩单一选项的插槽不参与枚举（无搜索价值）。
    """
    defaults = {str(k): str(v) for k, v in (weapon.get("default_items") or {}).items()}
    variant_item = str(weapon.get("variant_item_id")) if weapon.get("variant_item_id") else None

    root: List[SocketSpec] = []
    for socket in weapon.get("sockets") or []:
        socket_id = str(socket.get("socket_id"))
        options = _prune_options(
            game_data, [str(o) for o in (socket.get("options") or [])], defaults.get(socket_id), include_non_ttk
        )
        if len(options) <= 1 and not include_non_ttk:
            continue
        root.append(SocketSpec(socket_id=socket_id, options=options))

    root_ids = {spec.socket_id for spec in root}
    inserts: Dict[str, Dict[str, List[str]]] = {}
    for provider_id, sockets in (weapon.get("provider_sockets") or {}).items():
        for socket in sockets:
            socket_id = str(socket.get("socket_id"))
            if socket_id in root_ids:
                continue
            options = _prune_options(
                game_data,
                [str(o) for o in (socket.get("options") or [])],
                defaults.get(socket_id),
                include_non_ttk,
            )
            if len(options) <= 1 and not include_non_ttk:
                continue
            inserts.setdefault(socket_id, {})[str(provider_id)] = options

    specs = list(root)
    for socket_id, providers in inserts.items():
        all_options: List[str] = []
        seen = set()
        for opts in providers.values():
            for item in opts:
                if item not in seen:
                    seen.add(item)
                    all_options.append(item)
        specs.append(SocketSpec(socket_id=socket_id, options=all_options, providers=providers))
    return specs


# --------------------------------------------------------------------------- #
# 精校断点
# --------------------------------------------------------------------------- #
def tuning_breakpoints(part: Mapping[str, Any], tune: Mapping[str, Any]) -> List[float]:
    """滑块的最优候选值：曲线控制点 ∪ {min, default, max}（分段线性 ⇒ 最优在断点）。"""
    values = {
        float(tune.get("min_value") or 0.0),
        float(tune.get("max_value") or 0.0),
        float(tune.get("default_value") or 0.0),
    }
    for func in tune.get("functions") or []:
        for point in func.get("curve") or []:
            try:
                values.add(float(point[0]))
            except (TypeError, ValueError, IndexError):
                continue
    low = float(tune.get("min_value") or 0.0)
    high = float(tune.get("max_value") or 0.0)
    return sorted(v for v in values if low - 1e-9 <= v <= high + 1e-9)


def ttk_tuning_dims(game_data: Any, loadout: Mapping[str, str]) -> List[Tuple[str, str, List[float]]]:
    """列出该配装下所有**影响 TTK** 的精校维度及其断点。"""
    dims: List[Tuple[str, str, List[float]]] = []
    for item_id in loadout.values():
        part = game_data.get_part(item_id)
        if not part:
            continue
        for tune in part.get("tunes") or []:
            if not any(target_affects_ttk(f.get("target")) for f in (tune.get("functions") or [])):
                continue
            dims.append((str(item_id), str(tune["tune_id"]), tuning_breakpoints(part, tune)))
    return dims


# --------------------------------------------------------------------------- #
# 求解
# --------------------------------------------------------------------------- #
DEFAULT_COARSE_DISTANCES: Tuple[float, ...] = (0.0, 40.0, 80.0)


@dataclass
class LoadoutSolution:
    profile_key: str
    scenario_id: str
    loadout: Dict[str, str]
    tuning: Dict[str, Dict[str, float]]
    curve: List[eg.TtkResult]
    score_seconds: Optional[float] = None

    @property
    def band_ms(self) -> Dict[str, Dict[str, float]]:
        return eg.band_summary(self.curve)

    @property
    def ttk_at_0m_ms(self) -> float:
        return self.curve[0].ttk_milliseconds

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "scenario_id": self.scenario_id,
            "loadout": self.loadout,
            "tuning": self.tuning,
            "ttk_at_0m_ms": round(self.ttk_at_0m_ms, 2),
            "bands": self.band_ms,
        }


class LoadoutSolver:
    """在官方插槽规则下搜索「配装 + 精校」的最优实战 TTK。"""

    def __init__(self, game_data: Any, scenario_id: str, mode: str = "sol", resolver: Any = None):
        from src.engine.weapon_state import WeaponStateResolver

        self.gd = game_data
        self.scenario_id = scenario_id
        self.scenario = eg.resolve_scenario(game_data, scenario_id)
        self.armor = eg.scenario_armor(game_data, self.scenario)
        self.probabilities = self.scenario["hit_probabilities"]
        self.resolver = resolver or WeaponStateResolver(game_data, mode)
        self._ammo_cache: Dict[str, Mapping[str, Any]] = {}

    # ------------------------------------------------------------------ #
    def ammo_for(self, profile_key: str) -> Mapping[str, Any]:
        if profile_key not in self._ammo_cache:
            self._ammo_cache[profile_key] = eg.pick_ammo(self.gd, profile_key, self.scenario["ammo_level"])
        return self._ammo_cache[profile_key]

    def _mounted(self, profile_key: str, loadout: Mapping[str, str]) -> Dict[str, str]:
        weapon = self.gd.get_weapon(profile_key)
        mounted, _ = self.resolver._build_loadout(weapon, loadout)
        return mounted

    def _band_score(
        self,
        profile_key: str,
        loadout: Mapping[str, str],
        tuning: Optional[Mapping[str, Mapping[str, float]]],
        distances: Sequence[float],
    ) -> float:
        state = self.resolver.resolve(profile_key, loadout=loadout, tuning=tuning)
        ammo = self.ammo_for(profile_key)
        total = 0.0
        for d in distances:
            total += eg.ttk_at(state, ammo, self.armor, self.probabilities, d).ttk_seconds
        return total / len(distances)

    # ------------------------------------------------------------------ #
    def enumerate_loadouts(
        self,
        profile_key: str,
        beam_width: int = 48,
        distances: Sequence[float] = DEFAULT_COARSE_DISTANCES,
    ) -> List[Dict[str, str]]:
        """束搜索枚举合法配装（只展开影响 TTK 的插槽）。"""
        weapon = self.gd.get_weapon(profile_key)
        specs = build_socket_specs(self.gd, weapon)
        beam: List[Dict[str, str]] = [{}]
        beam_scores: List[float] = [self._band_score(profile_key, {}, None, distances)]

        for spec in specs:
            expanded: Dict[Tuple[Tuple[str, str], ...], Tuple[Dict[str, str], float]] = {}
            for loadout in beam:
                mounted = self._mounted(profile_key, loadout)
                options = spec.options_for(mounted.values())
                choices: List[Optional[str]] = list(options) if options else []
                choices.append(None)  # 允许不装（回落到默认件）
                for item in choices:
                    trial = dict(loadout)
                    if item is None:
                        trial.pop(spec.socket_id, None)
                    else:
                        trial[spec.socket_id] = item
                    # 以 resolver 实际装机结果去重（coupling forced 会改写选择）
                    actual = self._mounted(profile_key, trial)
                    key = tuple(sorted(actual.items()))
                    if key in expanded:
                        continue
                    expanded[key] = (trial, self._band_score(profile_key, trial, None, distances))
            ranked = sorted(expanded.values(), key=lambda pair: pair[1])[:beam_width]
            beam = [loadout for loadout, _ in ranked]
            beam_scores = [score for _, score in ranked]
        return beam

    # ------------------------------------------------------------------ #
    def solve_tuning(
        self,
        profile_key: str,
        loadout: Mapping[str, str],
        distances: Sequence[float] = DEFAULT_COARSE_DISTANCES,
        max_rounds: int = 3,
    ) -> Tuple[Dict[str, Dict[str, float]], float]:
        """坐标下降求最优精校（每维只在曲线断点上取值）。"""
        dims = ttk_tuning_dims(self.gd, self._mounted(profile_key, loadout))
        tuning: Dict[str, Dict[str, float]] = {}
        best = self._band_score(profile_key, loadout, tuning, distances)
        for _ in range(max_rounds):
            improved = False
            for item_id, tune_id, breakpoints in dims:
                for value in breakpoints:
                    trial = {k: dict(v) for k, v in tuning.items()}
                    trial.setdefault(item_id, {})[tune_id] = value
                    score = self._band_score(profile_key, loadout, trial, distances)
                    if score < best - 1e-9:
                        best = score
                        tuning = trial
                        improved = True
            if not improved:
                break
        return tuning, best

    # ------------------------------------------------------------------ #
    def solve(
        self,
        profile_key: str,
        beam_width: int = 6,
        top_k: int = 4,
        final_distances: Optional[Sequence[float]] = None,
    ) -> LoadoutSolution:
        """返回该枪在当前情景下的最优解（最优配装 + 最优精校）。

        两阶段评分：粗筛用少量距离点对候选排序并选优，**只对最终最优解**计算完整距离曲线
        （81 个距离点的 DP 是本流程最重的开销，避免对每个候选重复计算）。
        """
        coarse = DEFAULT_COARSE_DISTANCES
        if final_distances is None:
            final_distances = tuple(float(d) for d in range(0, int(eg.DISTANCE_MAX) + 1))

        candidates = self.enumerate_loadouts(profile_key, beam_width=beam_width, distances=coarse)
        if not candidates:
            candidates = [{}]
        ranked = sorted(
            candidates, key=lambda lo: (self._band_score(profile_key, lo, None, coarse), len(lo))
        )[:top_k]

        best_score: Optional[float] = None
        best_loadout: Dict[str, str] = {}
        best_tuning: Dict[str, Dict[str, float]] = {}
        for loadout in ranked:
            tuning, score = self.solve_tuning(profile_key, loadout, coarse)
            # 并列时优先配件更少（更贴近默认）的方案
            if best_score is None or score < best_score - 1e-9 or (
                abs(score - best_score) <= 1e-9 and len(loadout) < len(best_loadout)
            ):
                best_score = score
                best_loadout = loadout
                best_tuning = tuning

        state = self.resolver.resolve(profile_key, loadout=best_loadout, tuning=best_tuning)
        ammo = self.ammo_for(profile_key)
        curve = eg.ttk_curve(state, ammo, self.armor, self.probabilities, final_distances)
        return LoadoutSolution(
            profile_key=profile_key,
            scenario_id=self.scenario_id,
            loadout=best_loadout,
            tuning=best_tuning,
            curve=curve,
            score_seconds=best_score,
        )

