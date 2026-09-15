"""按用户/IP 的进程内滑动窗口限流。

本地起步无 Redis：单实例部署下进程内计数即可；多实例迁移时替换本实现
（接口 check/reset 不变）。限流键优先取可信 X-User-Id，缺失回退客户端 IP。
"""

import time
from collections import deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings

EXEMPT_PATHS = frozenset({"/api/health", "/api/internal"})  # 探活/内部接口不限


class SlidingWindowLimiter:
    """滑动窗口计数器：窗口内超过 max_requests 则拒绝。"""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str, *, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """返回 (是否放行, 建议重试等待秒数)。"""
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        cutoff = now - window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= max_requests:
            retry_after = max(1, int(hits[0] + window_seconds - now) + 1)
            return False, retry_after
        hits.append(now)
        if not hits:  # 刚被并发清空的极端情形
            hits.append(now)
        return True, 0

    def reset(self) -> None:
        """清空计数（测试与运维用）。"""
        self._hits.clear()


def install_rate_limit(app: FastAPI) -> None:
    """挂载限流中间件（设置每请求读取，测试可动态开关）。"""
    limiter = SlidingWindowLimiter()
    app.state.rate_limiter = limiter

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        settings = get_settings()
        if settings.rate_limit_requests <= 0:
            return await call_next(request)
        if request.url.path in EXEMPT_PATHS or any(
            request.url.path.startswith(p) for p in EXEMPT_PATHS
        ):
            return await call_next(request)

        user = (request.headers.get("X-User-Id") or "").strip()
        key = f"u:{user}" if user else f"ip:{request.client.host if request.client else 'unknown'}"
        allowed, retry_after = limiter.check(
            key,
            max_requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"请求过于频繁，请 {retry_after} 秒后重试"},
                headers={"Retry-After": str(retry_after)},
            )
        response = await call_next(request)
        response.headers.setdefault("X-RateLimit-Limit", str(settings.rate_limit_requests))
        return response
