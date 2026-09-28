"""配装枚举（Task #3）。

目标：在官方插槽规则下枚举**合法**配装，使给定情景与距离口径下的实战 TTK 最小。

关键事实决定本模块的设计：

**只有少数插槽影响 TTK**。瞄准镜（瞳距/缩放）、弹匣、握把等只影响与击杀时间无关的量，
一律固定为默认件，枚举空间因此指数级缩小。判定依据是配件的 ``effects`` / ``tunes.functions``
是否触及 TTK 相关规则目标（开镜时间、射速、弹道/伤害档案、优势射程等）。

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


# --------------------------------------------------------------------------- #
# 赛季限时件（绝版）排除表
# --------------------------------------------------------------------------- #
# 哈夫克军工「限时武器改件」按赛季轮换：活动凭证兑换、配件自带 30 天有效期，
# 赛季结束后无法获取。上游 dfttk published data 只含游戏内配件定义、不含获取渠道，
# 若不过滤，配装搜索会选中这些已绝版件，导致榜单最优 TTK 在新赛季不可达成。
# 维护方式：每赛季对照官方更新公告核对本清单（S11 起）。
EXCLUDED_PART_IDS: frozenset = frozenset(
    {
        "13020000590",  # M249 H.A.V.K 链锯套件（S9「回声」限时）
        "13020000595",  # MP7 H.A.V.K 格斗套件（S9「回声」限时）
        "13020000603",  # ASh-12 HVK 双发枪管（S10「裂变」限时）
    }
)


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
) -> List[str]:
    """只保留直接影响 TTK 的选项，并保证默认件在内（否则最优可能被剪掉）。"""
    kept: List[str] = []
    seen = set()
    for item in options:
        if (
            item in seen
            or str(item) in EXCLUDED_PART_IDS
            or not part_affects_ttk(game_data.get_part(item))
        ):
            continue
        seen.add(item)
        kept.append(item)
    if default_item and str(default_item) not in EXCLUDED_PART_IDS and default_item not in seen:
        kept.insert(0, default_item)
    return kept


def build_socket_specs(game_data: Any, weapon: Mapping[str, Any]) -> List[SocketSpec]:
    """构造参与枚举的插槽计划：先根插槽，后插入式插槽。

    选项按「直接影响 TTK」剪枝；剪枝后只剩单一选项的插槽不参与枚举（无搜索价值）。
    """
    defaults = {str(k): str(v) for k, v in (weapon.get("default_items") or {}).items()}
    variant_item = str(weapon.get("variant_item_id")) if weapon.get("variant_item_id") else None

    root: List[SocketSpec] = []
    for socket in weapon.get("sockets") or []:
        socket_id = str(socket.get("socket_id"))
        options = _prune_options(
            game_data, [str(o) for o in (socket.get("options") or [])], defaults.get(socket_id)
        )
        if len(options) <= 1:
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
            )
            if len(options) <= 1:
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
# 配装枚举
# --------------------------------------------------------------------------- #
DEFAULT_COARSE_DISTANCES: Tuple[float, ...] = (0.0, 40.0, 80.0)


class LoadoutSolver:
    """在官方插槽规则下束搜索实战 TTK 最优的候选配装。"""

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

