from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.deps_auth import DbSession, require_permission
from app.db.models.auth import AppUser
from app.schemas.image_generation import (
    ImageGenerationAdminQuotaResponse,
    ImageGenerationListResponse,
    ImageGenerationQuotaResponse,
    ImageGenerationQuotaUpdateRequest,
    ImageGenerationResponse,
)
from app.services.image_generation_service import (
    ImageGenerationError,
    ImageGenerationService,
    UploadedReferenceImage,
)

router = APIRouter()
ImageGenerationUser = Annotated[AppUser, Depends(require_permission("image_generation"))]
AdminUser = Annotated[AppUser, Depends(require_permission("users"))]
ImagePromptForm = Annotated[str, Form()]
ImageSizeForm = Annotated[str, Form()]
ReferenceImageFile = Annotated[UploadFile | None, File()]


@router.post("/image-generation/generations", response_model=ImageGenerationResponse)
async def create_image_generation(
    db: DbSession,
    user: ImageGenerationUser,
    prompt: ImagePromptForm,
    size: ImageSizeForm = "1024x1024",
    reference_image: ReferenceImageFile = None,
) -> ImageGenerationResponse:
    """创建图片生成任务，支持可选参考图上传。

    创建日期：2026-05-27
    author: sunshengxian
    """

    uploaded_reference = None
    if reference_image is not None and reference_image.filename:
        content = await reference_image.read()
        uploaded_reference = UploadedReferenceImage(
            filename=reference_image.filename,
            content=content,
            mime_type=reference_image.content_type,
        )
    try:
        return ImageGenerationService(db).create_generation(user, prompt, size, uploaded_reference)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/image-generation/generations", response_model=ImageGenerationListResponse)
def list_image_generations(
    db: DbSession,
    user: ImageGenerationUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    user_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> ImageGenerationListResponse:
    """查询图片生成历史，普通用户仅能查看自己的记录。

    创建日期：2026-05-27
    author: sunshengxian
    """

    return ImageGenerationService(db).list_generations(
        user,
        page,
        page_size,
        status,
        user_id,
        keyword,
    )


@router.get("/image-generation/generations/{generation_id}", response_model=ImageGenerationResponse)
def get_image_generation(
    generation_id: int,
    db: DbSession,
    user: ImageGenerationUser,
) -> ImageGenerationResponse:
    """查看图片生成详情。

    创建日期：2026-05-27
    author: sunshengxian
    """

    service = ImageGenerationService(db)
    try:
        return service.record_response(service.get_generation(user, generation_id))
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/image-generation/generations/{generation_id}/file")
def get_image_generation_file(
    generation_id: int,
    db: DbSession,
    user: ImageGenerationUser,
) -> FileResponse:
    """读取生成图片文件，必须先通过记录归属校验。

    创建日期：2026-05-27
    author: sunshengxian
    """

    try:
        path, mime_type = ImageGenerationService(db).image_file_path(user, generation_id)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=mime_type)


@router.get("/image-generation/generations/{generation_id}/reference-file")
def get_image_generation_reference_file(
    generation_id: int,
    db: DbSession,
    user: ImageGenerationUser,
) -> FileResponse:
    """读取参考图文件，仍按图片记录权限控制。

    创建日期：2026-05-27
    author: sunshengxian
    """

    try:
        path, mime_type = ImageGenerationService(db).image_file_path(
            user,
            generation_id,
            reference=True,
        )
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return FileResponse(path, media_type=mime_type)


@router.get("/image-generation/quota/me", response_model=ImageGenerationQuotaResponse)
def get_my_image_generation_quota(
    db: DbSession,
    user: ImageGenerationUser,
) -> ImageGenerationQuotaResponse:
    """读取当前用户今日图片生成剩余次数。

    创建日期：2026-05-27
    author: sunshengxian
    """

    return ImageGenerationService(db).get_user_quota(user.id)


@router.get(
    "/image-generation/admin/quotas",
    response_model=list[ImageGenerationAdminQuotaResponse],
)
def list_image_generation_quotas(
    db: DbSession,
    admin_user: AdminUser,
) -> list[ImageGenerationAdminQuotaResponse]:
    """管理员查询所有用户文生图次数配置。

    创建日期：2026-05-27
    author: sunshengxian
    """

    return ImageGenerationService(db).list_admin_quotas()


@router.patch(
    "/image-generation/admin/quotas/{user_id}",
    response_model=ImageGenerationAdminQuotaResponse,
)
def update_image_generation_quota(
    user_id: int,
    payload: ImageGenerationQuotaUpdateRequest,
    db: DbSession,
    admin_user: AdminUser,
) -> ImageGenerationAdminQuotaResponse:
    """管理员修改用户每日文生图上限。

    创建日期：2026-05-27
    author: sunshengxian
    """

    try:
        return ImageGenerationService(db).update_user_quota(
            admin_user,
            user_id,
            payload.daily_limit,
        )
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post(
    "/image-generation/admin/quotas/{user_id}/reset",
    response_model=ImageGenerationAdminQuotaResponse,
)
def reset_image_generation_quota(
    user_id: int,
    db: DbSession,
    admin_user: AdminUser,
) -> ImageGenerationAdminQuotaResponse:
    """管理员重置用户今日文生图已用次数。

    创建日期：2026-05-27
    author: sunshengxian
    """

    try:
        return ImageGenerationService(db).reset_user_quota(admin_user, user_id)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
