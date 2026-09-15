"""测试公共夹具：内存库 + 依赖覆盖 + 假 LLM。"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_session_factory
from app.db import Base, get_db
from app.llm.glm import ChatChunk, LLMError
from app.storage.local_disk import LocalDiskStorage


@pytest.fixture
def storage(tmp_path):
    return LocalDiskStorage(tmp_path / "artifacts")


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_sessionmaker(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
async def app_client(db_sessionmaker):
    """带 DB 依赖覆盖的 httpx ASGI 客户端。"""
    from app.main import app

    def _override_get_db():
        db = db_sessionmaker()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_factory] = lambda: db_sessionmaker
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class FakeLLM:
    """按预设分片回放流式回复。"""

    def __init__(self, deltas: list[str]):
        self.deltas = deltas
        self.calls: list[list[dict]] = []

    def stream_chat(self, messages):
        self.calls.append(messages)
        for d in self.deltas:
            yield ChatChunk(delta=d)
        yield ChatChunk(
            delta="", usage={"input_tokens": 10, "output_tokens": len(self.deltas)}
        )


class FailingLLM:
    def stream_chat(self, messages):
        raise LLMError("GLM_API_KEY 未配置")
        yield  # pragma: no cover


@pytest.fixture
def fake_llm():
    return FakeLLM(["你好", "，这里是", "智能体"])
