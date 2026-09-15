"""API 路由注册。"""

from fastapi import FastAPI

from app.api import chat, health, sessions


def register_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
