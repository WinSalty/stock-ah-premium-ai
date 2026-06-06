from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models.auth import AppUser
from app.db.models.image_generation import (
    AiImageGeneration,
    AiImageGenerationErrorLog,
    AiImageUserQuota,
)
from app.db.session import SessionLocal
from app.schemas.image_generation import (
    ImageGenerationAdminQuotaResponse,
    ImageGenerationErrorLogResponse,
    ImageGenerationListResponse,
    ImageGenerationQuotaResponse,
    ImageGenerationResponse,
)
from app.services.auth_service import ROLE_ADMIN
from app.services.image_generation_client import (
    ImageGenerationClient,
    ImageGenerationClientError,
    ImageGenerationUnsupportedError,
    ReferenceImagePayload,
)
from app.services.image_generation_storage_service import (
    ImageGenerationStorage,
    ImageGenerationStorageError,
    ImageGenerationStorageService,
    StoredImageFile,
)

IMAGE_GENERATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
IMAGE_GENERATION_PROVIDER = "86gamestore"
IMAGE_GENERATION_STATUS_GENERATING = "GENERATING"
IMAGE_GENERATION_STATUS_READY = "READY"
IMAGE_GENERATION_STATUS_FAILED = "FAILED"
IMAGE_GENERATION_MODE_TEXT = "TEXT_TO_IMAGE"
IMAGE_GENERATION_MODE_REFERENCE = "IMAGE_REFERENCE"
IMAGE_GENERATION_USER_FAILED_MESSAGE = "图片生成失败，请稍后重试或联系管理员查看原因。"
SUPPORTED_IMAGE_SIZES = {
    "1024x1024",
    "2048x2048",
    "1536x1024",
    "1024x1536",
    "3840x2160",
    "2160x3840",
}
DEFAULT_IMAGE_SIZE = "1024x1024"
SUPPORTED_REFERENCE_MIME_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_IMAGE_BYTES = 60 * 1024 * 1024


class ImageGenerationError(ValueError):
    """图片生成业务错误。

    创建日期：2026-05-27
    author: sunshengxian
    """

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class UploadedReferenceImage:
    """用户上传参考图。

    创建日期：2026-05-27
    author: sunshengxian
    """

    filename: str
    content: bytes
    mime_type: str | None


