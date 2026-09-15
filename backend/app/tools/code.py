"""代码执行工具：模型生成的代码进 Docker 沙箱，产出文件落产物存储。"""

import json
from functools import lru_cache

from app.config import get_settings
from app.sandbox.service import SandboxResult, SandboxService
from app.storage.base import artifact_key
from app.tools.base import ToolRegistry, ToolSpec, ToolError
from app.tools.context import get_tool_context


@lru_cache
def get_sandbox_service() -> SandboxService:
    s = get_settings()
    return SandboxService(
        image=s.sandbox_image,
        timeout_seconds=s.sandbox_timeout_seconds,
        memory=s.sandbox_memory,
        cpus=s.sandbox_cpus,
        max_output_bytes=s.sandbox_max_output_mb * 1024 * 1024,
    )


def _result_text(result: SandboxResult, saved: list[dict]) -> str:
    if result.timed_out:
        head = {"exit_code": None, "timed_out": True}
        note = "代码执行超时被终止，请简化或拆分任务"
    else:
        head = {"exit_code": result.exit_code, "timed_out": False}
        if result.exit_code == 0:
            note = "执行成功"
        else:
            note = "执行失败（非零退出码），stderr 见 stdout 字段"
    return json.dumps(
        {**head, "stdout": result.stdout, "saved": saved, "note": note},
        ensure_ascii=False,
    )


async def _run_python_code(args: dict) -> str:
    code = args["code"].strip()
    if not code:
        raise ToolError("代码内容为空")
    result = await get_sandbox_service().run_code(code)

    saved: list[dict] = []
    ctx = get_tool_context()
    for name, data in result.files.items():
        key = artifact_key(ctx.user_id, ctx.task_id, ctx.next_version(), name)
        ctx.storage.save(key, data)
        _record_data_file(name, key, data)
        saved.append({"kind": "sandbox_file", "name": name, "key": key})
    return _result_text(result, saved)


def _record_data_file(name: str, key: str, data: bytes) -> None:
    """沙箱产物落版本链：csv 附带结构化预览数据，其余仅可下载。"""
    from app.tools.artifacts import _record

    payload = None
    fmt = "binary"
    if name.lower().endswith(".csv"):
        import csv
        import io

        try:
            rows = list(csv.reader(io.StringIO(data.decode("utf-8", errors="replace"))))
            payload = {"title": name, "headers": rows[0] if rows else [], "rows": rows[1:]}
            fmt = "csv"
        except Exception:  # noqa: BLE001 csv 解析失败按二进制处理
            payload = None
    _record("data", name, fmt, key, payload)


def register_code_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="run_python_code",
            description=(
                "在隔离沙箱中执行 Python 代码并回传 stdout（可用于数据处理、计算等）。"
                "可用库：numpy/pandas/openpyxl。需要保留的产出文件请写到 out/ 目录"
                "（如 out/result.csv），会自动保存为产物。无网络访问。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "完整 Python 代码"},
                    "purpose": {
                        "type": "string",
                        "description": "本次执行目的（简述）",
                    },
                },
                "required": ["code"],
            },
            func=_run_python_code,
        )
    )
