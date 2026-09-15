"""任务/闲聊分类器单元测试：保守判定（疑问句优先闲聊）。"""

import pytest

from app.services.routing import ROUTE_CHAT, ROUTE_TASK, get_classifier

clf = get_classifier()

TASK_CASES = [
    "帮我做一份Q3销售数据报告",
    "生成一张活动海报",
    "写一份工作总结",
    "帮我制作PPT",
    "设计一张邀请函",
    "翻译这份文档",
    "把这份Excel数据清洗一下",
    "统计一下这批名单",
    "海报帮我做一下",
    "给我做一份数据分析报告",
]

CHAT_CASES = [
    "你好",
    "什么是LangGraph",
    "PPT怎么做？",
    "帮我看看这段代码有什么问题",
    "今天天气怎么样",
    "谢谢",
    "你能做什么",
    "数据分析的方法有哪些？",
    "为什么天空是蓝色的",
    "周报的格式一般是什么样的",
]


@pytest.mark.parametrize("text", TASK_CASES)
def test_task_phrases(text):
    d = clf.classify(text)
    assert d.kind == ROUTE_TASK, f"{text} -> {d}"


@pytest.mark.parametrize("text", CHAT_CASES)
def test_chat_phrases(text):
    d = clf.classify(text)
    assert d.kind == ROUTE_CHAT, f"{text} -> {d}"


def test_decision_structure():
    d = clf.classify("帮我做一份Q3销售数据报告")
    assert d.is_task
    assert d.confidence > 0.5
    assert d.reason  # 卡片展示用


def test_empty_is_chat():
    assert clf.classify("").kind == ROUTE_CHAT
    assert clf.classify("   ").kind == ROUTE_CHAT
