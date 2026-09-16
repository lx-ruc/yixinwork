"""GLM 流式分片解析：reasoning_content 提取（思考过程展示的数据来源）。"""

from types import SimpleNamespace

from app.llm.glm import ChatChunk, _parse_chunk


def _chunk(delta=None, usage=None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta)] if delta is not None else [],
        usage=usage,
    )


def test_reasoning_content_extracted():
    d = SimpleNamespace(content=None, reasoning_content="思考片段")
    out = list(_parse_chunk(_chunk(delta=d)))
    assert out == [ChatChunk(reasoning="思考片段")]


def test_content_and_reasoning_same_chunk():
    d = SimpleNamespace(content="正文", reasoning_content="先想一想")
    out = list(_parse_chunk(_chunk(delta=d)))
    assert out == [ChatChunk(delta="正文", reasoning="先想一想")]


def test_plain_content_unchanged():
    d = SimpleNamespace(content="你好")
    out = list(_parse_chunk(_chunk(delta=d)))
    assert out == [ChatChunk(delta="你好")]


def test_empty_chunk_yields_nothing():
    d = SimpleNamespace(content=None, reasoning_content=None)
    assert list(_parse_chunk(_chunk(delta=d))) == []


def test_usage_only_chunk():
    u = SimpleNamespace(prompt_tokens=3, completion_tokens=4)
    out = list(_parse_chunk(_chunk(usage=u)))
    assert out == [ChatChunk(usage={"input_tokens": 3, "output_tokens": 4})]
