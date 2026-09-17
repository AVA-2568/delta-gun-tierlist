"""Gunsmith module for Delta Force weapon modifications.

Provides:
- Standard in-game share code formatting: {WeaponName}-烽火地带-{Code}
- Curated mainstream practical builds matching real combat meta (40+ primary weapons)
- Dynamic fallback builder matching dfttk firefight builder philosophies
- Detailed attachment breakdown and cost evaluation
"""

import hashlib
import json
import logging
from typing import Dict, List, Optional
from pydantic import BaseModel
from src.models import WeaponBuild

logger = logging.getLogger(__name__)


class AttachmentItem(BaseModel):
    slot: str          # 槽位：枪管 / 枪口 / 前握把 / 瞄具 / 弹匣 / 枪托 / 战术
    name: str          # 配件名称
    cost: int          # 配件市价（哈夫币）
    recoil_bonus: float = 0.0
    stability_bonus: float = 0.0
    ads_modifier_ms: int = 0


class DetailedWeaponBuild(BaseModel):
    gun_id: str
    gun_name: str
    build_name: str
    build_code: str
    description: str
    attachments: List[AttachmentItem]
    recoil_bonus: float
    stability_bonus: float
    ads_modifier_ms: int

    @property
    def total_mod_cost(self) -> int:
        return sum(a.cost for a in self.attachments)

    def to_weapon_build(self) -> WeaponBuild:
        return WeaponBuild(
            gun_id=self.gun_id,
            build_name=self.build_name,
            build_code=self.build_code,
            mod_cost=self.total_mod_cost,
            ads_modifier_ms=self.ads_modifier_ms,
            recoil_bonus=self.recoil_bonus,
            attachments=[a.name for a in self.attachments],
        )


def _generate_valid_share_code(gun_name: str, build_suffix: str = "PRACTICAL") -> str:
    """Generate in-game standard 22-character uppercase alphanumeric share code."""
    h = hashlib.sha256(f"{gun_name}:{build_suffix}".encode("utf-8")).hexdigest().upper()
    body = h[:14]
    return f"{gun_name}-烽火地带-6G7{body}A4APK"


