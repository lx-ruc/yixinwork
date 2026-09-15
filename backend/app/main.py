"""应用入口：uvicorn app.main:app。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent import recover_interrupted_tasks
from app.api import register_routers
from app.config import get_settings
from app.db import SessionLocal

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """LangGraph 检查点（同库 PG）+ 中断任务恢复。"""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        recovered = recover_interrupted_tasks(SessionLocal)
        if recovered:
            logger.warning("启动恢复：%d 个执行中任务标记为失败", recovered)
        yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_routers(app)
    return app


app = create_app()
