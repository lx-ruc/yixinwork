"""会话 CRUD 与数据隔离测试。"""

HEADERS_A = {"X-User-Id": "user-a"}
HEADERS_B = {"X-User-Id": "user-b"}


async def test_create_and_get_session(app_client):
    resp = await app_client.post(
        "/api/sessions", json={"title": "测试会话"}, headers=HEADERS_A
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "测试会话"
    assert body["mode"] == "chat"

    got = await app_client.get(f"/api/sessions/{body['id']}", headers=HEADERS_A)
    assert got.status_code == 200
    assert got.json()["id"] == body["id"]


async def test_create_rejects_invalid_mode(app_client):
    resp = await app_client.post(
        "/api/sessions", json={"mode": "foo"}, headers=HEADERS_A
    )
    assert resp.status_code == 422


async def test_list_sessions_scoped_by_user(app_client):
    await app_client.post("/api/sessions", json={}, headers=HEADERS_A)
    await app_client.post("/api/sessions", json={}, headers=HEADERS_B)

    list_a = await app_client.get("/api/sessions", headers=HEADERS_A)
    assert list_a.status_code == 200
    assert len(list_a.json()) == 1


async def test_cross_user_access_returns_404(app_client):
    created = await app_client.post("/api/sessions", json={}, headers=HEADERS_A)
    sid = created.json()["id"]

    got = await app_client.get(f"/api/sessions/{sid}", headers=HEADERS_B)
    assert got.status_code == 404


async def test_patch_mode_persists(app_client):
    created = await app_client.post("/api/sessions", json={}, headers=HEADERS_A)
    sid = created.json()["id"]

    patched = await app_client.patch(
        f"/api/sessions/{sid}", json={"mode": "work"}, headers=HEADERS_A
    )
    assert patched.status_code == 200
    assert patched.json()["mode"] == "work"

    again = await app_client.get(f"/api/sessions/{sid}", headers=HEADERS_A)
    assert again.json()["mode"] == "work"
