"""API 路由注册。"""

from fastapi import FastAPI

from app.api import artifacts, chat, health, sessions, tasks, usage


def register_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(chat.router)
    app.include_router(tasks.router)
    app.include_router(artifacts.router)
    app.include_router(usage.router)
