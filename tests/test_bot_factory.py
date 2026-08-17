from __future__ import annotations

from aiogram.client.session.aiohttp import AiohttpSession

from src.control.bot_factory import build_bot
from src.core.config import Settings


def test_build_bot_without_proxy_uses_default_session() -> None:
    settings = Settings(_env_file=None, bot_token="123456:test-token-fake-abc")  # type: ignore[call-arg]
    bot = build_bot(settings)
    assert bot.token == "123456:test-token-fake-abc"


def test_build_bot_with_proxy_configures_aiohttp_session() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, bot_token="123456:test-token-fake-abc", telegram_proxy_url="http://127.0.0.1:10809"
    )
    bot = build_bot(settings)
    assert isinstance(bot.session, AiohttpSession)
