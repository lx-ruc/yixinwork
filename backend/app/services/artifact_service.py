"""产物生命周期服务：版本链落库、预览数据、满意后最终格式转换、签名下载。

模型约定（models/artifact.py）：一个版本 = 一个中间格式 file_key；
满意确认后转换出 final_file_key（复用工具保存时已生成的同名伴随文件，
缺失则现算），下载经 HMAC 签名 URL（含过期时间，key 不含用户输入）。
"""

import hashlib
import hmac
import io
import json
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models import (
    ARTIFACT_DATA,
    ARTIFACT_DOCUMENT,
    ARTIFACT_POSTER,
    ARTIFACT_SLIDES,
    ARTIFACT_TABLE,
    Artifact,
    ArtifactVersion,
    Task,
)
from app.storage import get_storage
from app.storage.base import StorageError

logger = logging.getLogger(__name__)

# 各产物类型的最终下载格式与文件名
FINAL_FORMATS: dict[str, tuple[str, str]] = {
    ARTIFACT_DOCUMENT: ("docx", "document.docx"),
    ARTIFACT_POSTER: ("png", "poster.png"),
    ARTIFACT_TABLE: ("xlsx", "table.xlsx"),
    ARTIFACT_SLIDES: ("pptx", "slides.pptx"),
    ARTIFACT_DATA: ("xlsx", "data.xlsx"),
}


# ---- 版本链落库（工具执行流内调用） ----


def record_version(
    db_factory: sessionmaker,
    *,
    user_id: str,
    task_id: str,
    kind: str,
    title: str,
    intermediate_format: str,
    file_key: str,
    preview_payload: dict | None = None,
) -> str:
    """记录一次产物保存：同 (task, kind) 归并为一个产物的下一版本。"""
    with db_factory() as db:
        artifact = db.execute(
            select(Artifact).where(Artifact.task_id == task_id, Artifact.kind == kind)
        ).scalar_one_or_none()
        if artifact is None:
            artifact = Artifact(user_id=user_id, task_id=task_id, kind=kind, title=title)
            db.add(artifact)
            db.flush()
        artifact.title = title  # 以最新保存的标题为准
        next_version = (
            db.execute(
                select(ArtifactVersion.version)
                .where(ArtifactVersion.artifact_id == artifact.id)
                .order_by(ArtifactVersion.version.desc())
                .limit(1)
            ).scalar_one_or_none()
            or 0
        ) + 1
        row = ArtifactVersion(
            artifact_id=artifact.id,
            user_id=user_id,
            version=next_version,
            intermediate_format=intermediate_format,
            file_key=file_key,
            preview_payload=preview_payload,
        )
        db.add(row)
        db.commit()
        return str(row.id)


# ---- 查询 ----


def list_task_artifacts(db, task: Task) -> list[dict]:
    arts = (
        db.execute(
            select(Artifact).where(Artifact.task_id == task.id).order_by(Artifact.created_at)
        )
        .scalars()
        .all()
    )
    out: list[dict] = []
    for a in arts:
        versions = (
            db.execute(
                select(ArtifactVersion)
                .where(ArtifactVersion.artifact_id == a.id)
                .order_by(ArtifactVersion.version)
            )
            .scalars()
            .all()
        )
        out.append(
            {
                "id": str(a.id),
                "kind": a.kind,
                "title": a.title,
                "versions": [
                    {
                        "version": v.version,
                        "format": v.intermediate_format,
                        "final_format": v.final_format,
                        "created_at": v.created_at.isoformat() if v.created_at else None,
                    }
                    for v in versions
                ],
            }
        )
    return out


def get_version(db, user_id: str, artifact_id: str, version: int | None):
    """取产物与指定版本（None=最新）；跨用户返回 None。"""
    art = db.get(Artifact, artifact_id)
    if art is None or art.user_id != user_id:
        return None, None
    stmt = (
        select(ArtifactVersion)
        .where(ArtifactVersion.artifact_id == art.id)
        .order_by(ArtifactVersion.version.desc())
    )
    if version is None:
        ver = db.execute(stmt.limit(1)).scalar_one_or_none()
    else:
        ver = db.execute(
            stmt.where(ArtifactVersion.version == version)
        ).scalar_one_or_none()
    return (art, ver) if ver is not None else (None, None)


