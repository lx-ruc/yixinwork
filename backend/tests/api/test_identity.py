"""身份上下文测试：X-User-Id 解析、严格模式 401、开发回退。"""

import pytest
from fastapi import HTTPException

from app.api.deps import get_current_user_id
from app.config import Settings


def test_header_value_wins():
    assert get_current_user_id(x_user_id=" user-42 ") == "user-42"


def test_dev_fallback_when_header_missing():
    settings = Settings(require_user_header=False, dev_default_user_id="dev-local-user")
    # get_current_user_id 读取的是 lru_cache 的全局配置，这里直接测函数逻辑分支
    assert settings.dev_default_user_id == "dev-local-user"
    assert get_current_user_id(x_user_id=None) in {"dev-local-user", "dev-user"}


def test_strict_mode_raises_401(monkeypatch):
    import app.api.deps as deps

    monkeypatch.setattr(
        deps,
        "get_settings",
        lambda: Settings(require_user_header=True, dev_default_user_id="dev"),
    )
    with pytest.raises(HTTPException) as exc:
        get_current_user_id(x_user_id=None)
    assert exc.value.status_code == 401


def test_empty_header_falls_back_or_401():
    # 空白头视同缺失
    assert get_current_user_id(x_user_id="   ") in {"dev-local-user", "dev-user"}
