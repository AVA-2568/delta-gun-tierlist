"""zxfps「三角洲工具站」行情采集：主源（onebiji 市场全览）缺价时的回填源。

背景（2026-09-22）：onebiji 市场全览未收录部分武器与弹药（如 MDR、汤姆逊冲锋枪、
APC/+P 系弹药），而 zxfps 工具站（https://tool.zxfps.com）覆盖更全
（武器 68 / 子弹 113 / 头盔 73），且条目 ``pic`` URL 内嵌官方 objectID，
可与本仓目录精确对齐。

接口与签名（浏览器端公开 JS 逻辑，token.js + CryptoJS）：

- 列表接口：``GET /api/sjz/item_list?a=<分类>&top=1-2&p=<页>&grade=-1``
  分页每页 10 条；分类：``gun`` / ``ammo`` / ``helmet`` / ``armor`` …
- 签名：``h1 = md5(参数串 + 时间戳)``；
  ``token = md5(时间戳 + h1 + 盐串)``，盐串为站点公开 JS 内嵌的警示文案；
  最终请求 ``?参数&token=...&timestamp=...``。时间戳取自分类页内嵌
  ``var TimeUnix = <unix>``（服务器时间）。
- 官方 objectID：从条目 ``pic``（形如 ``.../object/<objectID>.png``）提取。

设计要点（与采集层一致）：

- 标准库 urllib + hashlib，**零第三方依赖**。
- 站点有 openresty 限流（连发约 2 请求即 403 空响应）：页间强制间隔、
  403 退避重试、重试失败则**返回已获数据**（缺价不猜测，主源数据不受影响）。
- 仅作**缺价回填**：调用方传入缺失 id 集合，本模块翻页收集到全部目标
  或列表耗尽即停，尽量减少请求量；每日 CI 调用一次，请求总量 ~20 次。
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

SOURCE_URL = "https://tool.zxfps.com"
SOURCE_NAME = "zxfps 三角洲工具站"

#: 分类页与列表接口（页面内嵌服务器时间戳，请求需带签名）
_PAGE_PATH = "/sjz/v/{a}"
_LIST_PATH = "/api/sjz/item_list"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

#: 站点 token.js 公开内嵌的签名盐串（警示文案，逐字符复制）
SIGN_SALT = "私自使用，后果自负！我方保留起诉权利！"

#: 条目 pic 形如 https://playerhub.df.qq.com/playerhub/60004/object/<objectID>.png
_OID_RE = re.compile(r"/object/(\d+)\.")

#: 每页 10 条；列表页数上限（防异常计数死循环）
_PAGE_SIZE = 10
_MAX_PAGES = 20

#: 请求间隔（秒）：站点限流敏感，宁慢勿封
REQUEST_INTERVAL_S = 2.0

#: 整体轮次上限：每轮换新会话从第 1 页重来（限流窗口长于单次退避时的兜底）
_MAX_ROUNDS = 3


def sign(params: str, timestamp: int) -> str:
    """复现站点公开 JS 的请求签名（与 token.js 输出逐位一致）。

    ``h1 = md5(params + timestamp)``；``token = md5(timestamp + h1 + 盐串)``。
    """
    h1 = hashlib.md5((params + str(timestamp)).encode("utf-8")).hexdigest()
    return hashlib.md5((str(timestamp) + h1 + SIGN_SALT).encode("utf-8")).hexdigest()


def object_id_of(item: Dict[str, Any]) -> Optional[str]:
    """从条目 ``pic`` 提取官方 objectID；无法提取返回 ``None``。"""
    match = _OID_RE.search(str(item.get("pic") or ""))
    return match.group(1) if match else None


class _Session:
    """单分类一次抓取的会话：独立 CookieJar + 间隔控制。"""

    def __init__(self, category: str, timeout: float = 60.0) -> None:
        self.category = category
        self.timeout = timeout
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        self.opener.addheaders = [
            ("User-Agent", _USER_AGENT),
            ("Accept", "*/*"),
            ("Referer", f"{SOURCE_URL}/sjz/v/{category}"),
        ]
        self._last_request_at: float = 0.0

    def get(self, url: str) -> str:
        """GET 一个 URL，强制请求间隔；403 时退避重试一次。"""
        wait = REQUEST_INTERVAL_S - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        for attempt in (1, 2):
            self._last_request_at = time.monotonic()
            try:
                with self.opener.open(url, timeout=self.timeout) as resp:
                    return resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                if exc.code == 403 and attempt == 1:
                    logger.info("zxfps 限流（403），退避后重试一次：%s", url)
                    time.sleep(REQUEST_INTERVAL_S * 2)
                    continue
                raise
        raise RuntimeError("unreachable")  # pragma: no cover


def _page_timestamp(session: _Session, category: str) -> int:
    """抓分类页，取内嵌服务器时间戳（签名素材）。"""
    html = session.get(SOURCE_URL + _PAGE_PATH.format(a=category))
    match = re.search(r"var TimeUnix = (\d+)", html)
    if not match:
        raise RuntimeError(f"分类页未内嵌时间戳：{category}")
    return int(match.group(1))


def collect_category_prices(
    category: str,
    wanted_ids: Iterable[str],
    max_pages: int = _MAX_PAGES,
    session_factory: Callable[[str], Any] = None,  # type: ignore[assignment]
) -> Dict[str, Dict[str, Any]]:
    """抓一个分类的物品列表，返回 ``官方objectID -> 条目``（仅含 wanted_ids 命中项）。

    翻页直到：目标 id 全部命中 / 列表耗尽 / 页数上限。限流（403）退避后
    **换新会话整轮重试**（最多 :data:`_MAX_ROUNDS` 轮）——限流窗口可能长于
    单次退避间隔。任何网络异常都不抛出——本模块只做回填，失败即返回已收集部分。
    """
    wanted = {str(i) for i in wanted_ids}
    if not wanted:
        return {}
    found: Dict[str, Dict[str, Any]] = {}
    factory = session_factory or _Session
    for round_index in range(1, _MAX_ROUNDS + 1):
        try:
            session = factory(category)
            timestamp = _page_timestamp(session, category)
            exhausted = False
            for page in range(1, max_pages + 1):
                params = f"a={category}&top=1-2&p={page}&grade=-1"
                query = f"{_LIST_PATH}?{params}&token={sign(params, timestamp)}&timestamp={timestamp}"
                body = json.loads(session.get(SOURCE_URL + query))
                if body.get("code") != 0:
                    logger.info("zxfps 列表返回异常（page=%d code=%s）", page, body.get("code"))
                    break
                rows = body.get("data") or []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    object_id = object_id_of(row)
                    price = row.get("price")
                    if object_id in wanted and object_id not in found and isinstance(price, int) and price > 0:
                        found[object_id] = {
                            "name": str(row.get("name") or ""),
                            "price": price,
                            "day_7_price": row.get("day_7_price"),
                            "day_30_price": row.get("day_30_price"),
                        }
                if wanted <= found.keys():  # 目标全部命中 → 早退，省请求
                    exhausted = True
                    break
                total = body.get("count") or 0
                if not rows or len(rows) < _PAGE_SIZE or page * _PAGE_SIZE >= total:
                    exhausted = True
                    break
            if exhausted or wanted <= found.keys():
                break  # 本轮走完整表 / 目标已拿全 → 不再重试
            logger.info(
                "zxfps 第 %d 轮中断（已命中 %d/%d），换新会话重试",
                round_index, len(found), len(wanted),
            )
            time.sleep(REQUEST_INTERVAL_S * 5)  # 轮间长退避，等限流窗口过去
        except Exception as exc:  # noqa: BLE001 - 回填源任何失败都不致命
            logger.warning(
                "zxfps 回填第 %d 轮中断（%s：%s），已收集 %d 条",
                round_index, type(exc).__name__, exc, len(found),
            )
            if round_index < _MAX_ROUNDS:
                time.sleep(REQUEST_INTERVAL_S * 5)
    logger.info("zxfps %s 分类命中 %d / %d 个目标", category, len(found), len(wanted))
    return found


def collect_missing_prices(
    category: str,
    missing_ids: Iterable[str],
    session_factory: Callable[[str], Any] = None,  # type: ignore[assignment]
) -> Dict[str, int]:
    """回填入口：返回 ``官方objectID -> 当日价``（仅含成功命中的缺失 id）。"""
    found = collect_category_prices(
        category, missing_ids, session_factory=session_factory,
    )
    return {object_id: int(row["price"]) for object_id, row in found.items()}
