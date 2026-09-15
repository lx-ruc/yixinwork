"""本地磁盘实现：开发/本地部署用，root 可配置。"""

from pathlib import Path

from app.storage.base import StorageError, StorageService, validate_key


class LocalDiskStorage:
    """root 下的 key 即相对路径；解析后必须仍在 root 内（双保险防穿越）。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError(f"存储 key 逃逸出根目录: {key!r}")
        return path

    def save(self, key: str, data: bytes | str) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = data.encode("utf-8") if isinstance(data, str) else data
        path.write_bytes(raw)
        return key

    def read(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise StorageError(f"文件不存在: {key!r}")
        return path.read_bytes()

    def read_text(self, key: str) -> str:
        return self.read(key).decode("utf-8")

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).is_file()
        except StorageError:
            return False

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.is_file():
            path.unlink()
