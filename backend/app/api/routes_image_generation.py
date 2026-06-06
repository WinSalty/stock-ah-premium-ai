from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.api.deps_auth import DbSession, require_permission
from app.db.models.auth import AppUser
from app.schemas.image_generation import (
    ImageGenerationAdminQuotaResponse,
    ImageGenerationErrorLogResponse,
    ImageGenerationListResponse,
    ImageGenerationQuotaResponse,
    ImageGenerationQuotaUpdateRequest,
    ImageGenerationResponse,
)
from app.services.image_generation_service import (
    IMAGE_GENERATION_STATUS_GENERATING,
    ImageGenerationError,
    ImageGenerationService,
    UploadedReferenceImage,
    process_image_generation_background,
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
    background_tasks: BackgroundTasks,
    prompt: ImagePromptForm,
    size: ImageSizeForm = "1024x1024",
    reference_image: ReferenceImageFile = None,
) -> ImageGenerationResponse:
    """创建图片生成任务并交给后台继续处理，用户离开页面后仍可回看状态。

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
        response = ImageGenerationService(db).create_generation(
            user,
            prompt,
            size,
            uploaded_reference,
        )
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if response.status == IMAGE_GENERATION_STATUS_GENERATING:
        background_tasks.add_task(process_image_generation_background, response.id)
    return response


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


@router.post(
    "/image-generation/generations/{generation_id}/retry",
    response_model=ImageGenerationResponse,
)
def retry_image_generation(
    generation_id: int,
    db: DbSession,
    user: ImageGenerationUser,
    background_tasks: BackgroundTasks,
) -> ImageGenerationResponse:
    """一键重试失败图片，复用原描述、尺寸和参考图后重新进入后台生成。

    创建日期：2026-06-05
    author: sunshengxian
    """

    try:
        response = ImageGenerationService(db).retry_generation(user, generation_id)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    if response.status == IMAGE_GENERATION_STATUS_GENERATING:
        background_tasks.add_task(process_image_generation_background, response.id)
    return response


@router.delete("/image-generation/generations/{generation_id}", status_code=204)
def delete_image_generation(
    generation_id: int,
    db: DbSession,
    user: ImageGenerationUser,
) -> Response:
    """逻辑删除图片历史记录，保留 OSS 对象和审计日志。

    创建日期：2026-06-06
    author: sunshengxian
    """

    try:
        ImageGenerationService(db).delete_generation(user, generation_id)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/image-generation/generations/{generation_id}/file")
def get_image_generation_file(
    generation_id: int,
    db: DbSession,
    user: ImageGenerationUser,
) -> Response:
    """鉴权后读取生成图片；OSS 模式返回一天有效签名 URL 跳转。

    创建日期：2026-06-06
    author: sunshengxian
    """

    service = ImageGenerationService(db)
    try:
        if service.storage.is_local:
            path, mime_type = service.image_file_path(user, generation_id)
            return FileResponse(path, media_type=mime_type)
        return RedirectResponse(service.image_file_signed_url(user, generation_id), status_code=307)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/image-generation/generations/{generation_id}/reference-file")
def get_image_generation_reference_file(
    generation_id: int,
    db: DbSession,
    user: ImageGenerationUser,
) -> Response:
    """鉴权后读取参考图；OSS 模式返回一天有效签名 URL 跳转。

    创建日期：2026-06-06
    author: sunshengxian
    """

    service = ImageGenerationService(db)
    try:
        if service.storage.is_local:
            path, mime_type = service.image_file_path(user, generation_id, reference=True)
            return FileResponse(path, media_type=mime_type)
        return RedirectResponse(
            service.image_file_signed_url(user, generation_id, reference=True),
            status_code=307,
        )
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get(
    "/image-generation/generations/{generation_id}/error-logs",
    response_model=list[ImageGenerationErrorLogResponse],
)
def list_image_generation_error_logs(
    generation_id: int,
    db: DbSession,
    admin_user: AdminUser,
) -> list[ImageGenerationErrorLogResponse]:
    """管理员查看图片生成失败详情，普通用户响应不暴露供应商原始错误。

    创建日期：2026-06-05
    author: sunshengxian
    """

    try:
        return ImageGenerationService(db).list_error_logs(admin_user, generation_id)
    except ImageGenerationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
