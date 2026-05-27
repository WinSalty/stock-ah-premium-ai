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
from app.db.models.image_generation import AiImageGeneration, AiImageUserQuota
from app.schemas.image_generation import (
    ImageGenerationAdminQuotaResponse,
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

IMAGE_GENERATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
IMAGE_GENERATION_PROVIDER = "86gamestore"
IMAGE_GENERATION_STATUS_GENERATING = "GENERATING"
IMAGE_GENERATION_STATUS_READY = "READY"
IMAGE_GENERATION_STATUS_FAILED = "FAILED"
IMAGE_GENERATION_MODE_TEXT = "TEXT_TO_IMAGE"
IMAGE_GENERATION_MODE_REFERENCE = "IMAGE_REFERENCE"
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


@dataclass(frozen=True)
class StoredImageFile:
    """已落盘图片文件信息。

    创建日期：2026-05-27
    author: sunshengxian
    """

    relative_path: str
    mime_type: str
    size_bytes: int
    sha256: str


class ImageGenerationService:
    """图片生成、用户隔离、本地存储和次数控制服务。

    创建日期：2026-05-27
    author: sunshengxian
    """

    def __init__(
        self,
        db: Session,
        settings: Settings | None = None,
        client: ImageGenerationClient | None = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        self.client = client or ImageGenerationClient(self.settings)

    def create_generation(
        self,
        user: AppUser,
        prompt: str,
        size: str | None = None,
        reference_image: UploadedReferenceImage | None = None,
    ) -> ImageGenerationResponse:
        """创建图片生成记录，失败时返还本次扣减次数。

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

        started_at = perf_counter()
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

            if stored_reference is not None and reference_image is not None:
                provider_result = self.client.generate_with_reference(
                    normalized_prompt,
                    normalized_size,
                    self.settings.image_gen_model,
                    ReferenceImagePayload(
                        filename=reference_image.filename or "reference.png",
                        content=reference_image.content,
                        mime_type=stored_reference.mime_type,
                    ),
                )
            else:
                provider_result = self.client.generate(
                    normalized_prompt,
                    normalized_size,
                    self.settings.image_gen_model,
                )

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
            self.db.refresh(record)
            quota = self.get_user_quota(user.id)
            return self.record_response(record, user, quota)
        except ImageGenerationUnsupportedError as exc:
            return self._mark_failed_and_refund(record, user, str(exc), started_at)
        except (ImageGenerationClientError, httpx.HTTPError, OSError, ValueError) as exc:
            return self._mark_failed_and_refund(record, user, str(exc), started_at)

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
            conditions.append(AiImageGeneration.status == status.strip().upper())
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
        path = self._storage_root().joinpath(relative_path).resolve()
        storage_root = self._storage_root().resolve()
        if not path.is_relative_to(storage_root) or not path.exists():
            raise ImageGenerationError("图片文件不存在", 404)
        return path, mime_type

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

    def record_response(
        self,
        record: AiImageGeneration,
        owner: AppUser | None = None,
        quota: ImageGenerationQuotaResponse | None = None,
    ) -> ImageGenerationResponse:
        """转换图片记录为前端响应，不暴露本地绝对路径。

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
                f"/api/image-generation/generations/{record.id}/file"
                if record.file_relative_path
                else None
            ),
            reference_image_url=(
                f"/api/image-generation/generations/{record.id}/reference-file"
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
        """供应商或落盘失败时返还本次扣减次数，最低不会小于 0。

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
    ) -> ImageGenerationResponse:
        """记录失败并返还次数，保留失败流水便于用户回看和复制 prompt。

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
        self.db.commit()
        self.db.refresh(record)
        self._refund_quota(user.id)
        return self.record_response(record, user, self.get_user_quota(user.id))

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
            raise ValueError("生成图片超过本地保存上限")
        detected_mime_type = self._detect_mime_type(image_bytes, mime_type)
        if detected_mime_type not in SUPPORTED_REFERENCE_MIME_TYPES:
            detected_mime_type = "image/png"
        return self._store_bytes(record, user, image_bytes, detected_mime_type, category="outputs")

    def _store_bytes(
        self,
        record: AiImageGeneration,
        user: AppUser,
        content: bytes,
        mime_type: str,
        category: str,
    ) -> StoredImageFile:
        """按日期和用户分目录原子写入图片文件。

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
        target_path = self._storage_root() / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        tmp_path.write_bytes(content)
        tmp_path.replace(target_path)
        return StoredImageFile(
            relative_path=relative_path.as_posix(),
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
            raise ValueError("生成图片超过本地保存上限")
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

    def _storage_root(self) -> Path:
        """返回独立数据盘图片存储根目录。

        创建日期：2026-05-27
        author: sunshengxian
        """

        return self.settings.image_gen_storage_dir

    def _today(self) -> date:
        """按东八区计算用户每日次数日期。

        创建日期：2026-05-27
        author: sunshengxian
        """

        return datetime.now(IMAGE_GENERATION_TIMEZONE).date()
