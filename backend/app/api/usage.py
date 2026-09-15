"""内部用量查询接口：宿主系统/运维按用户+时间范围拉汇总。

非用户面接口：X-Internal-Token 必须与 INTERNAL_API_TOKEN 常量时间比对；
未配置令牌时一律 403（默认关闭，部署时显式启用）。
"""

import hmac
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Query

from app.api.deps import DbSession
from app.config import get_settings
from app.services.usage_service import summarize_usage

router = APIRouter(prefix="/api/internal/usage", tags=["internal-usage"])


@router.get("/summary")
def usage_summary(
    db: DbSession,
    user_id: str = Query(min_length=1, max_length=64),
    since: datetime = Query(),
    until: datetime = Query(),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> dict:
    settings = get_settings()
    expected = settings.internal_api_token
    if not expected or not x_internal_token or not hmac.compare_digest(
        x_internal_token, expected
    ):
        raise HTTPException(status_code=403, detail="内部接口未授权")
    if since >= until:
        raise HTTPException(status_code=422, detail="时间范围非法：since 需早于 until")
    return summarize_usage(db, user_id=user_id, since=since, until=until)
