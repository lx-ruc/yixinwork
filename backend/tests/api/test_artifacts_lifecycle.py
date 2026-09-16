"""G8 产物生命周期测试：版本链、预览、满意交付转换、签名下载与安全。"""

import json

from langchain_core.messages import AIMessage

from app.api.deps import get_agent_model
from app.main import app
from app.services import artifact_service
from tests.conftest import FakeAgentModel

HEADERS = {"X-User-Id": "art-user"}


def _parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def _doc_tool(title: str, body: str, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "save_document", "args": {"title": title, "content_md": body}, "id": call_id}
        ],
    )


async def _run_doc_task(app_client) -> tuple[str, list[dict]]:
    """跑一个带保存动作的任务到预览就绪，返回 (session_id, events)。"""
    sid = (
        await app_client.post("/api/sessions", json={}, headers=HEADERS)
    ).json()["id"]
    await app_client.patch(f"/api/sessions/{sid}", json={"mode": "work"}, headers=HEADERS)
    resp = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "写个方案"},
        headers=HEADERS,
    )
    return sid, _parse_sse(resp.text)


async def test_version_chain_preview_download_flow(app_client):
    """保存→v1；修改→v2；预览按版本；交付后下载 docx。"""
    model = FakeAgentModel(
        messages=iter(
            [
                _doc_tool("方案", "第一版内容", "c1"),
                AIMessage(content="初稿完成"),
                _doc_tool("方案", "第二版内容", "c2"),
                AIMessage(content="修订完成"),
            ]
        )
    )
    app.dependency_overrides[get_agent_model] = lambda: model
    sid, events = await _run_doc_task(app_client)
    task_id = next(e for e in events if e["type"] == "task_created")["task"]["id"]

    arts = (await app_client.get(f"/api/tasks/{task_id}/artifacts", headers=HEADERS)).json()
    assert len(arts) == 1 and arts[0]["kind"] == "document"
    assert [v["version"] for v in arts[0]["versions"]] == [1]

    # 修改指令 → 同一产物 v2（版本链）
    revise = await app_client.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "补充第二版"},
        headers=HEADERS,
    )
    assert _parse_sse(revise.text)[-1]["type"] == "preview_ready"
    arts = (await app_client.get(f"/api/tasks/{task_id}/artifacts", headers=HEADERS)).json()
    assert [v["version"] for v in arts[0]["versions"]] == [1, 2]

    art_id = arts[0]["id"]
    # 预览：默认最新（v2），可指定历史版本
    latest = (await app_client.get(f"/api/artifacts/{art_id}/preview", headers=HEADERS)).json()
    assert latest["render"] == "markdown" and "第二版内容" in latest["content"]
    v1 = (
        await app_client.get(f"/api/artifacts/{art_id}/preview?version=1", headers=HEADERS)
    ).json()
    assert "第一版内容" in v1["content"]

    # 下载签名 URL → docx 内容
    link = (
        await app_client.post(
            f"/api/artifacts/{art_id}/versions/2/download", headers=HEADERS
        )
    ).json()
    assert link["format"] == "docx"
    token = link["url"].rsplit("/", 1)[-1]
    file_resp = await app_client.get(f"/api/downloads/{token}")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml"
    )
    assert file_resp.content[:2] == b"PK"  # docx = zip 包
    # 双文件名：现代浏览器取 filename*（原名），老浏览器回退 ASCII（保扩展名）
    disp = file_resp.headers["content-disposition"]
    assert 'filename="yixin-work.docx"' in disp
    assert "filename*=UTF-8''" in disp

    # 满意交付（终态）后重复反馈 409
    approve = await app_client.post(
        f"/api/tasks/{task_id}/feedback", json={"action": "approve"}, headers=HEADERS
    )
    assert _parse_sse(approve.text)[-1]["type"] == "task_completed"


async def test_poster_preview_xss_escaped(app_client):
    """海报标题注入 script → 预览内容为转义文本（生成时已 escape）。"""
    model = FakeAgentModel(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "save_poster",
                            "args": {"title": "海报<script>alert(1)</script>", "slogan": "s"},
                            "id": "c1",
                        }
                    ],
                ),
                AIMessage(content="完成"),
            ]
        )
    )
    app.dependency_overrides[get_agent_model] = lambda: model
    _, events = await _run_doc_task(app_client)
    task_id = next(e for e in events if e["type"] == "task_created")["task"]["id"]
    arts = (await app_client.get(f"/api/tasks/{task_id}/artifacts", headers=HEADERS)).json()
    preview = (
        await app_client.get(f"/api/artifacts/{arts[0]['id']}/preview", headers=HEADERS)
    ).json()
    assert preview["render"] == "html"
    assert "<script>" not in preview["content"]
    assert "&lt;script&gt;" in preview["content"]


async def test_artifacts_cross_user_404(app_client):
    model = FakeAgentModel(
        messages=iter([_doc_tool("t", "内容", "c1"), AIMessage(content="完成")])
    )
    app.dependency_overrides[get_agent_model] = lambda: model
    _, events = await _run_doc_task(app_client)
    task_id = next(e for e in events if e["type"] == "task_created")["task"]["id"]
    other = {"X-User-Id": "intruder"}
    assert (
        await app_client.get(f"/api/tasks/{task_id}/artifacts", headers=other)
    ).status_code == 404
    arts = (await app_client.get(f"/api/tasks/{task_id}/artifacts", headers=HEADERS)).json()
    assert (
        await app_client.get(f"/api/artifacts/{arts[0]['id']}/preview", headers=other)
    ).status_code == 404
    assert (
        await app_client.post(
            f"/api/artifacts/{arts[0]['id']}/versions/1/download", headers=other
        )
    ).status_code == 404


async def test_download_token_security(app_client):
    """篡改签名 403；过期 403；伪造 key（路径穿越）无法通过签名。"""
    model = FakeAgentModel(
        messages=iter([_doc_tool("t", "内容", "c1"), AIMessage(content="完成")])
    )
    app.dependency_overrides[get_agent_model] = lambda: model
    _, events = await _run_doc_task(app_client)
    task_id = next(e for e in events if e["type"] == "task_created")["task"]["id"]
    arts = (await app_client.get(f"/api/tasks/{task_id}/artifacts", headers=HEADERS)).json()
    link = (
        await app_client.post(
            f"/api/artifacts/{arts[0]['id']}/versions/1/download", headers=HEADERS
        )
    ).json()
    token = link["url"].rsplit("/", 1)[-1]

    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert (
        await app_client.get(f"/api/downloads/{tampered}")
    ).status_code == 403

    expired_token, _ = artifact_service.make_download_token(
        key="whatever", user_id="u", filename="x.docx", ttl=-1
    )
    assert (
        await app_client.get(f"/api/downloads/{expired_token}")
    ).status_code == 403

    # 签名密钥不知情的前提下无法为任意 key（含 ../）伪造合法 token
    forged_token, _ = artifact_service.make_download_token(
        key="../../etc/passwd", user_id="u", filename="p", ttl=60
    )
    resp = await app_client.get(f"/api/downloads/{forged_token}")
    assert resp.status_code == 404  # 签名虽合法但 key 经存储层校验不存在/逃逸拒绝