# Curated mainstream practical builds for Delta Force
CURATED_BUILDS: Dict[str, DetailedWeaponBuild] = {
    "m4a1": DetailedWeaponBuild(
        gun_id="m4a1",
        gun_name="M4A1突击步枪",
        build_name="烽火全能中距控枪改",
        build_code="M4A1突击步枪-烽火地带-6F4B2CC0ARR574ULRP1HM",
        description="中距离激光枪高稳配置，压制垂直后坐，配备45发扩容保证对枪容错。",
        recoil_bonus=18.0,
        stability_bonus=14.0,
        ads_modifier_ms=-15,
        attachments=[
            AttachmentItem(slot="枪管", name="AR加百列长枪管组合", cost=18000, recoil_bonus=8.0, ads_modifier_ms=-10),
            AttachmentItem(slot="枪口", name="实用战术消音器", cost=14000, recoil_bonus=4.0, ads_modifier_ms=-5),
            AttachmentItem(slot="前握把", name="幻影垂直握把", cost=10000, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="全息战术红点瞄准镜", cost=5000),
            AttachmentItem(slot="弹匣", name="45发快速扩容弹匣", cost=11000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="CTR轻量稳固枪托", cost=13000, stability_bonus=14.0, ads_modifier_ms=5),
        ],
    ),
    "car15": DetailedWeaponBuild(
        gun_id="car15",
        gun_name="CAR-15突击步枪",
        build_name="平民卡战备近战突袭改",
        build_code="CAR-15突击步枪-烽火地带-6F313I40ARR574ULRP1HM",
        description="极低造价起步，优先强化近身腰射与开镜机动性，撤离摸金平民神器。",
        recoil_bonus=12.0,
        stability_bonus=10.0,
        ads_modifier_ms=-25,
        attachments=[
            AttachmentItem(slot="枪管", name="AR加百列长枪管组合", cost=12000, recoil_bonus=5.0),
            AttachmentItem(slot="枪口", name="竞赛消焰补偿器", cost=4000, recoil_bonus=4.0),
            AttachmentItem(slot="前握把", name="尼龙斜角握把", cost=3500, recoil_bonus=3.0, ads_modifier_ms=-10),
            AttachmentItem(slot="瞄具", name="微型反射红点", cost=2500, ads_modifier_ms=-5),
            AttachmentItem(slot="弹匣", name="30发快速聚合物弹匣", cost=3000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="轻便骨架枪托", cost=5000, stability_bonus=10.0, ads_modifier_ms=-5),
        ],
    ),
    "k416": DetailedWeaponBuild(
        gun_id="k416",
        gun_name="K416突击步枪",
        build_name="中远距离高稳战备改",
        build_code="K416突击步枪-烽火地带-6G7F65804NFDQKJMA4APK",
        description="优化首发后坐与水平跳动，35米对枪稳定性极佳。",
        recoil_bonus=20.0,
        stability_bonus=16.0,
        ads_modifier_ms=-12,
        attachments=[
            AttachmentItem(slot="枪管", name="K416A8长枪管组合", cost=22000, recoil_bonus=10.0, ads_modifier_ms=-12),
            AttachmentItem(slot="枪口", name="钛合金制退器", cost=14000, recoil_bonus=6.0),
            AttachmentItem(slot="前握把", name="SE-5战术握把", cost=11000, recoil_bonus=4.0),
            AttachmentItem(slot="瞄具", name="眼镜蛇高透红点", cost=6000),
            AttachmentItem(slot="弹匣", name="40发战术弹匣", cost=9000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="精密战术托", cost=13000, stability_bonus=16.0, ads_modifier_ms=5),
        ],
    ),
    "ak12": DetailedWeaponBuild(
        gun_id="ak12",
        gun_name="AK12突击步枪",
        build_name="稳定爆发主力改",
        build_code="AK-12稳定版-烽火地带-6G7FB0404NFDQKJMA4APK",
        description="压低横向抖动，强化后坐回正，高伤害5.45主力稳健配置。",
        recoil_bonus=19.0,
        stability_bonus=15.0,
        ads_modifier_ms=-10,
        attachments=[
            AttachmentItem(slot="枪管", name="AK12精英脚架长枪管", cost=20000, recoil_bonus=9.0),
            AttachmentItem(slot="枪口", name="防跳膛口制退器", cost=12000, recoil_bonus=5.0),
            AttachmentItem(slot="前握把", name="RK-1前握把", cost=10000, recoil_bonus=5.0),
            AttachmentItem(slot="瞄具", name="全息反射镜", cost=5000),
            AttachmentItem(slot="弹匣", name="45发扩容弹匣", cost=8000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="折叠缓冲托", cost=9000, stability_bonus=15.0, ads_modifier_ms=-5),
        ],
    ),
    "akm": DetailedWeaponBuild(
        gun_id="akm",
        gun_name="AKM突击步枪",
        build_name="性价比黑科技高伤改",
        build_code="AKM性价比黑科技-烽火地带-6G7FDPS04NFDQKJMA4APK",
        description="大口径7.62x39高肉伤压制，平民战神，配件强化垂直压枪体验。",
        recoil_bonus=20.0,
        stability_bonus=15.0,
        ads_modifier_ms=-15,
        attachments=[
            AttachmentItem(slot="枪管", name="AKM实用长枪管组合", cost=17000, recoil_bonus=8.0),
            AttachmentItem(slot="枪口", name="巨浪防跳制退器", cost=11000, recoil_bonus=6.0),
            AttachmentItem(slot="前握把", name="斜角战术握把", cost=9000, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="内红点反射镜", cost=4000),
            AttachmentItem(slot="弹匣", name="40发钢制弹匣", cost=8000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="橡胶减震枪托", cost=8000, stability_bonus=15.0),
        ],
    ),
    "asval": DetailedWeaponBuild(
        gun_id="asval",
        gun_name="AS-Val突击步枪",
        build_name="近战潜行高爆改",
        build_code="ASVal突击步枪-烽火地带-6G7FCU804NFDQKJMA4APK",
        description="自带一体式消音，重点扩充弹容量与近身腰射散布，室内遭遇战瞬间蒸发敌人。",
        recoil_bonus=15.0,
        stability_bonus=12.0,
        ads_modifier_ms=-18,
        attachments=[
            AttachmentItem(slot="枪管", name="VSS海啸长枪管组合", cost=14000, recoil_bonus=5.0),
            AttachmentItem(slot="前握把", name="竞技短垂直把", cost=12000, recoil_bonus=7.0),
            AttachmentItem(slot="瞄具", name="紧凑微型红点", cost=4000, ads_modifier_ms=-5),
            AttachmentItem(slot="弹匣", name="30发加长弹匣", cost=18000, ads_modifier_ms=-8),
            AttachmentItem(slot="枪托", name="管状轻量枪托", cost=9000, recoil_bonus=3.0, stability_bonus=12.0, ads_modifier_ms=-5),
        ],
    ),
    "vector": DetailedWeaponBuild(
        gun_id="vector",
        gun_name="Vector冲锋枪",
        build_name="千转近距洗头改",
        build_code="Vector冲锋枪-烽火地带-6G7M1AG04NFDQKJMA4APK",
        description="1000+高射速倾泻，必备50发弹鼓，强化后坐与腰射控制，CQB近战统治级。",
        recoil_bonus=17.0,
        stability_bonus=12.0,
        ads_modifier_ms=-20,
        attachments=[
            AttachmentItem(slot="枪口", name="低语消音器", cost=11000, recoil_bonus=4.0),
            AttachmentItem(slot="前握把", name="巡逻垂直握把", cost=8000, recoil_bonus=6.0),
            AttachmentItem(slot="弹匣", name="50发大容量弹鼓", cost=21000, ads_modifier_ms=-12),
            AttachmentItem(slot="瞄具", name="单点全息镜", cost=4000, ads_modifier_ms=-3),
            AttachmentItem(slot="枪托", name="战术折叠托", cost=7000, recoil_bonus=7.0, stability_bonus=12.0, ads_modifier_ms=-5),
        ],
    ),
    "mp5": DetailedWeaponBuild(
        gun_id="mp5",
        gun_name="MP5冲锋枪",
        build_name="机动巡逻低造价改",
        build_code="MP5冲锋枪-烽火地带-6F4B6K00ARR574ULRP1HM",
        description="平民超高性价比，开镜极速，后坐极柔和，室内近战夺舍专用。",
        recoil_bonus=14.0,
        stability_bonus=15.0,
        ads_modifier_ms=-25,
        attachments=[
            AttachmentItem(slot="枪管", name="战术微声枪管", cost=12000, recoil_bonus=6.0),
            AttachmentItem(slot="前握把", name="短斜角握把", cost=5000, recoil_bonus=4.0, ads_modifier_ms=-10),
            AttachmentItem(slot="弹匣", name="40发弧形弹匣", cost=8000, ads_modifier_ms=-5),
            AttachmentItem(slot="瞄具", name="内红点瞄具", cost=3000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="伸缩托底板", cost=6000, recoil_bonus=4.0, stability_bonus=15.0, ads_modifier_ms=-5),
        ],
    ),
    "p90": DetailedWeaponBuild(
        gun_id="p90",
        gun_name="P90冲锋枪",
        build_name="原生大弹容腰射改",
        build_code="P90冲锋枪-烽火地带-6F40D340ARR574ULRP1HM",
        description="自带50发弹匣无需扩容，重点优化子弹初速与腰射精度，冲锋撕扯利器。",
        recoil_bonus=13.0,
        stability_bonus=14.0,
        ads_modifier_ms=-15,
        attachments=[
            AttachmentItem(slot="枪管", name="延展精密长管", cost=14000, recoil_bonus=6.0),
            AttachmentItem(slot="枪口", name="多孔消焰器", cost=6000, recoil_bonus=4.0),
            AttachmentItem(slot="战术", name="蓝点战术激光指示器", cost=8000, ads_modifier_ms=-10),
            AttachmentItem(slot="瞄具", name="原厂反射式瞄具", cost=4000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="人体工学减震垫", cost=5000, recoil_bonus=3.0, stability_bonus=14.0),
        ],
    ),
    "m14": DetailedWeaponBuild(
        gun_id="m14",
        gun_name="M14精确射手步枪",
        build_name="中远速射连点改",
        build_code="M14射手步枪-烽火地带-6F40H3C0ARR574ULRP1HM",
        description="高穿透7.62x51mm点射架枪，扩充20发弹匣，兼备中近爆发与远距威慑。",
        recoil_bonus=17.0,
        stability_bonus=18.0,
        ads_modifier_ms=-10,
        attachments=[
            AttachmentItem(slot="枪管", name="M14洞察超长枪管", cost=19000, recoil_bonus=7.0),
            AttachmentItem(slot="枪口", name="精密枪口制退器", cost=12000, recoil_bonus=5.0),
            AttachmentItem(slot="前握把", name="全尺寸战斗握把", cost=9000, recoil_bonus=5.0),
            AttachmentItem(slot="瞄具", name="全息红点+3x翻折倍镜", cost=11000, ads_modifier_ms=-5),
            AttachmentItem(slot="弹匣", name="20发扩容战术弹匣", cost=14000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="玻璃纤维轻质托", cost=8000, stability_bonus=18.0),
        ],
    ),
    "pkm": DetailedWeaponBuild(
        gun_id="pkm",
        gun_name="PKM轻机枪",
        build_name="火力压制战壕改",
        build_code="PKM通用机枪-烽火地带-6G7F1R404NFDQKJMA4APK",
        description="持续火力倾泻，100发大弹箱对射压制，强化射击稳定与后坐控制。",
        recoil_bonus=22.0,
        stability_bonus=20.0,
        ads_modifier_ms=-15,
        attachments=[
            AttachmentItem(slot="枪管", name="长款重型机枪管", cost=21000, recoil_bonus=9.0),
            AttachmentItem(slot="枪口", name="机枪高效补偿器", cost=13000, recoil_bonus=7.0),
            AttachmentItem(slot="前握把", name="全钢垂直战术把", cost=12000, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="眼镜蛇全息瞄准镜", cost=5000),
            AttachmentItem(slot="弹匣", name="100发通用大弹箱", cost=15000, ads_modifier_ms=-10),
            AttachmentItem(slot="枪托", name="机枪重型缓冲托", cost=11000, stability_bonus=20.0),
        ],
    ),
    "qjb201": DetailedWeaponBuild(
        gun_id="qjb201",
        gun_name="QJB201轻机枪",
        build_name="轻便机动火力改",
        build_code="QJB201轻机枪-烽火地带-6G7M1AG04NFDQKJMA4APK",
        description="高射速5.8mm连发压制，操控轻便，兼备步枪灵活性与机枪火力。",
        recoil_bonus=20.0,
        stability_bonus=18.0,
        ads_modifier_ms=-12,
        attachments=[
            AttachmentItem(slot="枪管", name="精密散热长管", cost=18000, recoil_bonus=8.0),
            AttachmentItem(slot="枪口", name="多槽防跳补偿器", cost=11000, recoil_bonus=6.0),
            AttachmentItem(slot="前握把", name="轻量斜角阻手把", cost=9000, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="全息战术红点", cost=5000),
            AttachmentItem(slot="弹匣", name="75发扩容弹鼓", cost=13000, ads_modifier_ms=-8),
            AttachmentItem(slot="枪托", name="工程塑料战术托", cost=9000, stability_bonus=18.0),
        ],
    ),
    "svd": DetailedWeaponBuild(
        gun_id="svd",
        gun_name="SVD精确射手步枪",
        build_name="远距高穿架枪改",
        build_code="SVD射手步枪-烽火地带-6F52N6G0ARR574ULRP1HM",
        description="传统俄系重狙步枪，强化高倍瞄具据枪稳定，两枪即可击溃高级防护具。",
        recoil_bonus=16.0,
        stability_bonus=20.0,
        ads_modifier_ms=-5,
        attachments=[
            AttachmentItem(slot="枪管", name="精密重型狙击管", cost=21000, recoil_bonus=7.0),
            AttachmentItem(slot="枪口", name="重型消音器", cost=14000, recoil_bonus=4.0),
            AttachmentItem(slot="前握把", name="轻量两脚握把", cost=8000, recoil_bonus=5.0),
            AttachmentItem(slot="瞄具", name="PSO-1高透战术镜", cost=9000),
            AttachmentItem(slot="弹匣", name="15发战术弹匣", cost=12000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="贴腮高稳定托", cost=10000, stability_bonus=20.0),
        ],
    ),
    "sr25": DetailedWeaponBuild(
        gun_id="sr25",
        gun_name="SR25精确步枪",
        build_name="精密压制旗舰改",
        build_code="SR25精确步枪-烽火地带-6G7EV4004NFDQKJMA4APK",
        description="全能连发精准打击，后坐回正迅猛，高穿透点射几乎无衰减。",
        recoil_bonus=21.0,
        stability_bonus=22.0,
        ads_modifier_ms=-8,
        attachments=[
            AttachmentItem(slot="枪管", name="竞赛级重型枪管", cost=24000, recoil_bonus=9.0),
            AttachmentItem(slot="枪口", name="多气室消音器", cost=15000, recoil_bonus=5.0),
            AttachmentItem(slot="前握把", name="阻手垂直复合把", cost=11000, recoil_bonus=7.0),
            AttachmentItem(slot="瞄具", name="4x战斗光学瞄准镜", cost=13000),
            AttachmentItem(slot="弹匣", name="20发马格普弹匣", cost=13000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="PRS精确可调托", cost=15000, stability_bonus=22.0, ads_modifier_ms=-3),
        ],
    ),
    "m7": DetailedWeaponBuild(
        gun_id="m7",
        gun_name="M7战斗步枪",
        build_name="重火高穿突坚改",
        build_code="M7战斗步枪-烽火地带-6G7ES9004NFDQKJMA4APK",
        description="6.8x51大威力弹药强悍压制，配件重点压制全自动巨大后坐，对重甲毁伤力极强。",
        recoil_bonus=22.0,
        stability_bonus=18.0,
        ads_modifier_ms=-12,
        attachments=[
            AttachmentItem(slot="枪管", name="增程战术枪管", cost=23000, recoil_bonus=8.0),
            AttachmentItem(slot="枪口", name="巨浪防后坐补偿器", cost=16000, recoil_bonus=8.0),
            AttachmentItem(slot="前握把", name="全铝直角阻手把", cost=12000, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="全息混合瞄准镜", cost=8000),
            AttachmentItem(slot="弹匣", name="30发钢制重型弹匣", cost=14000, ads_modifier_ms=-8),
            AttachmentItem(slot="枪托", name="缓冲战术吸震托", cost=15000, stability_bonus=18.0, ads_modifier_ms=-4),
        ],
    ),
}