class ImageGenerationService:
    """图片生成、用户隔离、OSS 存储和次数控制服务。

    创建日期：2026-05-27
    author: sunshengxian
    """

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        client: ImageGenerationClient | None = None,
        storage: ImageGenerationStorage | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.client = client or ImageGenerationClient(self.settings)
        self.storage = storage or ImageGenerationStorageService(self.settings)

    def create_generation(
        self,
        user: AppUser,
        prompt: str,
        size: str | None = None,
        reference_image: UploadedReferenceImage | None = None,
    ) -> ImageGenerationResponse:
        """创建图片生成任务并立即返回，实际供应商调用由后台任务继续处理。

        创建日期：2026-05-27
        author: sunshengxian
        """

        normalized_prompt = self._validate_prompt(prompt)
        normalized_size = self._validate_size(size)
        quota = self._consume_quota(user.id)
        record = AiImageGeneration(
            user_id=user.id,
            prompt=normalized_prompt,
            model=self.settings.image_gen_model,
            size=normalized_size,
            status=IMAGE_GENERATION_STATUS_GENERATING,
            provider=IMAGE_GENERATION_PROVIDER,
            generation_mode=(
                IMAGE_GENERATION_MODE_REFERENCE
                if reference_image
                else IMAGE_GENERATION_MODE_TEXT
            ),
            request_payload_json=json.dumps(
                {
                    "model": self.settings.image_gen_model,
                    "prompt": normalized_prompt,
                    "size": normalized_size,
                    "n": 1,
                    "has_reference_image": bool(reference_image),
                },
                ensure_ascii=False,
            ),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        try:
            stored_reference = (
                self._store_reference_image(record, user, reference_image)
                if reference_image
                else None
            )
            if stored_reference is not None:
                record.reference_file_relative_path = stored_reference.relative_path
                record.reference_mime_type = stored_reference.mime_type
                record.reference_file_size_bytes = stored_reference.size_bytes
                record.reference_file_sha256 = stored_reference.sha256
                self.db.commit()
            self.db.refresh(record)
            return self.record_response(record, user, quota)
        except (OSError, ValueError) as exc:
            # 参考图大小、格式、空文件属于用户可自行修正的上传校验问题；
            # 服务器文件系统异常仍只给通用文案，详细原因保留在管理员日志中。
            user_message = (
                str(exc)
                if isinstance(exc, ValueError)
                else IMAGE_GENERATION_USER_FAILED_MESSAGE
            )
            return self._mark_failed_and_refund(
                record,
                user,
                user_message,
                perf_counter(),
                detail_message=str(exc),
                phase="store_reference",
                error_type=exc.__class__.__name__,
            )

    def retry_generation(self, user: AppUser, generation_id: int) -> ImageGenerationResponse:
        """按原图片记录重新创建生成任务，复用 prompt、尺寸和参考图。

        创建日期：2026-06-05
        author: sunshengxian
        """

        original_record = self.get_generation(user, generation_id)
        if original_record.status != IMAGE_GENERATION_STATUS_FAILED:
            raise ImageGenerationError("只有失败的图片记录可以重试")
        owner = self.db.get(AppUser, original_record.user_id)
        if owner is None:
            raise ImageGenerationError("图片所属用户不存在", 404)
        reference_image = None
        if original_record.reference_file_relative_path:
            # 重试带参考图的任务时先从存储读取原参考图，再进入 create_generation 扣次数；
            # 这样参考图对象缺失不会误消耗用户今日生成次数。
            reference_filename, reference_content, reference_mime_type = (
                self._reference_payload(original_record)
            )
            reference_image = UploadedReferenceImage(
                filename=reference_filename,
                content=reference_content,
                mime_type=reference_mime_type,
            )
        return self.create_generation(
            owner,
            original_record.prompt,
            original_record.size,
            reference_image,
        )

    def process_generation(self, generation_id: int) -> None:
        """后台处理图片生成任务，用户离开页面后仍继续推进记录状态。

        创建日期：2026-06-05
        author: sunshengxian
        """

        record = self.db.get(AiImageGeneration, generation_id)
        if record is None or record.deleted_at is not None:
            return
        if record.status != IMAGE_GENERATION_STATUS_GENERATING:
            return
        user = self.db.get(AppUser, record.user_id)
        if user is None:
            self._mark_failed_and_refund(
                record,
                AppUser(id=record.user_id, username="", password_hash="", role="USER"),
                IMAGE_GENERATION_USER_FAILED_MESSAGE,
                perf_counter(),
                detail_message="图片所属用户不存在",
                phase="load_user",
                error_type="UserNotFound",
            )
            return

        started_at = perf_counter()
        try:
            if record.reference_file_relative_path:
                reference_filename, reference_content, reference_mime_type = (
                    self._reference_payload(record)
                )
                provider_result = self.client.generate_with_reference(
                    record.prompt,
                    record.size,
                    record.model,
                    ReferenceImagePayload(
                        filename=reference_filename,
                        content=reference_content,
                        mime_type=reference_mime_type,
                    ),
                )
            else:
                provider_result = self.client.generate(record.prompt, record.size, record.model)

            image_bytes = provider_result.image_bytes
            external_url = provider_result.image_url
            if image_bytes is None and external_url:
                image_bytes, mime_type = self._download_provider_image(external_url)
                provider_mime_type = mime_type
            else:
                provider_mime_type = provider_result.mime_type
            if image_bytes is None:
                raise ImageGenerationClientError("文生图服务未返回可保存的图片")

            stored_output = self._store_output_image(record, user, image_bytes, provider_mime_type)
            record.status = IMAGE_GENERATION_STATUS_READY
            record.mime_type = stored_output.mime_type
            record.file_relative_path = stored_output.relative_path
            record.file_size_bytes = stored_output.size_bytes
            record.file_sha256 = stored_output.sha256
            record.external_url_expires_unknown = bool(external_url)
            record.response_summary_json = json.dumps(
                provider_result.response_summary,
                ensure_ascii=False,
            )
            record.elapsed_ms = (perf_counter() - started_at) * 1000
            record.error_message = None
            self.db.commit()
        except ImageGenerationUnsupportedError as exc:
            self._mark_failed_and_refund(
                record,
                user,
                "当前暂不支持参考图生成，请移除参考图后重试。",
                started_at,
                detail_message=str(exc),
                phase="provider_reference",
                error_type=exc.__class__.__name__,
                status_code=exc.status_code,
            )
        except (
            ImageGenerationClientError,
            ImageGenerationStorageError,
            httpx.HTTPError,
            OSError,
            ValueError,
        ) as exc:
            self._mark_failed_and_refund(
                record,
                user,
                IMAGE_GENERATION_USER_FAILED_MESSAGE,
                started_at,
                detail_message=str(exc),
                phase="generate",
                error_type=exc.__class__.__name__,
                status_code=getattr(exc, "status_code", None),
                retry_count=getattr(exc, "retry_count", 0),
            )
        except Exception as exc:
            # 后台任务不能把未知异常抛回已关闭的前端请求；这里统一转为失败记录和管理员日志，
            # 避免用户下次进入页面时看到任务长期停留在“生成中”。
            self._mark_failed_and_refund(
                record,
                user,
                IMAGE_GENERATION_USER_FAILED_MESSAGE,
                started_at,
                detail_message=str(exc),
                phase="unexpected",
                error_type=exc.__class__.__name__,
            )

    def list_generations(
        self,
        user: AppUser,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        user_id: int | None = None,
        keyword: str | None = None,
    ) -> ImageGenerationListResponse:
        """查询图片记录，普通用户只能读取自己的图片。

        创建日期：2026-05-27
        author: sunshengxian
        """

        page = max(page, 1)
        page_size = min(max(page_size, 1), 100)
        conditions = [AiImageGeneration.deleted_at.is_(None)]
        if user.role != ROLE_ADMIN:
            conditions.append(AiImageGeneration.user_id == user.id)
        elif user_id:
            conditions.append(AiImageGeneration.user_id == user_id)
        if status:
            # 历史图库默认只展示生成中和已完成记录；这里允许前端用逗号传多个状态，
            # 管理员仍可选择单个 FAILED 状态查看失败任务和错误详情。
            status_values = [
                item.strip().upper()
                for item in status.split(",")
                if item.strip()
            ]
            if status_values:
                conditions.append(AiImageGeneration.status.in_(status_values))
        if keyword:
            like_value = f"%{keyword.strip()}%"
            conditions.append(
                or_(
                    AiImageGeneration.prompt.like(like_value),
                    AppUser.username.like(like_value),
                )
            )
        total = self.db.scalar(
            select(func.count())
            .select_from(AiImageGeneration)
            .join(AppUser, AppUser.id == AiImageGeneration.user_id)
            .where(*conditions)
        )
        rows = list(
            self.db.execute(
                select(AiImageGeneration, AppUser)
                .join(AppUser, AppUser.id == AiImageGeneration.user_id)
                .where(*conditions)
                .order_by(AiImageGeneration.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        )
        return ImageGenerationListResponse(
            total=int(total or 0),
            items=[self.record_response(record, owner) for record, owner in rows],
        )

    def get_generation(self, user: AppUser, generation_id: int) -> AiImageGeneration:
        """读取单条图片记录并校验用户隔离。

        创建日期：2026-05-27
        author: sunshengxian
        """

        record = self.db.get(AiImageGeneration, generation_id)
        if record is None or record.deleted_at is not None:
            raise ImageGenerationError("图片记录不存在", 404)
        if user.role != ROLE_ADMIN and record.user_id != user.id:
            raise ImageGenerationError("没有访问该图片的权限", 403)
        return record

    def delete_generation(self, user: AppUser, generation_id: int) -> None:
        """逻辑删除图片记录，不物理删除 OSS 对象和错误日志。

        创建日期：2026-06-06
        author: sunshengxian
        """

        record = self.get_generation(user, generation_id)
        # deleted_at 按东八区 naive 写入，和项目内会话逻辑删除口径保持一致；
        # 删除只影响历史展示和后续访问鉴权，不回收已消耗的生成次数，也不删除 OSS 对象。
        record.deleted_at = datetime.now(IMAGE_GENERATION_TIMEZONE).replace(tzinfo=None)
        self.db.commit()

    def image_file_path(
        self,
        user: AppUser,
        generation_id: int,
        reference: bool = False,
    ) -> tuple[Path, str]:
        """解析图片文件路径，返回前必须完成记录权限校验。

        创建日期：2026-05-27
        author: sunshengxian
        """

        record = self.get_generation(user, generation_id)
        relative_path = (
            record.reference_file_relative_path if reference else record.file_relative_path
        )
        mime_type = record.reference_mime_type if reference else record.mime_type
        if not relative_path or not mime_type:
            raise ImageGenerationError("图片文件不存在", 404)
        if not self.storage.is_local:
            raise ImageGenerationError("当前图片已切换为 OSS 签名 URL 访问", 410)
        path = self.storage.local_file_path(relative_path)
        if not path.exists():
            raise ImageGenerationError("图片文件不存在", 404)
        return path, mime_type

    def image_file_signed_url(
        self,
        user: AppUser,
        generation_id: int,
        reference: bool = False,
    ) -> str:
        """鉴权后生成一天有效的图片 OSS 签名 URL。

        创建日期：2026-06-06
        author: sunshengxian
        """

        record = self.get_generation(user, generation_id)
        relative_path = (
            record.reference_file_relative_path if reference else record.file_relative_path
        )
        if not relative_path:
            raise ImageGenerationError("图片文件不存在", 404)
        return self.storage.signed_url(relative_path)

    def get_user_quota(self, user_id: int) -> ImageGenerationQuotaResponse:
        """读取用户今日图片生成次数，跨日时懒重置。

        创建日期：2026-05-27
        author: sunshengxian
        """

        quota = self._get_or_create_quota(user_id)
        today = self._today()
        if quota.quota_date != today:
            quota.quota_date = today
            quota.used_count = 0
            self.db.commit()
            self.db.refresh(quota)
        return self.quota_response(quota)

    def list_admin_quotas(self) -> list[ImageGenerationAdminQuotaResponse]:
        """管理员查询所有用户图片生成次数配置。

        创建日期：2026-05-27
        author: sunshengxian
        """

        users = list(self.db.scalars(select(AppUser).order_by(AppUser.id)).all())
        return [
            self.admin_quota_response(user, self._get_or_create_quota(user.id))
            for user in users
        ]

    def update_user_quota(
        self,
        admin_user: AppUser,
        user_id: int,
        daily_limit: int,
    ) -> ImageGenerationAdminQuotaResponse:
        """管理员修改单个用户每日生成上限。

        创建日期：2026-05-27
        author: sunshengxian
        """

        if daily_limit < 0 or daily_limit > 100:
            raise ImageGenerationError("每日次数必须在 0 到 100 之间")
        user = self.db.get(AppUser, user_id)
        if user is None:
            raise ImageGenerationError("用户不存在", 404)
        quota = self._get_or_create_quota(user_id)
        quota.daily_limit = daily_limit
        quota.updated_by_user_id = admin_user.id
        self.db.commit()
        self.db.refresh(quota)
        return self.admin_quota_response(user, quota)

    def reset_user_quota(
        self,
        admin_user: AppUser,
        user_id: int,
    ) -> ImageGenerationAdminQuotaResponse:
        """管理员重置用户今日已用次数。

        创建日期：2026-05-27
        author: sunshengxian
        """

        user = self.db.get(AppUser, user_id)
        if user is None:
            raise ImageGenerationError("用户不存在", 404)
        quota = self._get_or_create_quota(user_id)
        quota.quota_date = self._today()
        quota.used_count = 0
        quota.last_reset_at = datetime.now(UTC).replace(tzinfo=None)
        quota.updated_by_user_id = admin_user.id
        self.db.commit()
        self.db.refresh(quota)
        return self.admin_quota_response(user, quota)

    def list_error_logs(
        self,
        admin_user: AppUser,
        generation_id: int,
    ) -> list[ImageGenerationErrorLogResponse]:
        """管理员查看单条图片生成失败的详细日志。

        创建日期：2026-06-05
        author: sunshengxian
        """

        if admin_user.role != ROLE_ADMIN:
            raise ImageGenerationError("没有访问权限", 403)
        rows = list(
            self.db.scalars(
                select(AiImageGenerationErrorLog)
                .where(AiImageGenerationErrorLog.generation_id == generation_id)
                .order_by(AiImageGenerationErrorLog.id.desc())
            ).all()
        )
        return [self.error_log_response(row) for row in rows]

    def record_response(
        self,
        record: AiImageGeneration,
        owner: AppUser | None = None,
        quota: ImageGenerationQuotaResponse | None = None,
    ) -> ImageGenerationResponse:
        """转换图片记录为前端响应，不暴露本地绝对路径或未鉴权永久对象地址。

        创建日期：2026-05-27
        author: sunshengxian
        """

        owner = owner or self.db.get(AppUser, record.user_id)
        return ImageGenerationResponse(
            id=record.id,
            user_id=record.user_id,
            username=owner.username if owner else None,
            display_name=owner.display_name if owner else None,
            prompt=record.prompt,
            model=record.model,
            size=record.size,
            status=record.status,
            provider=record.provider,
            generation_mode=record.generation_mode,
            image_url=(
                self._image_access_url(record, reference=False)
                if record.file_relative_path
                else None
            ),
            reference_image_url=(
                self._image_access_url(record, reference=True)
                if record.reference_file_relative_path
                else None
            ),
            mime_type=record.mime_type,
            file_size_bytes=record.file_size_bytes,
            file_sha256=record.file_sha256,
            reference_mime_type=record.reference_mime_type,
            reference_file_size_bytes=record.reference_file_size_bytes,
            reference_file_sha256=record.reference_file_sha256,
            elapsed_ms=record.elapsed_ms,
            error_message=record.error_message,
            quota=quota,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def quota_response(self, quota: AiImageUserQuota) -> ImageGenerationQuotaResponse:
        """转换 quota 为当前可用次数响应。

        创建日期：2026-05-27
        author: sunshengxian
        """

        used_count = max(quota.used_count, 0)
        daily_limit = max(quota.daily_limit, 0)
        return ImageGenerationQuotaResponse(
            daily_limit=daily_limit,
            used_count=used_count,
            remaining_count=max(daily_limit - used_count, 0),
            quota_date=quota.quota_date or self._today(),
        )

    def admin_quota_response(
        self,
        user: AppUser,
        quota: AiImageUserQuota,
    ) -> ImageGenerationAdminQuotaResponse:
        """转换管理员用户次数维护响应。

        创建日期：2026-05-27
        author: sunshengxian
        """

        response = self.quota_response(quota)
        return ImageGenerationAdminQuotaResponse(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
            daily_limit=response.daily_limit,
            used_count=response.used_count,
            remaining_count=response.remaining_count,
            quota_date=response.quota_date,
            last_reset_at=quota.last_reset_at,
            updated_at=quota.updated_at,
        )

    def error_log_response(
        self,
        log: AiImageGenerationErrorLog,
    ) -> ImageGenerationErrorLogResponse:
        """转换图片生成错误日志响应，仅用于管理员排查。

        创建日期：2026-06-05
        author: sunshengxian
        """

        return ImageGenerationErrorLogResponse(
            id=log.id,
            generation_id=log.generation_id,
            user_id=log.user_id,
            provider=log.provider,
            model=log.model,
            phase=log.phase,
            retry_count=log.retry_count,
            status_code=log.status_code,
            error_type=log.error_type,
            user_message=log.user_message,
            detail_message=log.detail_message,
            created_at=log.created_at,
        )

    def _consume_quota(self, user_id: int) -> ImageGenerationQuotaResponse:
        """生成前扣减次数，使用行锁避免并发越过每日上限。

        创建日期：2026-05-27
        author: sunshengxian
        """

        quota = self._get_or_create_quota(user_id, for_update=True)
        today = self._today()
        if quota.quota_date != today:
            quota.quota_date = today
            quota.used_count = 0
        if quota.used_count >= quota.daily_limit:
            self.db.commit()
            raise ImageGenerationError("今日图片生成次数已用完，请明天再试或联系管理员重置。", 429)
        quota.used_count += 1
        self.db.commit()
        self.db.refresh(quota)
        return self.quota_response(quota)

    def _refund_quota(self, user_id: int) -> None:
        """供应商或存储失败时返还本次扣减次数，最低不会小于 0。

        创建日期：2026-05-27
        author: sunshengxian
        """

        quota = self._get_or_create_quota(user_id, for_update=True)
        if quota.quota_date == self._today():
            quota.used_count = max(quota.used_count - 1, 0)
            self.db.commit()

    def _get_or_create_quota(self, user_id: int, for_update: bool = False) -> AiImageUserQuota:
        """读取或创建用户次数配置，确保老用户首次使用也有默认限制。

        创建日期：2026-05-27
        author: sunshengxian
        """

        statement = select(AiImageUserQuota).where(AiImageUserQuota.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        quota = self.db.scalar(statement)
        if quota is not None:
            return quota
        quota = AiImageUserQuota(
            user_id=user_id,
            daily_limit=max(self.settings.image_gen_daily_limit_default, 0),
            quota_date=self._today(),
            used_count=0,
        )
        self.db.add(quota)
        self.db.commit()
        self.db.refresh(quota)
        return quota

    def _mark_failed_and_refund(
        self,
        record: AiImageGeneration,
        user: AppUser,
        message: str,
        started_at: float,
        detail_message: str,
        phase: str,
        error_type: str,
        status_code: int | None = None,
        retry_count: int = 0,
    ) -> ImageGenerationResponse:
        """记录失败摘要、返还次数，并把详细异常写入管理员日志表。

        创建日期：2026-05-27
        author: sunshengxian
        """

        record.status = IMAGE_GENERATION_STATUS_FAILED
        record.error_message = self._safe_error_message(message)
        record.elapsed_ms = (perf_counter() - started_at) * 1000
        record.response_summary_json = json.dumps(
            {"error": record.error_message},
            ensure_ascii=False,
        )
        self._append_error_log(
            record,
            record.error_message,
            detail_message,
            phase,
            error_type,
            status_code,
            retry_count,
        )
        self.db.commit()
        self.db.refresh(record)
        self._refund_quota(user.id)
        return self.record_response(record, user, self.get_user_quota(user.id))

    def _append_error_log(
        self,
        record: AiImageGeneration,
        user_message: str,
        detail_message: str,
        phase: str,
        error_type: str,
        status_code: int | None,
        retry_count: int,
    ) -> None:
        """写入图片生成错误详情，供管理员查看而不直接暴露给普通用户。

        创建日期：2026-06-05
        author: sunshengxian
        """

        self.db.add(
            AiImageGenerationErrorLog(
                generation_id=record.id,
                user_id=record.user_id,
                provider=record.provider,
                model=record.model,
                phase=phase,
                retry_count=max(retry_count, 0),
                status_code=status_code,
                error_type=error_type[:128],
                user_message=user_message,
                detail_message=self._safe_detail_message(detail_message),
            )
        )

    def _store_reference_image(
        self,
        record: AiImageGeneration,
        user: AppUser,
        reference_image: UploadedReferenceImage,
    ) -> StoredImageFile:
        """校验并保存用户参考图，供供应商图生图能力复用。

        创建日期：2026-05-27
        author: sunshengxian
        """

        if not reference_image.content:
            raise ValueError("参考图不能为空")
        if len(reference_image.content) > MAX_REFERENCE_IMAGE_BYTES:
            raise ValueError("参考图不能超过 10MB")
        mime_type = self._detect_mime_type(reference_image.content, reference_image.mime_type)
        if mime_type not in SUPPORTED_REFERENCE_MIME_TYPES:
            raise ValueError("参考图只支持 PNG、JPG 或 WebP")
        return self._store_bytes(
            record,
            user,
            reference_image.content,
            mime_type,
            category="references",
        )

    def _store_output_image(
        self,
        record: AiImageGeneration,
        user: AppUser,
        image_bytes: bytes,
        mime_type: str,
    ) -> StoredImageFile:
        """保存供应商生成图片，文件名不包含 prompt，避免泄露用户输入。

        创建日期：2026-05-27
        author: sunshengxian
        """

        if len(image_bytes) > MAX_OUTPUT_IMAGE_BYTES:
            raise ValueError("生成图片超过保存上限")
        detected_mime_type = self._detect_mime_type(image_bytes, mime_type)
        if detected_mime_type not in SUPPORTED_REFERENCE_MIME_TYPES:
            raise ValueError("生成结果不是可识别的图片文件")
        return self._store_bytes(record, user, image_bytes, detected_mime_type, category="outputs")

    def _reference_payload(self, record: AiImageGeneration) -> tuple[str, bytes, str]:
        """读取已保存参考图，后台任务用它重新组装供应商请求。

        创建日期：2026-06-05
        author: sunshengxian
        """

        if not record.reference_file_relative_path or not record.reference_mime_type:
            raise ValueError("参考图文件不存在")
        return (
            Path(record.reference_file_relative_path).name,
            self.storage.read_bytes(record.reference_file_relative_path),
            record.reference_mime_type,
        )

    def _store_bytes(
        self,
        record: AiImageGeneration,
        user: AppUser,
        content: bytes,
        mime_type: str,
        category: str,
    ) -> StoredImageFile:
        """按日期、用户和短 hash 生成对象键，并写入当前存储后端。

        创建日期：2026-05-27
        author: sunshengxian
        """

        sha256 = hashlib.sha256(content).hexdigest()
        today = self._today()
        extension = SUPPORTED_REFERENCE_MIME_TYPES.get(mime_type, ".png")
        relative_dir = (
            Path(category)
            / f"{today:%Y}"
            / f"{today:%m}"
            / f"{today:%d}"
            / f"user-{user.id}"
        )
        filename = (
            f"{datetime.now(IMAGE_GENERATION_TIMEZONE):%Y%m%d-%H%M%S}-"
            f"{record.id}-{sha256[:12]}{extension}"
        )
        relative_path = relative_dir / filename
        storage_key = self.storage.build_storage_key(relative_path.as_posix())
        self.storage.save_bytes(storage_key, content, mime_type)
        return StoredImageFile(
            relative_path=storage_key,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=sha256,
        )

    def _download_provider_image(self, image_url: str) -> tuple[bytes, str]:
        """下载供应商 URL 图片并限制最大体积，避免长期依赖外链。

        创建日期：2026-05-27
        author: sunshengxian
        """

        with httpx.Client(timeout=self.settings.image_gen_timeout_seconds) as client:
            response = client.get(image_url)
            response.raise_for_status()
        content = response.content
        if len(content) > MAX_OUTPUT_IMAGE_BYTES:
            raise ValueError("生成图片超过保存上限")
        return content, response.headers.get("content-type", "image/png").split(";")[0].strip()

    def _validate_prompt(self, prompt: str) -> str:
        """校验提示词长度，避免空请求或超大请求打到供应商。

        创建日期：2026-05-27
        author: sunshengxian
        """

        normalized = prompt.strip()
        if not normalized:
            raise ImageGenerationError("请输入图片描述")
        if len(normalized) > 4000:
            raise ImageGenerationError("图片描述不能超过 4000 字")
        return normalized

    def _validate_size(self, size: str | None) -> str:
        """校验用户选择的尺寸，默认使用最低成本 1K。

        创建日期：2026-05-27
        author: sunshengxian
        """

        normalized = (size or DEFAULT_IMAGE_SIZE).strip()
        if normalized not in SUPPORTED_IMAGE_SIZES:
            raise ImageGenerationError("图片尺寸不支持")
        return normalized

    def _detect_mime_type(self, content: bytes, fallback: str | None) -> str:
        """根据文件头识别图片类型，避免只信任浏览器上传的 Content-Type。

        创建日期：2026-05-27
        author: sunshengxian
        """

        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            return "image/webp"
        return (fallback or "image/png").split(";")[0].strip().lower()

    def _safe_error_message(self, message: str) -> str:
        """截断错误摘要，避免数据库和前端展示过长供应商响应。

        创建日期：2026-05-27
        author: sunshengxian
        """

        return (message or "图片生成失败").strip()[:512]

    def _safe_detail_message(self, message: str) -> str:
        """截断管理员错误详情，避免供应商完整响应撑爆日志表。

        创建日期：2026-06-05
        author: sunshengxian
        """

        return (message or "图片生成失败").strip()[:4000]

    def _image_access_url(self, record: AiImageGeneration, reference: bool = False) -> str:
        """按当前存储后端返回前端可访问 URL。

        创建日期：2026-06-06
        author: sunshengxian
        """

        if self.storage.is_local:
            suffix = "reference-file" if reference else "file"
            return f"/api/image-generation/generations/{record.id}/{suffix}"
        relative_path = (
            record.reference_file_relative_path if reference else record.file_relative_path
        )
        if not relative_path:
            raise ImageGenerationError("图片文件不存在", 404)
        return self.storage.signed_url(relative_path)

    def _today(self) -> date:
        """按东八区计算用户每日次数日期。

        创建日期：2026-05-27
        author: sunshengxian
        """

        return datetime.now(IMAGE_GENERATION_TIMEZONE).date()


def process_image_generation_background(generation_id: int) -> None:
    """使用独立数据库会话执行图片生成后台任务。

    创建日期：2026-06-05
    author: sunshengxian
    """

    db = SessionLocal()
    try:
        ImageGenerationService(db).process_generation(generation_id)
    finally:
        db.close()
