"""附件上传：multipart 接收 → 抽取文本暂存，返回 id 供消息引用。"""

from fastapi import APIRouter, HTTPException, UploadFile

from app.api.deps import CurrentUserId

from app.services.attachment_service import (
    MAX_FILES_PER_MESSAGE,
    AttachmentError,
    save_staging,
    sweep_staging,
)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("")
async def upload_attachments(files: list[UploadFile], user: CurrentUserId) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")
    if len(files) > MAX_FILES_PER_MESSAGE:
        raise HTTPException(
            status_code=400, detail=f"单条消息最多 {MAX_FILES_PER_MESSAGE} 个附件"
        )
    sweep_staging(user)  # 顺手清理超期暂存
    metas = []
    for f in files:
        data = await f.read()
        try:
            meta = save_staging(user, f.filename or "未命名", data)
        except AttachmentError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        # 文本不回传前端（体积与篡改面），只给展示用元数据
        metas.append({k: v for k, v in meta.items() if k != "text"})
    return {"attachments": metas}
