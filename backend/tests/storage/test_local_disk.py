"""StorageService 本地磁盘实现测试：路径约定、读写、穿越防护。"""

import pytest

from app.storage.base import StorageError, artifact_key, validate_key
from app.storage.local_disk import LocalDiskStorage


class TestArtifactKey:
    def test_layout(self):
        key = artifact_key("u1", "t1", 2, "report.md")
        assert key == "u1/t1/v2/report.md"

    def test_rejects_dotdot_segment(self):
        with pytest.raises(StorageError):
            artifact_key("../etc", "t1", 1, "x")

    def test_rejects_slash_in_filename(self):
        with pytest.raises(StorageError):
            artifact_key("u1", "t1", 1, "a/b.md")

    def test_rejects_empty_segment(self):
        with pytest.raises(StorageError):
            artifact_key("", "t1", 1, "x")


class TestValidateKey:
    def test_rejects_absolute(self):
        with pytest.raises(StorageError):
            validate_key("/etc/passwd")

    def test_rejects_dotdot(self):
        with pytest.raises(StorageError):
            validate_key("u/t/../../etc")

    def test_rejects_empty(self):
        with pytest.raises(StorageError):
            validate_key("")


class TestLocalDiskStorage:
    def test_bytes_roundtrip(self, storage):
        key = storage.save("u1/t1/v1/a.bin", b"\x00\x01\x02")
        assert key == "u1/t1/v1/a.bin"
        assert storage.read(key) == b"\x00\x01\x02"

    def test_text_roundtrip_unicode(self, storage):
        key = storage.save("u1/t1/v1/a.md", "# 报告\n中文内容")
        assert storage.read_text(key) == "# 报告\n中文内容"

    def test_exists_and_delete(self, storage):
        storage.save("u1/t1/v1/a", "x")
        assert storage.exists("u1/t1/v1/a") is True
        storage.delete("u1/t1/v1/a")
        assert storage.exists("u1/t1/v1/a") is False

    def test_read_missing_raises(self, storage):
        with pytest.raises(StorageError):
            storage.read("u1/t1/v1/none")

    def test_traversal_key_rejected(self, storage):
        with pytest.raises(StorageError):
            storage.save("u1/../../escape", "x")

    def test_creates_parent_dirs(self, storage):
        storage.save("deep/a/b/c/file.txt", "x")
        assert storage.exists("deep/a/b/c/file.txt")

    def test_validate_key_guard_via_exists(self, storage):
        assert storage.exists("/abs") is False
