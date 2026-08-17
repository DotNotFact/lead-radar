from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger("lead_radar.proxy")

_SCHEME_MAP = {"http": "http", "https": "http", "socks5": "socks5", "socks4": "socks4"}


def parse_telethon_proxy(url: str) -> dict[str, Any] | None:
    """TELEGRAM_PROXY_URL (http://host:port или socks5://host:port) -> формат python-socks,
    который принимает Telethon. Возвращает None и логирует предупреждение при пустом или
    неразбираемом URL - вызывающий код просто не передаёт proxy= Telethon, а не падает."""
    if not url:
        return None

    parsed = urlparse(url)
    proxy_type = _SCHEME_MAP.get(parsed.scheme)
    if proxy_type is None or not parsed.hostname or not parsed.port:
        logger.warning("telegram_proxy_url_unsupported", extra={"url": url})
        return None

    return {
        "proxy_type": proxy_type,
        "addr": parsed.hostname,
        "port": parsed.port,
        "username": parsed.username,
        "password": parsed.password,
    }
