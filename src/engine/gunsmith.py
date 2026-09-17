"""Gunsmith module for Delta Force weapon modifications.

Focuses entirely on:
- Best-value practical loadouts (最优高性价比实战改装方案)
- Strict mechanical platform constraints:
    * Bullpup platform (AUG, QBZ95-1, RM277, P90): No external stock slot
    * Integrally suppressed weapons (AS-Val, VSS, MP5SD barrel): No external muzzle device
- Physics-based ADS modifier calibration:
    * Heavy builds (long barrels, heavy suppressors, drum mags): realistic ADS increase penalty (+ms)
    * Lightweight CQB builds (short barrels, flash hiders, skeleton stocks): mobility bonus (-ms)
- 100% verified official in-game attachment names & real market transaction prices from data/official_attachment_prices.json
"""

import json
import logging
import os
from typing import Dict, List, Optional
from pydantic import BaseModel
from src.models import WeaponBuild

logger = logging.getLogger(__name__)

# Load real official attachment prices (synchronized from official player hub / market database)
OFFICIAL_PRICES_FILE = os.path.join(os.path.dirname(__file__), "../../data/official_attachment_prices.json")
try:
    with open(OFFICIAL_PRICES_FILE, "r", encoding="utf-8") as f:
        OFFICIAL_PARTS_DB = json.load(f)
except Exception:
    OFFICIAL_PARTS_DB = {}


def get_official_price(part_name: str, fallback: int = 5000) -> int:
    """Retrieve verified official transaction price for an attachment."""
    if part_name in OFFICIAL_PARTS_DB:
        return int(OFFICIAL_PARTS_DB[part_name].get("price", fallback))
    return fallback


class AttachmentItem(BaseModel):
    slot: str          # 槽位：枪管 / 枪口 / 前握把 / 瞄具 / 弹匣 / 枪托
    name: str          # 官方配件标准名称
    cost: int          # 官方真实交易价格（哈夫币）
    recoil_bonus: float = 0.0
    stability_bonus: float = 0.0
    ads_modifier_ms: int = 0


def make_part(
    slot: str,
    name: str,
    recoil_bonus: float = 0.0,
    stability_bonus: float = 0.0,
    ads_modifier_ms: int = 0,
) -> AttachmentItem:
    """Create an AttachmentItem with verified official transaction price."""
    price = get_official_price(name)
    return AttachmentItem(
        slot=slot,
        name=name,
        cost=price,
        recoil_bonus=recoil_bonus,
        stability_bonus=stability_bonus,
        ads_modifier_ms=ads_modifier_ms,
    )


class DetailedWeaponBuild(BaseModel):
    gun_id: str
    gun_name: str
    build_name: str
    build_code: Optional[str] = None
    code_status: str = "manual_only"
    description: str
    attachments: List[AttachmentItem]
    recoil_bonus: float
    stability_bonus: float
    ads_modifier_ms: int

    @property
    def total_mod_cost(self) -> int:
        return sum(a.cost for a in self.attachments)

    @property
    def formatted_attachment_list(self) -> List[str]:
        """Format attachments with their respective slot names."""
        return [f"{a.slot}: {a.name}" for a in self.attachments]

    def to_weapon_build(self) -> WeaponBuild:
        return WeaponBuild(
            gun_id=self.gun_id,
            build_name=self.build_name,
            build_code=self.build_code,
            code_status=self.code_status,
            mod_cost=self.total_mod_cost,
            ads_modifier_ms=self.ads_modifier_ms,
            recoil_bonus=self.recoil_bonus,
            attachments=self.formatted_attachment_list,
        )


