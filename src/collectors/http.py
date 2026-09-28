"""上游 HTTP 拉取与磁盘缓存。

从 :mod:`src.collectors.game_data_sync` 抽出。依赖方向：http → 标准库（无同仓库依赖）。
game_data_sync 单向 import 本模块；本模块**不** import game_data_sync。

``SOURCE_BASE`` 定义在此（下载层的自有常量）；编排方 ``sync_all`` 仅为了把
``base_url`` 写进 provenance 而反向 import 它，方向为 game_data_sync → http，无环。
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from typing import Any, Tuple

SOURCE_BASE = "https://dfttk.com/data/v3/"


class SourceUnavailable(RuntimeError):
    """上游数据不可用。"""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _download(path: str, cache_dir: str, timeout: float = 120.0, refresh: bool = False) -> bytes:
    """下载单文件，带磁盘缓存。缓存命中时直接返回，避免重复流量。"""
    cache_path = os.path.join(cache_dir, path.replace("/", "__"))
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    if os.path.exists(cache_path) and not refresh:
        with open(cache_path, "rb") as fh:
            return fh.read()
    url = SOURCE_BASE + path
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; delta-gun-tierlist)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:  # pragma: no cover - 网络异常分支
        raise SourceUnavailable(f"下载 {url} 失败：{type(exc).__name__} - {exc}") from exc
    with open(cache_path, "wb") as fh:
        fh.write(payload)
    return payload


def _download_json(path: str, cache_dir: str, timeout: float = 120.0, refresh: bool = False) -> Tuple[Any, str]:
    payload = _download(path, cache_dir, timeout=timeout, refresh=refresh)
    return json.loads(payload.decode("utf-8")), _sha256_bytes(payload)
