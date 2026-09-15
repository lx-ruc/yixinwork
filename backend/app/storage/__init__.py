"""存储入口：按配置提供单例。"""

from functools import lru_cache

from app.config import get_settings
from app.storage.base import StorageService
from app.storage.local_disk import LocalDiskStorage


@lru_cache
def get_storage() -> StorageService:
    return LocalDiskStorage(get_settings().storage_root)
