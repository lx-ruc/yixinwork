"""测试公共夹具：内存库 + 依赖覆盖 + 假 LLM（直答 / Agent 两套）。"""

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
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
    """带 DB / Agent 依赖覆盖的 httpx ASGI 客户端（lifespan 不执行，手动覆盖）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    from app.api.deps import get_agent_model, get_checkpointer
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

    shared_saver = InMemorySaver()  # 同一测试内跨请求共享（任务反馈续跑依赖 thread 状态）

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_session_factory] = lambda: db_sessionmaker
    app.dependency_overrides[get_checkpointer] = lambda: shared_saver
    app.dependency_overrides[get_agent_model] = lambda: FakeAgentModel(
        messages=iter([AIMessage(content="初稿已完成，请预览。")])
    )
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


class FakeAgentModel(GenericFakeChatModel):
    """Agent 循环假模型：按队列回放消息（可带 tool_calls），记录每次输入。"""

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def __init__(self, **data):
        super().__init__(**data)
        object.__setattr__(self, "_calls", [])

    @property
    def calls(self) -> list[list]:
        return self._calls

    async def ainvoke(self, messages, *a, **kw):  # type: ignore[override]
        self._calls.append(list(messages))
        return await super().ainvoke(messages, *a, **kw)


@pytest.fixture
def fake_llm():
    return FakeLLM(["你好", "，这里是", "智能体"])