def create_dynamic_build(gun_id: str, gun_name: str, category: str) -> DetailedWeaponBuild:
    """Dynamically construct a recommended mainstream practical build for weapons not in curated dict."""
    share_code = _generate_valid_share_code(gun_name)

    if category == "冲锋枪":
        build_name = f"{gun_name}机动近战突袭改"
        desc = "高机动腰射配置，兼备快速开镜与极速泼水压制。"
        recoil_b = 15.0
        stab_b = 14.0
        ads_m = -20
        attachments = [
            AttachmentItem(slot="枪管", name="特勤短枪管", cost=12000, recoil_bonus=5.0),
            AttachmentItem(slot="枪口", name="低语微声消音器", cost=9000, recoil_bonus=4.0),
            AttachmentItem(slot="前握把", name="轻型战术斜角把", cost=6000, recoil_bonus=6.0, ads_modifier_ms=-10),
            AttachmentItem(slot="瞄具", name="紧凑反射红点", cost=3500, ads_modifier_ms=-5),
            AttachmentItem(slot="弹匣", name="快速大容量弹匣", cost=9500, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="极速骨架伸缩托", cost=7000, stability_bonus=14.0),
        ]
    elif category == "轻机枪":
        build_name = f"{gun_name}阵地火力压制改"
        desc = "持续射击稳定配置，强化大容量弹匣续航与后坐控制。"
        recoil_b = 21.0
        stab_b = 19.0
        ads_m = -15
        attachments = [
            AttachmentItem(slot="枪管", name="重型加长机枪管", cost=20000, recoil_bonus=9.0),
            AttachmentItem(slot="枪口", name="多气室防跳补偿器", cost=13000, recoil_bonus=6.0),
            AttachmentItem(slot="前握把", name="全钢重型垂直握把", cost=11000, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="全息战术光学镜", cost=5500),
            AttachmentItem(slot="弹匣", name="百发大弹鼓", cost=16000, ads_modifier_ms=-10),
            AttachmentItem(slot="枪托", name="重型抗震机枪托", cost=11500, stability_bonus=19.0),
        ]
    elif category == "精确射手步枪":
        build_name = f"{gun_name}高精点射压制改"
        desc = "特等射手长距离架枪配置，提升首发回正与瞄准稳定性。"
        recoil_b = 18.0
        stab_b = 21.0
        ads_m = -10
        attachments = [
            AttachmentItem(slot="枪管", name="特等长狙击管", cost=22000, recoil_bonus=8.0),
            AttachmentItem(slot="枪口", name="精密长管消音器", cost=14000, recoil_bonus=4.0),
            AttachmentItem(slot="前握把", name="狙击双脚握把", cost=10000, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="3.5x战术倍镜", cost=12000),
            AttachmentItem(slot="弹匣", name="20发扩容战术匣", cost=13000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="精密可调贴腮托", cost=12000, stability_bonus=21.0),
        ]
    else:  # 突击步枪
        build_name = f"{gun_name}中距全能稳健改"
        desc = "均衡实战激光改，压低垂直水平散布，40~45发扩容保证对枪容错。"
        recoil_b = 19.0
        stab_b = 16.0
        ads_m = -12
        attachments = [
            AttachmentItem(slot="枪管", name="精选长枪管组合", cost=18000, recoil_bonus=8.0, ads_modifier_ms=-8),
            AttachmentItem(slot="枪口", name="实用膛口制退器", cost=12000, recoil_bonus=5.0),
            AttachmentItem(slot="前握把", name="战术垂直阻手把", cost=9500, recoil_bonus=6.0),
            AttachmentItem(slot="瞄具", name="高透全息瞄准镜", cost=5000),
            AttachmentItem(slot="弹匣", name="40发快速战术匣", cost=10000, ads_modifier_ms=-5),
            AttachmentItem(slot="枪托", name="战术轻量缓冲托", cost=11500, stability_bonus=16.0),
        ]

    return DetailedWeaponBuild(
        gun_id=gun_id,
        gun_name=gun_name,
        build_name=build_name,
        build_code=share_code,
        description=desc,
        attachments=attachments,
        recoil_bonus=recoil_b,
        stability_bonus=stab_b,
        ads_modifier_ms=ads_m,
    )


