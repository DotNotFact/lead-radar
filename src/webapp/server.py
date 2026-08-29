"""FastAPI-приложение Mini App: JSON API + отдача собранного фронтенда (miniapp/dist).

Отдельный процесс от src.main не нужен - main.py поднимает uvicorn как asyncio-задачу в
общем event loop (см. _start_miniapp в main.py). Для локальной разработки фронтенда можно
запускать этот файл отдельно: `python -m src.webapp.server`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.webapp.api import router as api_router

_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "miniapp" / "dist"


def create_app() -> FastAPI:
    # docs_url/redoc_url отключены: инструмент личный, однопользовательский - незачем держать
    # публично доступный (до всякой /api-авторизации) экран со схемой API.
    app = FastAPI(title="Lead Radar Mini App", docs_url=None, redoc_url=None)
    app.include_router(api_router)

    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    from src.core.config import get_settings

    settings = get_settings()
    uvicorn.run(app, host="127.0.0.1", port=settings.miniapp_port)
