from __future__ import annotations

from src.core.proxy import parse_telethon_proxy


def test_parses_http_proxy_url() -> None:
    result = parse_telethon_proxy("http://127.0.0.1:10809")
    assert result == {
        "proxy_type": "http",
        "addr": "127.0.0.1",
        "port": 10809,
        "username": None,
        "password": None,
    }


def test_parses_socks5_proxy_with_credentials() -> None:
    result = parse_telethon_proxy("socks5://user:pass@example.com:1080")
    assert result is not None
    assert result["proxy_type"] == "socks5"
    assert result["addr"] == "example.com"
    assert result["port"] == 1080
    assert result["username"] == "user"
    assert result["password"] == "pass"


def test_empty_url_returns_none() -> None:
    assert parse_telethon_proxy("") is None


def test_unsupported_scheme_returns_none() -> None:
    assert parse_telethon_proxy("ftp://127.0.0.1:21") is None


def test_missing_port_returns_none() -> None:
    assert parse_telethon_proxy("http://127.0.0.1") is None