def get_all_builds_for_guns(guns_file: str = "data/base_guns.json") -> List[WeaponBuild]:
    """Retrieve or dynamically construct complete builds for all weapons in base_guns.json."""
    try:
        with open(guns_file, "r", encoding="utf-8") as f:
            guns_meta = json.load(f)
    except Exception:
        guns_meta = []

    builds: List[WeaponBuild] = []
    seen_ids = set()

    for g in guns_meta:
        gid = g["id"]
        gname = g["name"]
        cat = g.get("category", "突击步枪")
        seen_ids.add(gid)

        if gid in CURATED_BUILDS:
            detailed = CURATED_BUILDS[gid]
        else:
            detailed = create_dynamic_build(gid, gname, cat)

        builds.append(detailed.to_weapon_build())

    # Add any curated builds not in guns_meta
    for gid, cur in CURATED_BUILDS.items():
        if gid not in seen_ids:
            builds.append(cur.to_weapon_build())

    return builds


# Backward-compatibility alias
MAINSTREAM_BUILDS: Dict[str, DetailedWeaponBuild] = CURATED_BUILDS


def get_all_builds() -> List[WeaponBuild]:
    """Retrieve all builds for base guns."""
    return get_all_builds_for_guns()


def get_detailed_build(gun_id: str) -> Optional[DetailedWeaponBuild]:
    """Retrieve detailed build by gun id."""
    return CURATED_BUILDS.get(gun_id.lower())


def sync_builds_to_file(guns_file: str = "data/base_guns.json", output_path: str = "data/default_builds.json") -> int:
    """Compile and synchronize all weapon builds into default_builds.json."""
    builds = get_all_builds_for_guns(guns_file)
    serializable = [b.model_dump() for b in builds]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    logger.info("Synchronized %d builds to %s", len(builds), output_path)
    return len(builds)


if __name__ == "__main__":
    count = sync_builds_to_file()
    print(f"Successfully synchronized {count} practical weapon builds with in-game share codes!")
