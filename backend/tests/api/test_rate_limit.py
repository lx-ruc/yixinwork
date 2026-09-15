"""G10 API 限流测试：按用户滑窗、429+Retry-After、健康检查豁免、身份隔离。"""

from app.config import get_settings

RL_USER = "rl-user"  # 专属用户：限流计数不与其他测试串扰


async def test_rate_limit_429_after_threshold(app_client, monkeypatch):
    """同用户超过阈值 → 429 + Retry-After；不同用户不受牵连。"""
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "3")
    get_settings.cache_clear()
    try:
        codes = [
            (
                await app_client.post(
                    "/api/sessions", json={}, headers={"X-User-Id": RL_USER}
                )
            ).status_code
            for _ in range(5)
        ]
        assert codes[:3] == [200, 200, 200]
        assert codes[3:] == [429, 429]

        # 超限响应带 Retry-After 与提示
        again = await app_client.post(
            "/api/sessions", json={}, headers={"X-User-Id": RL_USER}
        )
        assert again.status_code == 429
        assert int(again.headers["Retry-After"]) >= 1

        # 其他用户正常（限流键按身份隔离）
        other = await app_client.post(
            "/api/sessions", json={}, headers={"X-User-Id": "rl-other"}
        )
        assert other.status_code == 200
    finally:
        monkeypatch.delenv("RATE_LIMIT_REQUESTS", raising=False)
        get_settings.cache_clear()


async def test_rate_limit_exempts_health(app_client, monkeypatch):
    """探活豁免：限流打满后 /api/health 仍可用（监控不被误伤）。"""
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    get_settings.cache_clear()
    try:
        first = await app_client.get("/api/health", headers={"X-User-Id": RL_USER})
        assert first.status_code == 200
        # 打满限额
        await app_client.post("/api/sessions", json={}, headers={"X-User-Id": RL_USER})
        limited = await app_client.post(
            "/api/sessions", json={}, headers={"X-User-Id": RL_USER}
        )
        assert limited.status_code == 429
        # 探活不受限
        health = await app_client.get("/api/health", headers={"X-User-Id": RL_USER})
        assert health.status_code == 200
    finally:
        monkeypatch.delenv("RATE_LIMIT_REQUESTS", raising=False)
        get_settings.cache_clear()


async def test_rate_limiter_reset_clears_counters(app_client, monkeypatch):
    """reset 清零：运维/测试可恢复被限用户的访问。"""
    from app.main import app

    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    get_settings.cache_clear()
    try:
        for _ in range(2):
            await app_client.post("/api/sessions", json={}, headers={"X-User-Id": RL_USER})
        assert (
            await app_client.post(
                "/api/sessions", json={}, headers={"X-User-Id": RL_USER}
            )
        ).status_code == 429

        app.state.rate_limiter.reset()
        ok = await app_client.post(
            "/api/sessions", json={}, headers={"X-User-Id": RL_USER}
        )
        assert ok.status_code == 200
    finally:
        monkeypatch.delenv("RATE_LIMIT_REQUESTS", raising=False)
        get_settings.cache_clear()
        app.state.rate_limiter.reset()
