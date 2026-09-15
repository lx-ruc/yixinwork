"""Agent 工具注册框架：定义 / 校验 / 调用封装。

工具 = 名称 + 描述 + JSON Schema 参数 + 异步函数（入参 dict，出参文本结果）。
LLM 侧由 graph 绑定为 OpenAI function calling 格式；G6 按此框架填充真实工具。
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import jsonschema

ToolFunc = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema
    func: ToolFunc

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolError(Exception):
    """工具执行失败（回传给 LLM 与前端，不终止任务）。"""


class ToolRegistry:
    """进程内工具注册表；启动时注册，运行期只读。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"工具重名: {spec.name}")
        self._tools[spec.name] = spec

    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def openai_schemas(self) -> list[dict]:
        return [t.to_openai() for t in self._tools.values()]

    async def execute(self, name: str, args: dict) -> str:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolError(f"未知工具: {name}")
        try:
            jsonschema.validate(args, spec.parameters)
        except jsonschema.ValidationError as exc:
            raise ToolError(f"参数校验失败: {exc.message}") from exc
        try:
            return await spec.func(args)
        except ToolError:
            raise
        except Exception as exc:  # 工具内部错误统一转译，不外泄栈
            raise ToolError(f"{name} 执行失败: {exc}") from exc
