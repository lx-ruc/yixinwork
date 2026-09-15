"""任务/闲聊消息分类器：规则起步，预留小模型分类接口。

判定保守：只有明确"创作产物 / 数据处理"信号才判任务，
疑问句与寒暄优先按闲聊直答（误判可由确认卡片兜底，反之打扰更大）。
"""

import re
from dataclasses import dataclass
from typing import Protocol

ROUTE_TASK = "task"
ROUTE_CHAT = "chat"

# 产物名词（与 G6 可信工具层的产物类型对应）
_NOUNS = (
    "ppt|幻灯|演示文稿|海报|宣传图|报告|文档|文章|总结|方案|简历|表格|"
    "图表|词云|邀请函|通知|周报|月报|合同|文案"
)
# 创作动词
_VERBS = "做|写|生成|制作|创建|起草|设计|整理|排版|输出|修改|润色|优化|翻译"
# 动词与产物名词互相靠近（前向："写一份报告"；后向："报告帮我写一下"）
_VERB_NEAR_NOUN = re.compile(
    rf"(?:{_VERBS}).{{0,14}}(?:{_NOUNS})|(?:{_NOUNS}).{{0,14}}(?:{_VERBS})",
    re.IGNORECASE,
)
# 数据处理任务：动词与数据对象互相靠近（"分析这份数据 / Excel数据清洗一下"）
_DATA_NOUNS = "数据|文件|表格|excel|csv|日志|名单"
_DATA_VERBS = "处理|分析|清洗|统计|计算|汇总|转换|去重|筛选"
_DATA_TASK = re.compile(
    rf"(?:{_DATA_VERBS}).{{0,10}}(?:{_DATA_NOUNS})"
    rf"|(?:{_DATA_NOUNS}).{{0,10}}(?:{_DATA_VERBS})",
    re.IGNORECASE,
)
# 疑问/闲聊信号（优先级高于任务信号："PPT 怎么做？"是提问不是下单）
_QUESTION = re.compile(r"怎么|怎样|如何|什么是|是什么|为什么|哪些|哪个|[?？]|吗|呢")
_CHIT_CHAT = re.compile(
    r"你好|您好|嗨|hi|hello|在吗|谢谢|多谢|再见|拜拜|你是谁|你能做什么|自我介绍",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RouteDecision:
    """结构化路由判定。"""

    kind: str  # "task" | "chat"
    confidence: float
    reason: str

    @property
    def is_task(self) -> bool:
        return self.kind == ROUTE_TASK


class RoutingClassifier(Protocol):
    """分类器接口：后续可替换为小模型实现（输入消息、输出判定）。"""

    def classify(self, content: str) -> RouteDecision: ...


class RuleClassifier:
    """规则分类器：无外部依赖、可解释、毫秒级。"""

    def classify(self, content: str) -> RouteDecision:
        text = content.strip()
        if not text:
            return RouteDecision(ROUTE_CHAT, 1.0, "空消息按对话处理")

        has_task_signal = bool(_VERB_NEAR_NOUN.search(text) or _DATA_TASK.search(text))
        if not has_task_signal:
            return RouteDecision(ROUTE_CHAT, 0.6, "未识别到任务信号")

        if _CHIT_CHAT.search(text):
            return RouteDecision(ROUTE_CHAT, 0.7, "寒暄消息按对话处理")
        if _QUESTION.search(text):
            return RouteDecision(ROUTE_CHAT, 0.7, "疑问句优先按对话处理")

        return RouteDecision(
            ROUTE_TASK, 0.85, "检测到创作产物或数据处理意图，建议交给工作模式完成"
        )


_classifier: RoutingClassifier | None = None


def get_classifier() -> RoutingClassifier:
    """工厂：当前返回规则实现；接入小模型时在此切换。"""
    global _classifier
    if _classifier is None:
        _classifier = RuleClassifier()
    return _classifier
