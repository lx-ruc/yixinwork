"""StorageService 抽象：产物文件一律经此接口读写，便于后期换 OSS/S3。

key 即对象键，约定按用户分域：{user_id}/{task_id}/v{n}/{filename}
"""

from typing import Protocol


class StorageError(Exception):
    """存储层错误（key 非法、文件不存在等）。"""


class StorageService(Protocol):
    def save(self, key: str, data: bytes | str) -> str:
        """写入数据（bytes 或 utf-8 文本），返回 key。"""
        ...

    def read(self, key: str) -> bytes:
        """读取字节；不存在抛 StorageError。"""
        ...

    def read_text(self, key: str) -> str:
        """读取 utf-8 文本；不存在抛 StorageError。"""
        ...

    def exists(self, key: str) -> bool:
        ...

    def delete(self, key: str) -> None:
        ...


def artifact_key(user_id: str, task_id: str, version: int, filename: str) -> str:
    """构造产物文件 key：{user_id}/{task_id}/v{n}/{filename}。

    各段禁止路径分隔符与 ".."，防止路径穿越。
    """
    segments = [user_id, task_id, f"v{version}", filename]
    for seg in segments:
        if not seg or "/" in seg or "\\" in seg or ".." in seg:
            raise StorageError(f"非法存储 key 段: {seg!r}")
    return "/".join(segments)


def validate_key(key: str) -> None:
    """校验通用 key：非空、无绝对路径、无 ".."。"""
    if not key or key.startswith("/") or ".." in key or "\\" in key:
        raise StorageError(f"非法存储 key: {key!r}")
