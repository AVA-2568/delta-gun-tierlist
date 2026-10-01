"""上游 HTTP 拉取（无磁盘缓存）。

从 :mod:`src.collectors.game_data_sync` 抽出。依赖方向：http → 标准库（无同仓库依赖）。
game_data_sync 单向 import 本模块；本模块**不** import game_data_sync。

``SOURCE_BASE`` 定义在此（下载层的自有常量）；编排方 ``sync_all`` 仅为了把
``base_url`` 写进 provenance 而反向 import 它，方向为 game_data_sync → http，无环。

历史版本带 ``.cache`` 磁盘缓存，2026-09-30 移除：缓存只服务本地重跑
（CI 冷启动本就无缓存），却让下载层承担文件写入面；移除后本模块无任何
文件系统调用，仅剩出站请求。

安全约定（Mimosa 门禁）：出站请求仅允许 https、host 必须为 ``ALLOWED_HOST``
（dfttk.com），且 DNS 解析结果逐一拒绝环回/私有/链路本地/保留/组播/未指定
地址，见 :func:`assert_public_https`。
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import urllib.parse
import urllib.request
from typing import Any, Callable, Tuple

SOURCE_BASE = "https://dfttk.com/data/v3/"
#: 出站请求的唯一允许 host（与 SOURCE_BASE 一致）
ALLOWED_HOST = "dfttk.com"


class SourceUnavailable(RuntimeError):
    """上游数据不可用。"""


def assert_public_https(url: str, resolve: Callable = socket.getaddrinfo) -> None:
    """发请求前校验 URL：仅 https、host 必须为 ``ALLOWED_HOST``，且解析结果非环回/私有/保留地址。"""
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


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _download(path: str, timeout: float = 120.0) -> bytes:
    """下载单个上游文件，返回原始字节。出站前做 https/host/解析 IP 三重校验。"""
    url = SOURCE_BASE + path
    assert_public_https(url)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; delta-gun-tierlist)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as exc:  # pragma: no cover - 网络异常分支
        raise SourceUnavailable(f"下载 {url} 失败：{type(exc).__name__} - {exc}") from exc


def _download_json(path: str, timeout: float = 120.0) -> Tuple[Any, str]:
    payload = _download(path, timeout=timeout)
    return json.loads(payload.decode("utf-8")), _sha256_bytes(payload)