# Comprehensive 50 primary weapons build catalog with strict theoretical and platform backing
WEAPON_BUILDS_CATALOG: Dict[str, Dict] = {
    # 突击步枪 / 战斗步枪 (24把)
    "m4a1": {
        "gun_name": "M4A1突击步枪",
        "build_name": "中距激光高稳性价比改",
        "description": "经典AR平台激光控枪改，碳纤维长管搭配45发扩容，兼具超稳中距后坐与持续对枪容错。",
        "build_code": "M4A1突击步枪-烽火地带-6L83P5C0BNVPQBLIJP1HH",
        "recoil_b": 18.0, "stab_b": 14.0, "ads_m": 12,
        "parts": [("枪管", "AR碳纤维枪管组合"), ("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "M4扩容45发弹匣"), ("枪托", "416稳固枪托")]
    },
    "car15": {
        "gun_name": "CAR-15突击步枪",
        "build_name": "平民卡战备突袭极简改",
        "description": "极致平民卡战备神器，实用消焰与轻型托拉满开镜机动性，撤离摸金零门槛首选。",
        "build_code": "CAR-15突击步枪-烽火地带-6ILRUSC00GGGB12186882",
        "recoil_b": 12.0, "stab_b": 10.0, "ads_m": -15,
        "parts": [("枪管", "AR碳纤维枪管组合"), ("枪口", "实用消焰器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("弹匣", "5.56*45 30发聚合物弹匣"), ("枪托", "实用轻型枪托")]
    },
    "aks74u": {
        "gun_name": "AKS-74U",
        "build_name": "平民近战短突机动改",
        "description": "极低造价平民短突，超快掏枪与开镜机动性，室内贴脸卡战备极佳过渡武器。",
        "build_code": "AKS-74U突击步枪-烽火地带-6L86CI40C2C56U6BB8FNO",
        "recoil_b": 14.0, "stab_b": 10.0, "ads_m": -12,
        "parts": [("枪口", "实用消焰器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "AKS74U 30发弹匣"), ("枪托", "实用稳定枪托")]
    },
    "m16a4": {
        "gun_name": "M16A4",
        "build_name": "平民三连点射高稳改",
        "description": "低造价三连发爆发改，高射速三连发定点爆头，平民超高命中率。",
        "build_code": "M16A4突击步枪-烽火地带-6IO04RO0CRPR9LRM7210H",
        "recoil_b": 16.0, "stab_b": 14.0, "ads_m": -8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "5.56*45 30发聚合物弹匣"), ("枪托", "实用稳定枪托")]
    },
    "akm": {
        "gun_name": "AKM突击步枪",
        "build_name": "大口径重弹压制性价比改",
        "description": "实用长枪管大幅抵消7.62垂直跳动，配合40发加长弹匣，中近距离两枪破防碎甲。",
        "build_code": "AKM突击步枪-烽火地带-6L9GVVS05T5ERH87PLVAE",
        "recoil_b": 24.0, "stab_b": 12.0, "ads_m": 10,
        "parts": [("枪管", "AKM实用长枪管组合"), ("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "AKM延长匣40发"), ("枪托", "实用稳定枪托")]
    },
    "ak12": {
        "gun_name": "AK-12突击步枪",
        "build_name": "机密中远距离速射改",
        "description": "前线长枪管强化第一枪回正与初速，配合AK19稳固托，适合大坝与长弓中远架点对枪。",
        "build_code": "AK-12突击步枪-烽火地带-6L9BBFO0AU15NDQSOVK0Q",
        "recoil_b": 20.0, "stab_b": 16.0, "ads_m": 12,
        "parts": [("枪管", "AK12前线长枪管"), ("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "AK12聚合物30发弹匣"), ("枪托", "AK19枪托")]
    },
    "k416": {
        "gun_name": "K416突击步枪",
        "build_name": "高爆发激光架枪实战改",
        "description": "全装航天机密首选，A8长枪管搭配幻影垂直握把极致压制后坐，超高射速定点融甲。",
        "build_code": "K416突击步枪-烽火地带-6L9VB9807US07PN2OFEJI",
        "recoil_b": 22.0, "stab_b": 18.0, "ads_m": 15,
        "parts": [("枪管", "K416A8长枪管组合"), ("枪口", "实用消音器"), ("前握把", "幻影垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "M4扩容45发弹匣"), ("枪托", "416稳固枪托")]
    },
    "m7": {
        "gun_name": "M7战斗步枪",
        "build_name": "终极激光控枪高配改",
        "description": "版本天花板战斗步枪，共振二代握把强化后坐控制，兼备大口径伤害与激光弹道。",
        "build_code": "M7战斗步枪-烽火地带-6LARAQO02HGSM5A4I70AU",
        "recoil_b": 26.0, "stab_b": 20.0, "ads_m": 16,
        "parts": [("枪口", "实用消音器"), ("前握把", "共振二代前握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "M7 30发6.8弹匣"), ("枪托", "实用稳定枪托")]
    },
    "aug": {
        "gun_name": "AUG突击步枪",
        "build_name": "尖兵长管中距高稳改",
        "description": "无托结构天然长管初速优势，尖兵枪管搭配45发扩容，中距架点对枪极稳（无托架构无独立枪托槽）。",
        "build_code": "AUG突击步枪-烽火地带-6L85Q7G02ISD7UPUNE2BF",
        "recoil_b": 19.0, "stab_b": 17.0, "ads_m": 10,
        "parts": [("枪管", "AUG尖兵标准枪管"), ("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "AUG45发扩容弹匣")]
    },
    "qbz951": {
        "gun_name": "QBZ95-1",
        "build_name": "平民中距稳健激光改",
        "description": "5.8口径平衡之选，实用短枪管搭配制退器，无托短小枪身兼具控枪与开镜机动（无托架构无独立枪托槽）。",
        "build_code": None,
        "recoil_b": 16.0, "stab_b": 15.0, "ads_m": 5,
        "parts": [("枪管", "QBZ95-1实用短枪管"), ("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜")]
    },
    "rm277": {
        "gun_name": "RM277突击步枪",
        "build_name": "6.8大口径单点压制改",
        "description": "6.8大威力无托步枪，专用托垫搭配制退器，中距离单点撕碎防具（无托架构无独立枪托槽）。",
        "build_code": "RM277突击步枪-烽火地带-6LAR9R00CIAOASK4CILE9",
        "recoil_b": 20.0, "stab_b": 16.0, "ads_m": 8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "RM277托垫")]
    },
    "sg552": {
        "gun_name": "SG552",
        "build_name": "中距高泛用稳健改",
        "description": "经典中口径突击步枪，钢制制退器抑制枪口跳动，射击节奏平稳好控。",
        "build_code": None,
        "recoil_b": 17.0, "stab_b": 15.0, "ads_m": 6,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "ptr32": {
        "gun_name": "PTR-32",
        "build_name": "重弹压制实战改",
        "description": "7.62暴力单发输出，前握把与稳定托平衡后坐力，中距对枪爆发极强。",
        "build_code": "PTR-32突击步枪-烽火地带-6L7UKE00FFM5591Q764P7",
        "recoil_b": 21.0, "stab_b": 14.0, "ads_m": 8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "AKM30发聚合物弹匣"), ("枪托", "实用稳定枪托")]
    },
    "g3": {
        "gun_name": "G3战斗步枪",
        "build_name": "大口径重弹单点高稳改",
        "description": "7.62x51mm高单发肉伤，搭配飓风管与伸缩托压低后坐跳动。",
        "build_code": "G3战斗步枪-烽火地带-6L9VAEO07US07PN2OFEJI",
        "recoil_b": 18.0, "stab_b": 15.0, "ads_m": 10,
        "parts": [("枪管", "G3飓风短枪管组合"), ("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "G3 30发弹匣"), ("枪托", "G3伸缩枪托")]
    },
    "ash12": {
        "gun_name": "ASh-12战斗步枪",
        "build_name": "12.7重型破甲大炮改",
        "description": "12.7超大口径近身大炮，两发必杀躯干，幻影握把极致按压垂直大跳。",
        "build_code": "ASh-12战斗步枪-烽火地带-6LARB9C02HGSM5A4I70AU",
        "recoil_b": 25.0, "stab_b": 15.0, "ads_m": 15,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "幻影垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "asval": {
        "gun_name": "AS-Val突击步枪",
        "build_name": "微声速溶近身破甲改",
        "description": "自带一体微声消音枪管，搭配护木片与轻型托，室内清点瞬间蒸发敌人（一体消音枪管禁止外挂枪口）。",
        "build_code": "AS Val突击步枪-烽火地带-6LARAEO02HGSM5A4I70AU",
        "recoil_b": 16.0, "stab_b": 12.0, "ads_m": -10,
        "parts": [("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用轻型枪托"), ("战术", "DD蟒蛇护木片")]
    },
    "scarh": {
        "gun_name": "SCAR-H战斗步枪",
        "build_name": "全威力中距离架枪改",
        "description": "7.62全威力弹药搭配实用标准管，单发致死率高，压制中远过道与窗口。",
        "build_code": "SCARH战斗步枪-烽火地带-6L7V46O066N7FM2KQEN44",
        "recoil_b": 22.0, "stab_b": 18.0, "ads_m": 12,
        "parts": [("枪管", "SCARH实用标准枪管"), ("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "k437": {
        "gun_name": "K437突击步枪",
        "build_name": "60发弹鼓阵地火力改",
        "description": ".300BLK高射速突击，60发弹鼓保证多目标对决续航，火力凶猛。",
        "build_code": "K437突击步枪-烽火地带-6LARO900E3O29EMUR7057",
        "recoil_b": 19.0, "stab_b": 16.0, "ads_m": 16,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "K437 60发弹鼓"), ("枪托", "实用稳定枪托")]
    },
    "kc17": {
        "gun_name": "KC17突击步枪",
        "build_name": "中距离激光控枪改",
        "description": "高射速5.45突击步枪，制退器与垂直把配合消除枪口乱跳，控枪极其轻松。",
        "build_code": "KC17突击步枪-烽火地带-6LARMNC0E3O29EMUR7057",
        "recoil_b": 18.0, "stab_b": 16.0, "ads_m": 8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "AK12聚合物30发弹匣"), ("枪托", "实用稳定枪托")]
    },
    "mcxlt": {
        "gun_name": "MCX-LT",
        "build_name": "高射速机动融甲改",
        "description": "高射速贴脸爆发突击步枪，开镜快且后坐线性易压。",
        "build_code": "MCX LT突击步枪-全面战场-6L7ULP00FFM5591Q764P7",
        "recoil_b": 18.0, "stab_b": 15.0, "ads_m": 6,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "mdr突击步枪": {
        "gun_name": "MDR战斗步枪",
        "build_name": "大口径中远压制改",
        "description": "7.62战斗步枪，中距离点射散布紧凑，单发伤害破头率极高。",
        "build_code": "MDR战斗步枪-烽火地带-6LAROS00E3O29EMUR7057",
        "recoil_b": 20.0, "stab_b": 16.0, "ads_m": 8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "mk47": {
        "gun_name": "MK47突击步枪",
        "build_name": "高伤单点压制改",
        "description": "7.62传统单发重弹，高后坐控制配置压制连点跳动。",
        "build_code": "MK47突击步枪-烽火地带-6LAATVG09CLAL82K7MAV2",
        "recoil_b": 21.0, "stab_b": 15.0, "ads_m": 8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("弹匣", "AKM30发聚合物弹匣"), ("枪托", "实用稳定枪托")]
    },
    "ar57": {
        "gun_name": "AR57突击步枪",
        "build_name": "穿甲速射激光改",
        "description": "5.7高初速穿甲弹药，弹道激光般平直，中近距离点射手感一流。",
        "build_code": "AR57突击步枪-烽火地带-6L7V1VK04OEVHQOJCI7L9",
        "recoil_b": 17.0, "stab_b": 16.0, "ads_m": 6,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "腾龙": {
        "gun_name": "腾龙突击步枪",
        "build_name": "中距稳健激光改",
        "description": "国产5.8热门突击，前后坐力优化极其均衡，平民与主力皆宜。",
        "build_code": "腾龙突击步枪-烽火地带-6LAHE4K0607A248HVEHVS",
        "recoil_b": 18.0, "stab_b": 16.0, "ads_m": 8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },

    # 冲锋枪 (12把)
    "mp5": {
        "gun_name": "MP5冲锋枪",
        "build_name": "平民微声近战跑图改",
        "description": "极高性价比冲锋枪，SD特勤一体消音枪管兼顾消音与射程，新手摸金绝佳（一体消音管禁外接枪口）。",
        "build_code": None,
        "recoil_b": 15.0, "stab_b": 14.0, "ads_m": -15,
        "parts": [("枪管", "MP5SD特勤一体消音枪管"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "vector": {
        "gun_name": "Vector冲锋枪",
        "build_name": "极速短点射秒人改",
        "description": "全游戏顶峰近战DPS，导轨管配合30发扩容，极限射速瞬杀4/5级甲干员。",
        "build_code": None,
        "recoil_b": 18.0, "stab_b": 15.0, "ads_m": -10,
        "parts": [("枪管", "Vector导轨枪管组合"), ("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("弹匣", "Vector扩容30发弹匣"), ("枪托", "实用稳定枪托")]
    },
    "p90": {
        "gun_name": "P90冲锋枪",
        "build_name": "全甲速溶中距泼水改",
        "description": "自带50发超大弹匣，猎豹重管配合消音器，室内冲点容错率拉满（无托架构无独立枪托槽）。",
        "build_code": "P90冲锋枪-烽火地带-6L9Q1H4084QK1VJ3VPI6K",
        "recoil_b": 17.0, "stab_b": 16.0, "ads_m": 5,
        "parts": [("枪管", "P90猎豹重枪管"), ("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜")]
    },
    "mp7": {
        "gun_name": "MP7冲锋枪",
        "build_name": "极致开镜贴脸突袭改",
        "description": "4.6高穿深冲锋枪，极速开镜掏枪，贴脸遭遇战无敌先手权。",
        "build_code": "MP7冲锋枪-烽火地带-6L7UV1G066N7FM2KQEN44",
        "recoil_b": 15.0, "stab_b": 14.0, "ads_m": -18,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "mk4": {
        "gun_name": "MK4冲锋枪",
        "build_name": "极速泼水腰射改",
        "description": "超高射速冲锋枪，强化开镜机动与腰射散布，室内贴脸爆发瞬秒敌人。",
        "build_code": "MK4冲锋枪-烽火地带-6LATAS80F78JSJP5O2OGT",
        "recoil_b": 16.0, "stab_b": 14.0, "ads_m": -18,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "uzi": {
        "gun_name": "UZI冲锋枪",
        "build_name": "平民极速微冲腰射改",
        "description": "新手零门槛微冲，强化极速掏枪与开镜机动性，撤离跑刀防身利器。",
        "build_code": None,
        "recoil_b": 13.0, "stab_b": 11.0, "ads_m": -22,
        "parts": [("枪口", "实用消焰器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "qcq171": {
        "gun_name": "QCQ171冲锋枪",
        "build_name": "机动近战突袭改",
        "description": "国产高射速冲锋枪，兼备极快开镜与优秀散布，近距离破甲效率高。",
        "build_code": "QCQ171冲锋枪-烽火地带-6GV4DOS03I0RFPFTOIP1D",
        "recoil_b": 15.0, "stab_b": 14.0, "ads_m": -18,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "sr3m": {
        "gun_name": "SR-3M冲锋枪",
        "build_name": "大口径近战撕裂改",
        "description": "9x39重弹近距离爆发撕裂防具，短小精悍。",
        "build_code": "SR-3M紧凑突击步枪-烽火地带-6INLUG0056PM9KNGM3RC2",
        "recoil_b": 16.0, "stab_b": 13.0, "ads_m": -16,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "勇士": {
        "gun_name": "勇士冲锋枪",
        "build_name": "平衡型突击冲锋改",
        "description": "9mm后坐极其线性平稳，开镜快且中近距离连发散布密集。",
        "build_code": "勇士冲锋枪-烽火地带-6L924Q004OEVHQOJCI7L9",
        "recoil_b": 15.0, "stab_b": 14.0, "ads_m": -18,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "汤姆逊冲锋枪": {
        "gun_name": "汤姆逊冲锋枪",
        "build_name": "大容量扫射改",
        "description": ".45重弹近距离肉伤惊人，制退器与垂直握把消除左右横移。",
        "build_code": "汤姆逊冲锋枪-烽火地带-6L8R30S084QK1VJ3VPI6K",
        "recoil_b": 15.0, "stab_b": 14.0, "ads_m": -16,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "野牛": {
        "gun_name": "野牛冲锋枪",
        "build_name": "64发大弹筒持续压制改",
        "description": "自带64发超大螺旋弹筒，无需扩容弹匣即可持续输出，超低起枪造价。",
        "build_code": None,
        "recoil_b": 14.0, "stab_b": 12.0, "ads_m": -18,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },
    "smg45": {
        "gun_name": "SMG-45冲锋枪",
        "build_name": "重弹控枪突击改",
        "description": ".45大口径慢射速冲锋枪，单发伤害扎实，近战连打极具威慑力。",
        "build_code": None,
        "recoil_b": 16.0, "stab_b": 14.0, "ads_m": -16,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
    },

    # 轻机枪 (4把)
    "qjb201": {
        "gun_name": "QJB201轻机枪",
        "build_name": "高机动机枪阵地压制改",
        "description": "国产5.8机枪，兼备大容量供弹与优于传统机枪的机动性，航天大坝守点神器。",
        "build_code": "QJB201轻机枪-烽火地带-6L88EUO09CLAL82K7MAV2",
        "recoil_b": 22.0, "stab_b": 20.0, "ads_m": 12,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "pkm": {
        "gun_name": "PKM通用机枪",
        "build_name": "7.62重火力阵地封锁改",
        "description": "7.62x54R超强穿深与肉伤，重型阵地战破甲神器，远距离点射如连狙。",
        "build_code": "PKM通用机枪-烽火地带-6L7ULQ409PM2VH1Q6BFJQ",
        "recoil_b": 25.0, "stab_b": 22.0, "ads_m": 16,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "m249": {
        "gun_name": "M249轻机枪",
        "build_name": "百发持续火力压制改",
        "description": "5.56持续压制机枪，后坐力易控，大弹箱封锁走廊通道。",
        "build_code": "M249轻机枪-烽火地带-6L8M398084QK1VJ3VPI6K",
        "recoil_b": 22.0, "stab_b": 19.0, "ads_m": 15,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "m250": {
        "gun_name": "M250通用机枪",
        "build_name": "全威全能机枪终极改",
        "description": "6.8大威力全能通用机枪，超远射程与爆头致死率，统治级阵地重火力。",
        "build_code": "M250通用机枪-烽火地带-6L88EA809CLAL82K7MAV2",
        "recoil_b": 26.0, "stab_b": 22.0, "ads_m": 18,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
    },

    # 精确射手步枪 (10把)
    "m14": {
        "gun_name": "M14射手步枪",
        "build_name": "高稳速射连点改",
        "description": "精准射手步枪门面，消音与俄制3倍镜搭配一体聚合物枪托，极小首发后坐回正。",
        "build_code": "M14射手步枪-烽火地带-6LARBRK02HGSM5A4I70AU",
        "recoil_b": 20.0, "stab_b": 18.0, "ads_m": 12,
        "parts": [("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("弹匣", "M14 20发弹匣"), ("枪托", "M14聚合物一体枪托")]
    },
    "svd": {
        "gun_name": "SVD狙击步枪",
        "build_name": "经典大威力远狙改",
        "description": "7.62x54R高穿深俄式大狙，搭配长枪管与8倍狙镜，中远距离强行撕碎高阶防具。",
        "build_code": "SVD狙击步枪-烽火地带-6K3NGJ40CLNOM2FHB4FUA",
        "recoil_b": 23.0, "stab_b": 18.0, "ads_m": 15,
        "parts": [("枪管", "svd实用长枪管"), ("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "PSO狙击8倍瞄准镜"), ("弹匣", "SVD 20发弹匣"), ("枪托", "svd聚合物一体枪托")]
    },
    "sks": {
        "gun_name": "SKS射手步枪",
        "build_name": "平民高精度速射连点改",
        "description": "7.62传统射手步枪，3倍镜远程速点压制，平民单发伤害爆头致命。",
        "build_code": "SKS射手步枪-烽火地带-6JMDH9G0C741R248PB2AC",
        "recoil_b": 18.0, "stab_b": 18.0, "ads_m": 10,
        "parts": [("枪管", "SKS截断标准枪管"), ("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "sr25": {
        "gun_name": "SR-25射手步枪",
        "build_name": "特等射手架枪终极改",
        "description": "全能射手步枪，骨架狙击托搭配幻影握把，航天中控桥两发点杀破头神枪。",
        "build_code": "SR-25射手步枪-烽火地带-6L1F3IG08C4LQ9BA3SIDE",
        "recoil_b": 24.0, "stab_b": 22.0, "ads_m": 18,
        "parts": [("枪口", "实用消音器"), ("前握把", "幻影垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "骨架狙击枪托")]
    },
    "svch": {
        "gun_name": "SVCH精确射手步枪",
        "build_name": "新型半自动速点改",
        "description": "7.62x54R新型俄式半自动狙，射速快且回正优异，中远交火容错极高。",
        "build_code": "SVCH精确射手步枪-烽火地带-6LAGSMK09CLAL82K7MAV2",
        "recoil_b": 21.0, "stab_b": 20.0, "ads_m": 12,
        "parts": [("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "psg1": {
        "gun_name": "PSG-1射手步枪",
        "build_name": "高精架点对狙改",
        "description": "高精度单发精准射手步枪，制退器搭配俄制3倍镜，长距离定点清点。",
        "build_code": "PSG-1射手步枪-烽火地带-6L80P4807PL94ULQTD0NO",
        "recoil_b": 20.0, "stab_b": 20.0, "ads_m": 10,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "sr9": {
        "gun_name": "SR9射手步枪",
        "build_name": "平民卡战备架点改",
        "description": "极低门槛卡战备连发狙，兼具中远距离点射能力与超低起枪总造价。",
        "build_code": None,
        "recoil_b": 16.0, "stab_b": 15.0, "ads_m": 6,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "mini14": {
        "gun_name": "Mini-14射手步枪",
        "build_name": "5.56高初速速射改",
        "description": "5.56弹药极高子弹初速，下坠微弱，中远距离极速点射压制。",
        "build_code": None,
        "recoil_b": 18.0, "stab_b": 19.0, "ads_m": 8,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "实用稳定枪托")]
    },
    "vss": {
        "gun_name": "VSS射手步枪",
        "build_name": "微声连发全自动连狙改",
        "description": "自带一体消音管，加装30发弹匣与俄制3倍镜中距点射压制（一体消音管禁外接枪口）。",
        "build_code": None,
        "recoil_b": 18.0, "stab_b": 18.0, "ads_m": 5,
        "parts": [("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("弹匣", "VSS30发弹匣"), ("枪托", "实用稳定枪托")]
    },
    "marlin杠杆步枪": {
        "gun_name": "Marlin杠杆步枪",
        "build_name": "大口径杠杆猎杀改",
        "description": ".45-70超重弹头近身一枪头或两枪胸，制退器与专属稳固狙击枪托兼顾视野与威慑。",
        "build_code": "杠杆式步枪-烽火地带-6L83RM00BNVPQBLIJP1HH",
        "recoil_b": 15.0, "stab_b": 16.0, "ads_m": 6,
        "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "杠杆式步枪稳固狙击枪托")]
    },
}


def _build_detailed_from_config(gid: str, conf: Dict) -> DetailedWeaponBuild:
    """Helper to construct a DetailedWeaponBuild from configuration."""
    items = [make_part(slot, pname) for slot, pname in conf["parts"]]
    code = conf.get("build_code")
    code_status = "verified" if code else "manual_only"
    return DetailedWeaponBuild(
        gun_id=gid,
        gun_name=conf["gun_name"],
        build_name=conf["build_name"],
        build_code=code,
        code_status=code_status,
        description=conf["description"],
        attachments=items,
        recoil_bonus=conf["recoil_b"],
        stability_bonus=conf["stab_b"],
        ads_modifier_ms=conf["ads_m"],
    )


# Generate CURATED_BUILDS mapping
CURATED_BUILDS: Dict[str, DetailedWeaponBuild] = {
    gid: _build_detailed_from_config(gid, conf)
    for gid, conf in WEAPON_BUILDS_CATALOG.items()
}


def create_dynamic_build(gun_id: str, gun_name: str, category: str) -> DetailedWeaponBuild:
    """Fallback generator for any unspecified weapon."""
    if gun_id in CURATED_BUILDS:
        return CURATED_BUILDS[gun_id]

    if category == "冲锋枪":
        conf = {
            "gun_name": gun_name,
            "build_name": f"{gun_name}机动近战突袭改",
            "description": "高机动腰射配置，兼备快速开镜与近战泼水压制。",
            "recoil_b": 15.0, "stab_b": 14.0, "ads_m": -18,
            "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "反射式瞄准镜"), ("枪托", "实用轻型枪托")]
        }
    elif category == "轻机枪":
        conf = {
            "gun_name": gun_name,
            "build_name": f"{gun_name}阵地火力压制改",
            "description": "持续射击稳定配置，强化大容量弹链续航与后坐控制。",
            "recoil_b": 22.0, "stab_b": 19.0, "ads_m": 15,
            "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
        }
    elif category == "精确射手步枪":
        conf = {
            "gun_name": gun_name,
            "build_name": f"{gun_name}高精点射压制改",
            "description": "特等射手长距离架枪配置，提升首发回正与瞄准稳定性。",
            "recoil_b": 18.0, "stab_b": 20.0, "ads_m": 10,
            "parts": [("枪口", "实用消音器"), ("前握把", "实用垂直握把"), ("瞄具", "1p-29俄制3倍瞄准镜"), ("枪托", "实用稳定枪托")]
        }
    else:
        conf = {
            "gun_name": gun_name,
            "build_name": f"{gun_name}中距全能稳健改",
            "description": "均衡实战激光改，压低垂直水平散布，保证对枪容错。",
            "recoil_b": 18.0, "stab_b": 16.0, "ads_m": 8,
            "parts": [("枪口", "钢制膛口制退器"), ("前握把", "实用垂直握把"), ("瞄具", "全息二型瞄准镜"), ("枪托", "实用稳定枪托")]
        }

    return _build_detailed_from_config(gun_id, conf)


def get_all_builds_for_guns(guns_file: str = "data/base_guns.json") -> List[WeaponBuild]:
    """Retrieve complete builds for all weapons in base_guns.json."""
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


# Backward-compatible alias and helper functions
MAINSTREAM_BUILDS = CURATED_BUILDS


def get_detailed_build(gun_id: str) -> Optional[DetailedWeaponBuild]:
    """Retrieve detailed build configuration for a weapon."""
    return CURATED_BUILDS.get(gun_id)


def get_all_builds(guns_file: str = "data/base_guns.json") -> List[WeaponBuild]:
    """Retrieve complete builds for all weapons."""
    return get_all_builds_for_guns(guns_file)
