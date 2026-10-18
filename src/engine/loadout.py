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
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from src.engine import engagement as eg
from src.engine.weapon_state import WeaponStateResolver, build_loadout

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
# S10「裂变」三件 HVK 限时件：ASh-12 双发枪管、复合弓速射箭匣、SVCH 凌风并联弹匣。
# 其中速射箭匣会大幅改射速/优势射程（TTK 敏感），若不排除会让复合弓在新赛季虚高；
# 凌风弹匣只改弹匣容量与换弹（TTK 中性），一并列入以保持赛季清单完整。
EXCLUDED_PART_IDS: frozenset = frozenset(
    {
        "13020000590",  # M249 H.A.V.K 链锯套件（S9「回声」限时）
        "13020000595",  # MP7 H.A.V.K 格斗套件（S9「回声」限时）
        "13020000603",  # ASh-12 HVK 双发枪管（S10「裂变」限时）
        "13120000381",  # 复合弓 HVK 速射箭匣（S10「裂变」限时，改射速/优势射程）
        "13120000379",  # SVCH 凌风并联弹匣（S10「裂变」限时，TTK 中性但已绝版）
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
    relevant_providers: Optional[Set[str]] = None,
) -> List[str]:
    """只保留直接影响 TTK 的选项，并保证默认件在内（否则最优可能被剪掉）。

    ``relevant_providers`` 为「自身不直接改 TTK、但会解锁新的 TTK 选项」的
    提供者件（如 QJB201 的护木解锁导气箍、M700 的枪身系统解锁导气）。它们也必须
    保留，否则束搜索永远看不到被它们解锁的合法 TTK 状态。
    """
    relevant_providers = relevant_providers or set()
    kept: List[str] = []
    seen = set()
    for item in options:
        part = game_data.get_part(item)
        if (
            item in seen
            or str(item) in EXCLUDED_PART_IDS
            or part is None
            # 不可选中的内部件只能由默认/耦合带入，不能作为玩家自由选项
            or (str(item) != str(default_item) and not part.get("selectable", True))
            or (not part_affects_ttk(part) and str(item) not in relevant_providers)
        ):
            continue
        seen.add(item)
        kept.append(item)
    if default_item and str(default_item) not in EXCLUDED_PART_IDS and default_item not in seen:
        kept.insert(0, default_item)
    return kept


def _ttk_options_by_socket(
    game_data: Any,
    weapon: Mapping[str, Any],
    defaults: Mapping[str, str],
    mounted_items: Iterable[str],
) -> Dict[str, Set[str]]:
    """给定已装提供者件，汇总它们暴露的「非默认 TTK 选项」：``socket_id -> 选项集合``。"""
    out: Dict[str, Set[str]] = {}
    for item in mounted_items:
        for socket in (weapon.get("provider_sockets") or {}).get(str(item)) or []:
            socket_id = str(socket.get("socket_id"))
            default_item = defaults.get(socket_id)
            out.setdefault(socket_id, set()).update(
                str(option)
                for option in socket.get("options") or []
                if str(option) != default_item
                and part_affects_ttk(game_data.get_part(str(option)))
            )
    return out


def _relevant_providers(
    game_data: Any,
    weapon: Mapping[str, Any],
    defaults: Mapping[str, str],
) -> Set[str]:
    """自身不改 TTK、但能解锁**默认装法拿不到**的新 TTK 选项的提供者件。

    典型：QJB201 的三块护木本身无 TTK 效果，但分别解锁 socket 47 的
    高速/稳固导气箍；M700 的 HVK 旋风枪身系统解锁 socket 76 的强化导气。

    已由默认装法覆盖的提供者（例如各枪默认枪管已经暴露全部可用枪口）不算，
    避免把所有枪管都当成有效提供者、把束搜索空间放大一个量级。
    ``forced`` 耦合件（如 MCX-LT 焰魂枪管强制挂载的 376 护木）也不算：它们
    由耦合规则自动装入，不需要作为根插槽选项参与搜索。
    """
    mounted, _ = build_loadout(weapon, {})
    default_ttk = _ttk_options_by_socket(
        game_data, weapon, defaults, mounted.values()
    )
    # 根插槽本身已提供的 TTK 选项也算「默认可得」：例如 M700 的 socket 2
    # 已直接列出 443/444 枪管，内部件 18060000035 再暴露同一组枪管不构成新增。
    for socket in weapon.get("sockets") or []:
        socket_id = str(socket.get("socket_id"))
        default_item = defaults.get(socket_id)
        default_ttk.setdefault(socket_id, set()).update(
            str(option)
            for option in socket.get("options") or []
            if str(option) != default_item
            and part_affects_ttk(game_data.get_part(str(option)))
        )
    forced = {
        str(rule.get("mounted_item_id"))
        for rule in weapon.get("coupling") or []
        if str(rule.get("mount_policy") or "") == "forced"
    }
    relevant: Set[str] = set()
    for provider_id, sockets in (weapon.get("provider_sockets") or {}).items():
        provider_id = str(provider_id)
        if provider_id in forced:
            continue
        for socket in sockets:
            socket_id = str(socket.get("socket_id"))
            default_item = defaults.get(socket_id)
            added = {
                str(option)
                for option in socket.get("options") or []
                if str(option) != default_item
                and part_affects_ttk(game_data.get_part(str(option)))
            } - default_ttk.get(socket_id, set())
            if added:
                relevant.add(provider_id)
                break
    return relevant


def _needs_enumeration(options: Sequence[str], default_item: Optional[str]) -> bool:
    """剪枝后的选项是否值得枚举。

    多于一个选项时显然要枚举；**唯一选项不是默认件时也必须枚举**——
    「只有一个选项」不等于「没有搜索价值」：玩家仍可选择装上它（或保持不装），
    例如 MCX-LT 焰魂枪管强制挂载的护木只暴露一个 SUR 隔热外罩，该外罩
    改射速 -3.4%，属于会改变 TTK 的合法选择。只有「唯一选项就是默认件」时
    才可跳过（默认态已经包含它）。
    """
    if not options:
        return False
    if len(options) > 1:
        return True
    return str(options[0]) != str(default_item or "")


def build_socket_specs(game_data: Any, weapon: Mapping[str, Any]) -> List[SocketSpec]:
    """构造参与枚举的插槽计划：先根插槽，后插入式插槽。

    选项按「直接影响 TTK」剪枝；剪枝后只剩默认件本身的插槽不参与枚举
    （默认态已包含，无搜索价值），但**唯一非默认的 TTK 选项仍参与**。
    """
    defaults = {str(k): str(v) for k, v in (weapon.get("default_items") or {}).items()}
    relevant = _relevant_providers(game_data, weapon, defaults)

    root: List[SocketSpec] = []
    for socket in weapon.get("sockets") or []:
        socket_id = str(socket.get("socket_id"))
        options = _prune_options(
            game_data,
            [str(o) for o in (socket.get("options") or [])],
            defaults.get(socket_id),
            relevant,
        )
        if not _needs_enumeration(options, defaults.get(socket_id)):
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
                relevant,
            )
            if not _needs_enumeration(options, defaults.get(socket_id)):
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

    def __init__(self, game_data: Any, scenario_id: str, resolver: Any = None):
        self.gd = game_data
        self.scenario_id = scenario_id
        self.scenario = eg.resolve_scenario(game_data, scenario_id)
        self.armor = eg.scenario_armor(game_data, self.scenario)
        self.probabilities = self.scenario["hit_probabilities"]
        # 候选弹药等级集合（官方情景为单等级；自定义情景可多等级同榜，如修脚 3/4/5）
        self.ammo_levels = eg.scenario_ammo_levels(self.scenario)
        self.resolver = resolver or WeaponStateResolver(game_data)
        self._ammo_cache: Dict[str, Mapping[str, Any]] = {}

    # ------------------------------------------------------------------ #
    def ammo_for(self, profile_key: str) -> Mapping[str, Any]:
        """主弹：候选中该口径**存在**的最低等级官方池单弹（束搜索打分的默认弹）。

        多等级情景下各弹行由调用方注入对应弹（见 :func:`src.engine.ranking.rank_weapons_for_scenario`），
        本弹仅作主求解器的打分默认；该口径全部候选等级都无弹时抛 :class:`ScenarioError`。
        """
        if profile_key not in self._ammo_cache:
            last_error: Optional[eg.ScenarioError] = None
            for level in self.ammo_levels:
                try:
                    self._ammo_cache[profile_key] = eg.pick_ammo(self.gd, profile_key, level)
                except eg.ScenarioError as exc:
                    last_error = exc
                    continue
                break
            else:
                raise last_error  # type: ignore[misc]
        return self._ammo_cache[profile_key]

    def use_ammo(self, profile_key: str, ammo: Mapping[str, Any]) -> None:
        """把打分用弹固定为 ``ammo``（多等级情景逐弹成行时由调用方注入）。

        注入后 :meth:`_band_score` 不再走 :meth:`ammo_for` 的官方池单弹选取，
        束搜索的候选配装排序即按本款弹计算。
        """
        self._ammo_cache[profile_key] = ammo

    def _mounted(self, profile_key: str, loadout: Mapping[str, str]) -> Dict[str, str]:
        weapon = self.gd.get_weapon(profile_key)
        mounted, _ = build_loadout(weapon, loadout)
        return mounted

    def _band_score(
        self,
        profile_key: str,
        loadout: Mapping[str, str],
        tuning: Optional[Mapping[str, Mapping[str, float]]],
        distances: Sequence[float],
        mounted: Optional[Mapping[str, str]] = None,
    ) -> float:
        state = self.resolver.resolve(
            profile_key, loadout=loadout, tuning=tuning, _precomputed_mounted=mounted
        )
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
        # 打分只由「实际装机结果」决定（``resolve`` 以 mounted 为唯一状态输入），
        # 故按 mounted 签名记忆化：同一签名的重复打分复用，不重跑 resolve/ttk。
        # 纯 memo——不剪枝、不新增候选，候选集合与打分值均与改动前逐位一致。
        score_cache: Dict[Tuple[Tuple[str, str], ...], float] = {}

        def _score(loadout: Mapping[str, str], mounted: Mapping[str, str]) -> float:
            cache_key = tuple(sorted(mounted.items()))
            cached = score_cache.get(cache_key)
            if cached is None:
                cached = self._band_score(profile_key, loadout, None, distances, mounted=mounted)
                score_cache[cache_key] = cached
            return cached

        beam: List[Dict[str, str]] = [{}]
        # 预打分空配装以播种 score_cache：首轮「不装任何件」分支会复用这一结果。
        _score({}, self._mounted(profile_key, {}))

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
                    # actual 已是该 trial 的合成结果，直接透传给 resolve，避免重跑耦合求解
                    expanded[key] = (trial, _score(trial, actual))
            ranked = sorted(expanded.values(), key=lambda pair: pair[1])[:beam_width]
            beam = [loadout for loadout, _ in ranked]
        return beam

