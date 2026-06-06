from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.core.config import Settings

IMAGE_GENERATION_STORAGE_LOCAL = "local"
IMAGE_GENERATION_STORAGE_OSS = "oss"


class ImageGenerationStorageError(ValueError):
    """图片存储业务错误。

    创建日期：2026-06-06
    author: sunshengxian
    """


@dataclass(frozen=True)
class StoredImageFile:
    """已保存图片文件信息。

    创建日期：2026-06-06
    author: sunshengxian
    """

    relative_path: str
    mime_type: str
    size_bytes: int
    sha256: str


class ImageGenerationStorage(Protocol):
    """图片存储适配器协议，便于单测替换真实 OSS SDK。

    创建日期：2026-06-06
    author: sunshengxian
    """

    @property
    def is_local(self) -> bool:
        """标记当前是否仍使用本地文件系统，兼容单测和历史环境。

        创建日期：2026-06-06
        author: sunshengxian
        """

    def build_storage_key(self, relative_path: str) -> str:
        """生成最终入库的存储键。

        创建日期：2026-06-06
        author: sunshengxian
        """

    def save_bytes(self, storage_key: str, content: bytes, mime_type: str) -> None:
        """保存图片字节，调用方已完成大小和 MIME 校验。

        创建日期：2026-06-06
        author: sunshengxian
        """

    def read_bytes(self, storage_key: str) -> bytes:
        """读取图片字节，供参考图重试和供应商图生图请求使用。

        创建日期：2026-06-06
        author: sunshengxian
        """

    def signed_url(self, storage_key: str) -> str:
        """生成短期访问 URL，调用前必须已经完成业务权限校验。

        创建日期：2026-06-06
        author: sunshengxian
        """

    def local_file_path(self, storage_key: str) -> Path:
        """解析本地文件路径，仅在本地适配器下用于兼容文件代理接口。

        创建日期：2026-06-06
        author: sunshengxian
        """


class ImageGenerationStorageService:
    """图片生成存储适配器，生产环境使用阿里 OSS，单测可使用 local。

    创建日期：2026-06-06
    author: sunshengxian
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.backend = settings.image_gen_storage_backend.strip().lower()
        if self.backend not in {
            IMAGE_GENERATION_STORAGE_LOCAL,
            IMAGE_GENERATION_STORAGE_OSS,
        }:
            raise ImageGenerationStorageError("图片存储类型只支持 local 或 oss")
        self._bucket = None

    @property
    def is_local(self) -> bool:
        """标记当前是否使用本地文件系统。

        创建日期：2026-06-06
        author: sunshengxian
        """

        return self.backend == IMAGE_GENERATION_STORAGE_LOCAL

    def build_storage_key(self, relative_path: str) -> str:
        """生成最终入库键，OSS 模式会追加统一业务前缀。

        创建日期：2026-06-06
        author: sunshengxian
        """

        normalized_path = self._normalize_storage_key(relative_path)
        if self.is_local:
            return normalized_path
        prefix = self._normalize_storage_key(self.settings.image_gen_oss_prefix)
        return f"{prefix}/{normalized_path}" if prefix else normalized_path

    def save_bytes(self, storage_key: str, content: bytes, mime_type: str) -> None:
        """保存图片字节；OSS 模式直接写对象，本地模式保留原子替换。

        创建日期：2026-06-06
        author: sunshengxian
        """

        normalized_key = self._normalize_storage_key(storage_key)
        if self.is_local:
            target_path = self.local_file_path(normalized_key)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
            tmp_path.write_bytes(content)
            tmp_path.replace(target_path)
            return
        # OSS 对象上传是生成图片从供应商返回后的关键持久化步骤；
        # 这里显式写入 Content-Type，方便浏览器通过签名 URL 直接预览。
        self._oss_bucket().put_object(
            normalized_key,
            content,
            headers={"Content-Type": mime_type},
        )

    def read_bytes(self, storage_key: str) -> bytes:
        """读取图片字节，OSS 模式从私有 Bucket 拉取，不暴露对象公开权限。

        创建日期：2026-06-06
        author: sunshengxian
        """

        normalized_key = self._normalize_storage_key(storage_key)
        if self.is_local:
            path = self.local_file_path(normalized_key)
            if not path.exists():
                raise ImageGenerationStorageError("图片文件不存在")
            return path.read_bytes()
        try:
            return self._oss_bucket().get_object(normalized_key).read()
        except Exception as exc:
            raise ImageGenerationStorageError("图片文件不存在") from exc

    def signed_url(self, storage_key: str) -> str:
        """生成一天有效的 OSS 签名 URL，调用方负责先完成用户归属校验。

        创建日期：2026-06-06
        author: sunshengxian
        """

        if self.is_local:
            raise ImageGenerationStorageError("本地存储不支持 OSS 签名 URL")
        normalized_key = self._normalize_storage_key(storage_key)
        expires = max(self.settings.image_gen_oss_signed_url_expires_seconds, 1)
        return self._oss_bucket().sign_url("GET", normalized_key, expires)

    def local_file_path(self, storage_key: str) -> Path:
        """解析本地图片路径并阻止路径穿越。

        创建日期：2026-06-06
        author: sunshengxian
        """

        normalized_key = self._normalize_storage_key(storage_key)
        storage_root = self.settings.image_gen_storage_dir.resolve()
        path = storage_root.joinpath(normalized_key).resolve()
        if not path.is_relative_to(storage_root):
            raise ImageGenerationStorageError("图片文件不存在")
        return path

    def _oss_bucket(self):
        """延迟初始化 OSS Bucket，避免非图片功能启动时强依赖 OSS SDK 和凭据。

        创建日期：2026-06-06
        author: sunshengxian
        """

        if self._bucket is not None:
            return self._bucket
        if not self.settings.image_gen_oss_endpoint or not self.settings.image_gen_oss_bucket:
            raise ImageGenerationStorageError("请配置图片 OSS Endpoint 和 Bucket")
        access_key_id = self.settings.resolve_image_gen_oss_access_key_id()
        access_key_secret = self.settings.resolve_image_gen_oss_access_key_secret()
        security_token = self.settings.resolve_image_gen_oss_security_token()
        if not access_key_id or not access_key_secret:
            raise ImageGenerationStorageError("请配置图片 OSS AccessKey")
        try:
            import oss2
        except ImportError as exc:
            raise ImageGenerationStorageError("请安装阿里云 OSS Python SDK：oss2") from exc
        auth = (
            oss2.StsAuth(access_key_id, access_key_secret, security_token)
            if security_token
            else oss2.Auth(access_key_id, access_key_secret)
        )
        self._bucket = oss2.Bucket(
            auth,
            self.settings.image_gen_oss_endpoint,
            self.settings.image_gen_oss_bucket,
        )
        return self._bucket

    def _normalize_storage_key(self, value: str) -> str:
        """规范化对象键，拒绝绝对路径和上级目录，避免用户输入影响存储位置。

        创建日期：2026-06-06
        author: sunshengxian
        """

        normalized = str(PurePosixPath(value.strip().replace("\\", "/"))).strip("/")
        if not normalized or normalized == ".":
            return ""
        parts = PurePosixPath(normalized).parts
        if any(part in {"", ".", ".."} for part in parts):
            raise ImageGenerationStorageError("图片存储路径非法")
        return normalized
