"""orzice「三角洲小涛查」行情采集 → ``weapon_prices.json`` + ``ammo_prices.json``。

替代 onebiji（主源）+ zxfps（回填）双源，单源一次运行写出两张表。

数据源与口径（2026-09-30 实地确认的页面格式）：

- ``https://orzice.com/v/zhanbei?p=N`` 战备页（头盔/护甲/枪械/胸挂/背包/配件），
  共约 814 条、10 条/页：条目名在 ``class="ui-tname"``，当日价在第一个
  ``class="icon-gold ui-num"``（两种形态：``"68,035"`` 千分位、或 Vue 模板
  ``{{NumQfw(25630)}}``）；官方 objectID 从 ``pic:'…/object/<11位数字>.png`` 提取。
  只保留 objectID 命中 ``weapons.json`` weapon_id 集合的枪械条目，其余（配件/装备）忽略。
- ``https://orzice.com/v/ammo?p=N`` 弹药页约 10 页，格式同上；条目 ``pic`` 多为泛口径图
  （无 objectID，少数条目如 45-70 系/箭矢带官方 objectID）。有正价的条目按三层对齐：
  ① objectID 命中官方目录 → 精确匹配；② 「口径+名称」归一化（剥引号/空白/连字符/mm、
  行名字级别名折叠）与官方 ``ammo.json`` 目录**全等唯一匹配**；③ 行名形如
  ``<口径>_N`` 的合并行情行（口径_N = 口径 + N 级弹）按 (归一化口径, N) 组匹配，
  组内唯一 → 对齐，多条 → ambiguous（候选条目落 ``null`` + ``note`` 记候选集，
  待人工确认）。撞名键弃用、匹配不上或价格 0 → ``null``
  （赛季限定弹市场无流通落 ``null`` 是预期正确行为，不猜价）。
  同一 ammo_item_id 命中多行情行时取**全行最小价**并 ``note`` 记全部行名与价
  （站内页序非确定性，弃「取首行」）。

设计要点：

- 标准库 urllib，**零第三方依赖**（与采集层一致）。
- 请求串行、间隔 2s、真实浏览器 UA，宁慢勿封；403 退避 60s 重试一次，
  仍失败即停止翻页并写已获部分结果（退出码 0 + 日志警告），绝不并发、绝不高频重试。
- 空页（站点 404 文案页，无条目行）即翻页终止。
- 仅 https 且 host 必须为 ``orzice.com``，并解析 DNS 拒绝环回/私有/保留地址。
- 落盘安全：输出根目录先经 :func:`_safe_output_root` 规范化并拒绝上级目录分量，
  随后工作目录切至该根，所有文件系统调用一律使用**纯字符串字面量相对路径**——
  写入点不接触任何参数、变量或拼接结果，结构上不存在目录逃逸（禁路径穿越）。
- 确定性输出：条目按 id 排序，无时间戳漂移进数据体；**幂等**——解析出的价格
  （含 note）与现表完全一致时不重写文件（git 无 diff、Actions 无空提交），
  ``updated_at`` 语义 = 当前表内价格的抓取日。
- 缺价不猜测：装备名条件后缀（（全新）（几乎全新）（破损））剥掉取本体；
  名称归一化全等唯一才命中，宁漏配不错配。
- 抓取完整性护栏：有价条数较现表骤降 ≥10% 时告警（部分结果仍落盘），
  未匹配行情行 WARNING 日志积累别名清单（不静默）。
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from src.collectors.normalize import MERGED_AMMO_IDS

logger = logging.getLogger(__name__)

SOURCE_BASE = "https://orzice.com"
SOURCE_NAME = "orzice 三角洲小涛查"

#: 允许抓取的唯一 host（发请求前强制校验，拒绝其余一切主机）
ALLOWED_HOST = "orzice.com"

ZHANBEI_PATH = "/v/zhanbei"
AMMO_PATH = "/v/ammo"

#: 两张价格表的 schema（与现行文件完全一致）
WEAPON_PRICE_SCHEMA = "weapon-price-daily"
AMMO_PRICE_SCHEMA = "ammo-price-daily"

#: 返回值里的表路径文案（sync 内文件系统调用一律用纯字面量相对路径，不用本常量）
WEAPON_TABLE_RELPATH = "data/reference/weapon_prices.json"
AMMO_TABLE_RELPATH = "data/reference/ammo_prices.json"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

#: 请求间隔（秒）：串行慢抓，宁慢勿封
REQUEST_INTERVAL_S = 2.0
#: 403 退避（秒）：退避 60s 后重试一次，再失败即停（部分结果）
BACKOFF_403_S = 60.0
#: 页数上限（战备页约 82 页 + 冗余，防异常计数死循环；翻页以空页终止为准，不写死页数）
MAX_PAGES = 200
DEFAULT_TIMEOUT_S = 60.0

#: 有价条数骤降告警阈值：较现表下降 ≥10% 视为疑似抓取不完整
PRICED_DROP_WARN_RATIO = 0.9

# ---- 页面解析 ----
#: 行内条目名 / 价格单元格 / 官方 objectID（pic 为泛口径图时提取不到）
_TNAME_RE = re.compile(r'class="ui-tname">([^<]*)<')
_NUM_RE = re.compile(r'icon-gold ui-num">([^<]*)<')
_NUMQFW_RE = re.compile(r"\{\{\s*NumQfw\(\s*(\d+)\s*\)\s*\}\}")
_OID_RE = re.compile(r"/object/(\d+)\.png")
#: 装备条目名的成色后缀（半/全角括号）：统一剥掉取本体
_COND_SUFFIX_RE = re.compile(r"\s*[（(]\s*(?:全新|几乎全新|破损)\s*[）)]\s*$")
#: orzice 合并行情行 ``<口径>_N``（口径_N = 口径 + N 级弹；2026-09-30 实证仅 .300BLK 3 行）
_LEVEL_ROW_RE = re.compile(r"^(.+)_(\d)$")

#: 行名字级别名（站方行名 → 官方目录名写法；行情考古 2026-09-30 实证）。
#: 仅折叠**行名侧**（官方目录名不折叠，避免目录侧别名制造撞名键）；
#: 无法证明已穷尽——未匹配行 WARNING 日志积累新别名。
NAME_ALIASES: Dict[str, str] = {
    "箭形": "箭型",
    "鼠弹": "鼠蛋",
    "DART": "箭型弹",
}


class SourceUnavailable(RuntimeError):
    """行情源不可用。"""


def strip_condition_suffix(name: str) -> str:
    """剥掉条目名尾部的成色后缀（（全新）（几乎全新）（破损），半/全角括号）。"""
    name = str(name or "")
    while True:
        stripped = _COND_SUFFIX_RE.sub("", name)
        if stripped == name:
            return name.strip()
        name = stripped


def parse_price(text: str) -> Optional[int]:
    """解析价格单元格：``"68,035"`` 千分位 / ``{{NumQfw(25630)}}`` 模板 / 纯数字。

    无法解析返回 ``None``（缺价不猜测，不做任何换算）。
    """
    text = str(text or "").strip()
    match = _NUMQFW_RE.fullmatch(text)
    if match:
        return int(match.group(1))
    digits = re.sub(r"[,\s]", "", text)
    return int(digits) if digits.isdigit() else None


def parse_rows(page_html: str) -> List[Dict[str, Any]]:
    """解析行情页为条目行列表。

    每行取：条目名（剥成色后缀）、**第一个** ``icon-gold ui-num``（当前价格列，
    后面的 3日/7日/30日价格列不用）、``pic`` 里的官方 objectID（泛口径图为 ``None``）。
    价格为 0 / 缺失 / 无法解析 → ``None``（缺价不猜测）。
    """
    rows: List[Dict[str, Any]] = []
    for chunk in page_html.split("<tr>"):
        name_match = _TNAME_RE.search(chunk)
        if not name_match:
            continue  # 表头/页框等非条目行
        nums = _NUM_RE.findall(chunk)
        price = parse_price(nums[0]) if nums else None
        oid_match = _OID_RE.search(chunk)
        rows.append(
            {
                # 站方行名的引号等字符以 HTML 实体下发（如 9号霰射&#34;鼠弹&#34;），
                # 先解码再做成色剥除与归一化，否则引号别名链在此断裂（落 null）
                "name": strip_condition_suffix(html.unescape(name_match.group(1))),
                "price": price if price is not None and price > 0 else None,
                "object_id": oid_match.group(1) if oid_match else None,
            }
        )
    return rows


# ---- 网络层：host 校验 + 串行抓取 + 翻页 ----
def assert_public_https(url: str, resolve: Callable = socket.getaddrinfo) -> None:
    """发请求前校验 URL：仅 https、host 必须为 orzice.com，且解析结果非环回/私有/保留地址。"""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"仅允许 https，拒绝：{url}")
    host = (parsed.hostname or "").lower()
    if host != ALLOWED_HOST:
        raise ValueError(f"host 不在允许名单（期望 {ALLOWED_HOST}），拒绝：{host}")
    for info in resolve(host, 443):
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"{host} 解析到非公网地址 {ip}，拒绝请求")


def fetch_page(path: str, page: int, timeout: float = DEFAULT_TIMEOUT_S) -> str:
    """抓取一个分页页面的 HTML（自带 host 校验与浏览器 UA）。"""
    url = f"{SOURCE_BASE}{path}?p={page}"
    assert_public_https(url)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError:
        raise  # 403/404 等状态码由翻页层按策略处理
    except Exception as exc:  # noqa: BLE001 - 网络异常统一包装
        raise SourceUnavailable(f"页面下载失败：{type(exc).__name__} - {exc}") from exc


def crawl_pages(
    path: str,
    fetch: Callable[..., str],
    *,
    interval: float = REQUEST_INTERVAL_S,
    backoff_403_s: float = BACKOFF_403_S,
    max_pages: int = MAX_PAGES,
    sleep: Callable[[float], None] = time.sleep,
) -> Tuple[List[Dict[str, Any]], bool]:
    """串行翻页抓取一个列表，返回 ``(全部条目行, 是否完整抓完)``。

    翻页终止：空页（站点 404 文案页无条目行）或 HTTP 404 → 正常终止（完整）；
    403 → 退避 :data:`BACKOFF_403_S` 重试一次，仍失败 → 停止并返回已获部分
    （``complete=False``）；其余网络异常同样停止返回部分结果。
    任何情况下不并发、不高频重试。
    """
    rows: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        html: Optional[str] = None
        for attempt in (1, 2):
            sleep(interval)
            try:
                html = fetch(path, page)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    html = ""  # 越界页 → 翻页终止
                    break
                if exc.code == 403 and attempt == 1:
                    logger.warning(
                        "orzice 403，退避 %gs 后重试一次：%s?p=%s", backoff_403_s, path, page
                    )
                    sleep(backoff_403_s)
                    continue
                logger.warning(
                    "orzice 抓取失败（HTTP %s），停止翻页并保存已获数据：%s?p=%s",
                    exc.code, path, page,
                )
                return rows, False
            except Exception as exc:  # noqa: BLE001 - 其余异常停止翻页，保留部分结果
                logger.warning(
                    "orzice 抓取异常（%s：%s），停止翻页并保存已获数据：%s?p=%s",
                    type(exc).__name__, exc, path, page,
                )
                return rows, False
        page_rows = parse_rows(html or "")
        if not page_rows:
            break  # 空页 → 列表耗尽，正常终止
        rows.extend(page_rows)
        page += 1
    else:
        logger.warning("orzice 达到页数上限 %d，停止翻页：%s", max_pages, path)
        return rows, False
    return rows, True


# ---- 官方目录 ----
def load_weapon_catalog(path: str) -> Dict[str, Dict[str, Any]]:
    """读官方武器目录，返回 ``weapon_id -> 展示元数据``（仅本体，供全量表骨架）。

    官方变体条目（``is_variant=true``）跳过：变体 = 本体 + 预装改件，
    不存在独立的"变体枪"商品，同枪所有状态行共用本体价。
    """
    with open(path, encoding="utf-8") as fh:
        catalog = json.load(fh)
    return {
        str(record["weapon_id"]): {
            "name": record.get("name") or "",
            "category": record.get("category") or "",
            "caliber": record.get("caliber") or "",
        }
        for record in catalog.get("weapons", [])
        if record.get("weapon_id") and not record.get("is_variant")
    }


def load_ammo_catalog(path: str) -> Dict[str, Dict[str, Any]]:
    """读官方弹药目录，返回 ``ammo_item_id -> 展示元数据``（供全量表骨架）。

    被 :data:`src.collectors.normalize.MERGED_AMMO_IDS` 合并的条目不进骨架
    （合并 = 条目从目录消失；防御陈旧 ammo.json 残留被并 id）。
    """
    with open(path, encoding="utf-8") as fh:
        catalog = json.load(fh)
    return {
        str(record["ammo_item_id"]): {
            "caliber": record.get("caliber") or "",
            "name": record.get("name") or "",
            "penetration_level": record.get("penetration_level"),
        }
        for record in catalog.get("ammo", [])
        if record.get("ammo_item_id") and str(record["ammo_item_id"]) not in MERGED_AMMO_IDS
    }


def fold_name_aliases(name: Any) -> str:
    """行名字级别名折叠（站方行名 → 官方目录名写法），归一化前应用。"""
    name = str(name or "")
    for variant, canonical in NAME_ALIASES.items():
        if variant in name:
            name = name.replace(variant, canonical)
    return name


def norm_name(name: Any) -> str:
    """名称归一化：小写，去空白（含全角空格/\\xa0）、直弯引号、连字符与口径单位 ``mm``。

    orzice 展示名与官方目录写法不一：``12.7x55mm PS12`` vs 官方口径 ``12.7x55``、
    ``.45-ACP`` vs ``.45 ACP``、``7.62x51mm\\xa0Ultra\\xa0Nosler`` 含 \\xa0、
    站方直引号 ``"鼠弹"`` vs 官方弯引号 ``“鼠蛋”``（引号风格不统一）。
    两侧同规则归一化后全等才命中；已核验 mm/引号剔除不产生键碰撞。
    """
    return re.sub(r"mm|[\"'\u2018\u2019\u201c\u201d\s\-]+", "", str(name or "").lower())


def build_ammo_name_map(catalog: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """构建「归一化(口径+名称) → ammo_item_id」映射，供泛口径图条目（无 objectID）识别。

    仅收官方目录内归一化键**唯一**的条目；撞名键整组弃用（宁漏配不错配）。
    """
    keys: Dict[str, List[str]] = {}
    for item_id, meta in catalog.items():
        key = norm_name(f"{meta.get('caliber')} {meta.get('name')}")
        keys.setdefault(key, []).append(str(item_id))
    dropped = {key: ids for key, ids in keys.items() if len(ids) > 1}
    if dropped:
        logger.warning("弹药目录撞名键弃用 %d 个（宁漏配不错配）：%s", len(dropped), sorted(dropped))
    return {key: ids[0] for key, ids in keys.items() if len(ids) == 1}


# ---- 行 → 价格 ----
def match_weapon_prices(
    rows: List[Dict[str, Any]], weapon_ids: Set[str]
) -> Dict[str, int]:
    """战备页条目 → ``weapon_id -> 当日价``：仅保留 objectID 命中目录且价格为正的条目。

    同一 weapon_id 多行（如不同成色/多次上架）价不一致时取首行并告警（确定性）。
    """
    prices: Dict[str, int] = {}
    for row in rows:
        object_id = row.get("object_id")
        price = row.get("price")
        if object_id not in weapon_ids or not price:
            continue
        if object_id in prices and prices[object_id] != price:
            logger.warning("枪械 %s 多行价不一致（%d / %d），取首行", object_id, prices[object_id], price)
            continue
        prices[object_id] = price
    return prices


def _resolve_ammo_row(
    row: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
    name_map: Dict[str, str],
) -> Tuple[Optional[str], Optional[List[str]]]:
    """行 → ``(item_id, None)`` 或 ``(None, ambiguous 候选 id 列表)`` 或 ``(None, None)``。

    三层对齐（宁漏配不错配）：
    ① objectID 命中官方目录 → 精确匹配；
    ② 归一化「口径+名称」（行名先做别名折叠）全等唯一 → 命中；
    ③ 行名 ``<口径>_N`` 合并行 → (归一化口径, N) 组匹配：组内唯一 → 命中，
       多条 → ambiguous（数据层永不硬指变体归属）。
    """
    object_id = row.get("object_id")
    if object_id and object_id in catalog:
        return str(object_id), None
    row_name = fold_name_aliases(row["name"])
    item_id = name_map.get(norm_name(row_name))
    if item_id:
        return item_id, None
    level_row = _LEVEL_ROW_RE.match(row_name.strip())
    if level_row:
        caliber_key = norm_name(level_row.group(1))
        level = int(level_row.group(2))
        candidates = sorted(
            item_id
            for item_id, meta in catalog.items()
            if norm_name(str(meta.get("caliber") or "")) == caliber_key
            and meta.get("penetration_level") == level
        )
        if len(candidates) == 1:
            return candidates[0], None
        if len(candidates) > 1:
            return None, candidates
    return None, None


def match_ammo_prices(
    rows: List[Dict[str, Any]],
    catalog: Dict[str, Dict[str, Any]],
    name_map: Dict[str, str],
) -> Tuple[Dict[str, int], Dict[str, str]]:
    """弹药页条目 → ``ammo_item_id -> 当日价`` 与逐条 ``note``。

    返回 ``(prices, notes)``。价格确定性：同一 ammo_item_id 命中多行情行时取
    **全行最小价**（站内页序非确定性，弃「取首行」），``note`` 记全部行名与价；
    ambiguous 行的候选条目落 ``null``，``note`` 记行情价与候选集（待人工确认）。
    匹配不上（含无候选/组为空）的有价行 WARNING 日志（积累别名清单，不静默）。
    """
    prices: Dict[str, int] = {}
    min_source_notes: Dict[str, str] = {}
    ambiguous_notes: Dict[str, str] = {}
    hits: Dict[str, List[Tuple[str, int]]] = {}
    for row in rows:
        price = row.get("price")
        if not price:
            continue
        item_id, ambiguous = _resolve_ammo_row(row, catalog, name_map)
        if item_id:
            hits.setdefault(item_id, []).append((str(row["name"]), int(price)))
            continue
        if ambiguous:
            candidates_text = ", ".join(
                f"{cid} {catalog[cid]['name']}" for cid in ambiguous
            )
            note = f"orzice {row['name']}={price}; candidates=[{candidates_text}]; 待人工确认"
            for candidate_id in ambiguous:
                existing = ambiguous_notes.get(candidate_id)
                ambiguous_notes[candidate_id] = f"{existing} | {note}" if existing else note
        else:
            logger.warning(
                "orzice 有价行无法匹配官方目录（落 null，积累别名清单）：%s=%s",
                row["name"], price,
            )

    for item_id, row_hits in hits.items():
        prices[item_id] = min(price for _, price in row_hits)
        if len(row_hits) > 1:
            min_source_notes[item_id] = "orzice " + "; ".join(
                f"{name}={price}" for name, price in row_hits
            )
    # 候选条目被其他行精确命中的极端情形：以实价为准，撤掉 ambiguous note（多源 min note 不受影响）
    notes = {
        cid: note for cid, note in ambiguous_notes.items() if cid not in prices
    }
    notes.update(min_source_notes)
    return prices, notes


# ---- 表构造与幂等写盘 ----
def _safe_output_root(output_dir: str) -> str:
    """规范化输出根目录：字面量含上级目录分量即拒绝（防路径拼接逃逸）。

    sync 随后把工作目录切到该根并只使用纯字符串字面量相对路径读写，
    外部传入的目录串不接触任何文件写入点。
    """
    output_dir = str(output_dir or ".")
    if ".." in os.path.normpath(output_dir).replace("\\", "/").split("/"):
        raise ValueError(f"output-dir 不允许路径穿越，拒绝：{output_dir}")
    return os.path.realpath(os.path.abspath(output_dir))


def _today_beijing() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d")


def build_weapon_table(
    catalog: Dict[str, Dict[str, Any]], prices: Dict[str, int], fetched_date: str
) -> Dict[str, Any]:
    """构造枪械价格表：官方目录全量本体条目，命中填价，未命中 ``null``（缺价不猜测）。"""
    return {
        "schema": WEAPON_PRICE_SCHEMA,
        "currency": "哈夫币",
        "window": {"from": fetched_date, "to": fetched_date, "days": 1},
        "updated_at": fetched_date,
        "source": f"{SOURCE_NAME} · 战备页交易行实时价（本体裸枪当日价）",
        "note": (
            "自动维护：每日 GitHub Actions 抓取 orzice 小涛查实时价；"
            "交易行无报价的枪械为 null（渲染为 —），变体共用本体价（配件价不计入），"
            "非官方数据仅供参考"
        ),
        "weapons": [
            {"weapon_id": item_id, **meta, "price_daily": prices.get(item_id)}
            for item_id, meta in sorted(catalog.items())
        ],
    }


def build_ammo_table(
    catalog: Dict[str, Dict[str, Any]],
    prices: Dict[str, int],
    fetched_date: str,
    notes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """构造弹药价格表：官方目录全量条目，命中填价，未命中 ``null``（缺价不猜测）。

    ``notes`` 为可选逐条备注（多源取 min 的全源价 / ambiguous 候选集），
    仅有值时输出 ``note`` 字段（向后兼容扩展：消费方只读 ``price_daily``）。
    """
    note_by_id = notes or {}
    return {
        "schema": AMMO_PRICE_SCHEMA,
        "currency": "哈夫币",
        "window": {"from": fetched_date, "to": fetched_date, "days": 1},
        "updated_at": fetched_date,
        "source": f"{SOURCE_NAME} · 弹药页交易行实时价（泛口径条目按官方目录口径+名称全等唯一匹配）",
        "note": (
            "自动维护：每日 GitHub Actions 抓取 orzice 小涛查实时价；"
            "交易行无报价/匹配不上官方目录的弹药为 null（渲染为 —，含赛季限定弹），"
            "note 记多源价或 ambiguous 候选集（待人工确认），"
            "非官方数据仅供参考"
        ),
        "ammo": [
            {
                "ammo_item_id": item_id,
                **meta,
                "price_daily": prices.get(item_id),
                **({"note": note_by_id[item_id]} if item_id in note_by_id else {}),
            }
            for item_id, meta in sorted(catalog.items())
        ],
    }


def _load_current_table(table_path: str, schema: str) -> Optional[Dict[str, Any]]:
    """读现表（只读）：缺失/损坏/schema 不符 → ``None``。"""
    if not os.path.exists(table_path):
        return None
    try:
        with open(table_path, encoding="utf-8") as fh:
            current = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(current, dict) or current.get("schema") != schema:
        return None
    return current


def _table_priced_count(current: Optional[Dict[str, Any]], section: str) -> int:
    """现表内有价（price_daily 非空）条数，供骤降告警基线。"""
    if not current:
        return 0
    return sum(
        1
        for row in current.get(section) or []
        if isinstance(row, dict) and row.get("price_daily") is not None
    )


def _table_prices_match(
    table_path: str,
    table: Dict[str, Any],
    *,
    schema: str,
    section: str,
    id_field: str,
) -> bool:
    """现表与本次解析出的价格（含 note）是否逐条一致（幂等判据，只读不写）。"""
    current = _load_current_table(table_path, schema)
    if current is None:
        return False
    current_prices = {
        str(row.get(id_field)): (row.get("price_daily"), row.get("note"))
        for row in current.get(section) or []
        if isinstance(row, dict)
    }
    new_prices = {
        str(row[id_field]): (row["price_daily"], row.get("note"))
        for row in table[section]
    }
    return current_prices == new_prices and current.get("currency") == table["currency"]


# ---- 编排 ----
def sync(
    output_dir: str = ".",
    timeout: float = DEFAULT_TIMEOUT_S,
    interval: float = REQUEST_INTERVAL_S,
    backoff_403_s: float = BACKOFF_403_S,
    max_pages: int = MAX_PAGES,
    fetch: Optional[Callable[..., str]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    """执行同步：抓战备页+弹药页 → 解析匹配 → 构造两张表 → 幂等写盘。

    Args:
        output_dir: 输出根目录（官方目录与两张价格表都相对它解析），
            不允许含上级目录分量；sync 会把工作目录临时切到该根，
            全部文件系统调用使用纯字面量相对路径（外部路径不接触写入点）。
        fetch: 页面抓取函数 ``fetch(path, page) -> html``（测试注入用），
            默认走真实网络（:func:`fetch_page`，带 host 校验）。
        sleep: 等待函数（间隔与 403 退避共用，测试注入用）。

    Returns:
        ``{"complete": bool, "weapon": {...}, "ammo": {...}}``；抓取中断时
        ``complete=False`` 并写已获部分结果（调用方退出码 0 + 日志警告）。
    """
    root = _safe_output_root(output_dir)
    fetcher = fetch or (lambda path, page: fetch_page(path, page, timeout=timeout))

    weapon_rows, weapon_complete = crawl_pages(
        ZHANBEI_PATH, fetcher, interval=interval, backoff_403_s=backoff_403_s,
        max_pages=max_pages, sleep=sleep,
    )
    ammo_rows, ammo_complete = crawl_pages(
        AMMO_PATH, fetcher, interval=interval, backoff_403_s=backoff_403_s,
        max_pages=max_pages, sleep=sleep,
    )

    prev_cwd = os.getcwd()
    os.chdir(root)
    try:
        weapon_catalog = load_weapon_catalog("data/game/weapons.json")
        if not weapon_catalog:
            raise RuntimeError("官方武器目录为空或缺失：data/game/weapons.json")
        ammo_catalog = load_ammo_catalog("data/game/ammo.json")
        if not ammo_catalog:
            raise RuntimeError("官方弹药目录为空或缺失：data/game/ammo.json")

        weapon_prices = match_weapon_prices(weapon_rows, set(weapon_catalog))
        ammo_prices, ammo_notes = match_ammo_prices(
            ammo_rows, ammo_catalog, build_ammo_name_map(ammo_catalog)
        )

        # ---- 抓取完整性护栏：有价条数较现表骤降 ≥10% 告警（部分结果仍落盘）----
        prev_weapon_priced = _table_priced_count(
            _load_current_table("data/reference/weapon_prices.json", WEAPON_PRICE_SCHEMA),
            "weapons",
        )
        if prev_weapon_priced and len(weapon_prices) < prev_weapon_priced * PRICED_DROP_WARN_RATIO:
            logger.warning(
                "枪械有价条数骤降：%d → %d（≥10%%，疑似抓取不完整或站点改版，部分结果仍落盘）",
                prev_weapon_priced, len(weapon_prices),
            )
        prev_ammo_priced = _table_priced_count(
            _load_current_table("data/reference/ammo_prices.json", AMMO_PRICE_SCHEMA),
            "ammo",
        )
        if prev_ammo_priced and len(ammo_prices) < prev_ammo_priced * PRICED_DROP_WARN_RATIO:
            logger.warning(
                "弹药有价条数骤降：%d → %d（≥10%%，疑似抓取不完整或站点改版，部分结果仍落盘）",
                prev_ammo_priced, len(ammo_prices),
            )

        fetched_date = _today_beijing()
        weapon_table = build_weapon_table(weapon_catalog, weapon_prices, fetched_date)
        ammo_table = build_ammo_table(ammo_catalog, ammo_prices, fetched_date, notes=ammo_notes)

        # ---- 幂等写盘：价格与现表一致时不重写（git 无 diff、Actions 无空提交）----
        weapon_changed = not _table_prices_match(
            "data/reference/weapon_prices.json", weapon_table,
            schema=WEAPON_PRICE_SCHEMA, section="weapons", id_field="weapon_id",
        )
        if weapon_changed:
            os.makedirs("data/reference", exist_ok=True)
            weapon_payload = json.dumps(weapon_table, ensure_ascii=False, indent=1) + "\n"
            Path("data/reference/weapon_prices.json").write_text(weapon_payload, encoding="utf-8")
            logger.info(
                "枪械价格表已更新：matched=%d / catalog=%d",
                len(weapon_prices), len(weapon_catalog),
            )
        else:
            logger.info("枪械价格与现表一致，不重写（matched=%d）", len(weapon_prices))

        ammo_changed = not _table_prices_match(
            "data/reference/ammo_prices.json", ammo_table,
            schema=AMMO_PRICE_SCHEMA, section="ammo", id_field="ammo_item_id",
        )
        if ammo_changed:
            ammo_payload = json.dumps(ammo_table, ensure_ascii=False, indent=1) + "\n"
            Path("data/reference/ammo_prices.json").write_text(ammo_payload, encoding="utf-8")
            logger.info(
                "弹药价格表已更新：matched=%d / catalog=%d",
                len(ammo_prices), len(ammo_catalog),
            )
        else:
            logger.info("弹药价格与现表一致，不重写（matched=%d）", len(ammo_prices))
    finally:
        os.chdir(prev_cwd)

    complete = weapon_complete and ammo_complete
    if not complete:
        logger.warning(
            "orzice 抓取不完整（战备页 %s、弹药页 %s），已写入部分结果",
            "完整" if weapon_complete else "中断", "完整" if ammo_complete else "中断",
        )
    return {
        "complete": complete,
        "weapon": {
            "changed": weapon_changed,
            "matched": len(weapon_prices),
            "catalog": len(weapon_catalog),
            "table_path": WEAPON_TABLE_RELPATH,
        },
        "ammo": {
            "changed": ammo_changed,
            "matched": len(ammo_prices),
            "catalog": len(ammo_catalog),
            "table_path": AMMO_TABLE_RELPATH,
        },
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="orzice 小涛查行情同步（枪械+弹药当日价）")
    parser.add_argument("--output-dir", default=".", help="输出根目录（默认当前目录）")
    args = parser.parse_args()

    result = sync(output_dir=_safe_output_root(args.output_dir))
    state = "完整" if result["complete"] else "部分（抓取中断，详见日志警告）"

    def _part(key: str, label: str) -> str:
        r = result[key]
        return (
            f"{label} {r['matched']}/{r['catalog']} 条"
            f"（{'已更新' if r['changed'] else '无变化'} → {r['table_path']}）"
        )

    print(f"orzice 价格同步完成（{state}）：{_part('weapon', '枪械')}，{_part('ammo', '弹药')}")


if __name__ == "__main__":
    main()