# ---- 预览 ----


def build_preview(art: Artifact, ver: ArtifactVersion) -> dict:
    """按中间格式产出前端可渲染的预览数据。"""
    storage = get_storage()
    fmt = ver.intermediate_format
    preview: dict = {
        "artifact_id": str(art.id),
        "title": art.title,
        "kind": art.kind,
        "version": ver.version,
        "render": fmt,
        "content": "",
        "payload": None,
    }
    if fmt in ("markdown", "html", "html_table", "html_slides"):
        preview["content"] = storage.read_text(ver.file_key)
    elif fmt == "csv":
        import csv

        text = storage.read_text(ver.file_key)
        rows = list(csv.reader(io.StringIO(text)))
        preview["render"] = "html_table"
        preview["payload"] = {"headers": rows[0] if rows else [], "rows": rows[1:]}
        preview["content"] = ""
    else:  # 二进制产物（无预览，仅下载）
        preview["render"] = "binary"
    if ver.preview_payload:
        preview["payload"] = ver.preview_payload
    return preview


# ---- 满意确认后的最终格式转换 ----


def ensure_final(db, ver: ArtifactVersion, *, kind: str) -> ArtifactVersion:
    """幂等补齐 final_file_key：优先复用工具保存时生成的伴随文件。"""
    if ver.final_file_key:
        db.commit()
        return ver
    storage = get_storage()
    final_fmt, final_name = FINAL_FORMATS.get(kind, ("bin", "download.bin"))
    version_dir = ver.file_key.rsplit("/", 1)[0]
    companion = f"{version_dir}/{final_name}"
    if storage.exists(companion):
        final_key = companion
    else:
        final_key = _convert(ver, kind, final_fmt, final_name)
    ver.final_file_key = final_key
    ver.final_format = final_fmt
    db.commit()
    return ver


def _convert(ver: ArtifactVersion, kind: str, final_fmt: str, final_name: str) -> str:
    """伴随文件缺失时按需转换（markdown→docx / 表格→xlsx 等）。"""
    storage = get_storage()
    version_dir = ver.file_key.rsplit("/", 1)[0]
    key = f"{version_dir}/{final_name}"
    if kind == ARTIFACT_DOCUMENT:
        from app.tools.artifacts import markdown_to_docx_bytes

        title = (ver.preview_payload or {}).get("title", "文档")
        data = markdown_to_docx_bytes(title, storage.read_text(ver.file_key))
    elif kind in (ARTIFACT_TABLE, ARTIFACT_DATA):
        data = _payload_to_xlsx(ver)
    else:
        raise StorageError(f"产物类型 {kind} 缺少可下载文件，无法转换")
    storage.save(key, data)
    return key


def _payload_to_xlsx(ver: ArtifactVersion) -> bytes:
    from openpyxl import Workbook

    payload = ver.preview_payload or {}
    wb = Workbook()
    ws = wb.active
    ws.append([str(h) for h in payload.get("headers", [])])
    for row in payload.get("rows", []):
        ws.append([str(c) for c in row])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---- 签名 URL 下载 ----


def _signing_secret() -> str:
    return get_settings().download_signing_secret


def make_download_token(*, key: str, user_id: str, filename: str, ttl: int) -> tuple[str, int]:
    expires = int(time.time()) + ttl
    payload = json.dumps(
        {"k": key, "u": user_id, "f": filename, "e": expires}, separators=(",", ":")
    ).encode("utf-8")
    body = _b64url(payload)
    sig = _b64url(hmac.new(_signing_secret().encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}", expires


def verify_download_token(token: str) -> dict:
    """校验签名与过期时间；返回 payload，非法抛 ValueError。"""
    body, _, sig = token.partition(".")
    if not body or not sig:
        raise ValueError("token 格式非法")
    expected = _b64url(
        hmac.new(_signing_secret().encode(), body.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        raise ValueError("token 签名不匹配")
    try:
        payload = json.loads(_b64url_decode(body))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("token 载荷非法") from exc
    if not isinstance(payload, dict) or not payload.get("k"):
        raise ValueError("token 载荷非法")
    if int(payload.get("e", 0)) < time.time():
        raise ValueError("token 已过期")
    return payload


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    import base64

    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)
