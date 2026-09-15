"""产物 API：版本链查询 / 预览 / 签名下载。所有者校验经 task/artifact 的 user_id。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserId, DbSession
from app.models import Artifact, ArtifactVersion, Task
from app.services import artifact_service
from app.storage import get_storage
from app.storage.base import StorageError

router = APIRouter(prefix="/api", tags=["artifacts"])

# 下载文件名 → MIME
MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "png": "image/png",
    "pdf": "application/pdf",
    "csv": "text/csv",
    "md": "text/markdown",
    "html": "text/html",
}


def _owned_task(db: Session, user_id: str, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/tasks/{task_id}/artifacts")
def list_artifacts(
    task_id: str, db: DbSession, user_id: CurrentUserId
) -> list[dict]:
    task = _owned_task(db, user_id, task_id)
    return artifact_service.list_task_artifacts(db, task)


class PreviewOut(BaseModel):
    artifact_id: str
    title: str
    kind: str
    version: int
    render: str
    content: str
    payload: dict | None = None


@router.get("/artifacts/{artifact_id}/preview", response_model=PreviewOut)
def get_preview(
    artifact_id: str, db: DbSession, user_id: CurrentUserId, version: int | None = None
):
    art, ver = artifact_service.get_version(db, user_id, artifact_id, version)
    if art is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    try:
        return artifact_service.build_preview(art, ver)
    except StorageError:
        raise HTTPException(status_code=410, detail="产物文件已失效") from None


class DownloadLink(BaseModel):
    format: str
    filename: str
    url: str
    expires_at: int


def _download_filename(art: Artifact, ver: ArtifactVersion) -> str:
    ext = ver.final_format or ver.intermediate_format
    base = (art.title or art.kind).replace("/", "-")[:60] or art.kind
    return f"{base}.{ext}"


@router.post("/artifacts/{artifact_id}/versions/{version}/download")
def create_download(
    artifact_id: str,
    version: int,
    db: DbSession,
    user_id: CurrentUserId,
) -> DownloadLink:
    art, ver = artifact_service.get_version(db, user_id, artifact_id, version)
    if art is None:
        raise HTTPException(status_code=404, detail="产物不存在")
    try:
        ver = artifact_service.ensure_final(db, ver, kind=art.kind)
    except StorageError:
        raise HTTPException(status_code=409, detail="该产物暂无可下载文件") from None
    from app.config import get_settings

    token, expires = artifact_service.make_download_token(
        key=ver.final_file_key,
        user_id=user_id,
        filename=_download_filename(art, ver),
        ttl=get_settings().download_url_ttl_seconds,
    )
    return DownloadLink(
        format=ver.final_format or "",
        filename=_download_filename(art, ver),
        url=f"/api/downloads/{token}",
        expires_at=expires,
    )


@router.get("/downloads/{token}")
def download(token: str, request: Request) -> Response:
    """签名 URL 下载：只信 HMAC 签名 + 过期时间（key 由服务端签发，无用户输入）。"""
    try:
        payload = artifact_service.verify_download_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    key = payload["k"]
    filename = payload.get("f", "download")
    try:
        data = get_storage().read(key)
    except StorageError:
        raise HTTPException(status_code=404, detail="文件不存在或已清理") from None
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media_type = MIME_TYPES.get(ext, "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{_quote(filename)}"},
    )


def _quote(name: str) -> str:
    from urllib.parse import quote

    return quote(name)
