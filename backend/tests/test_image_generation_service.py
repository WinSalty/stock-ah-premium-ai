from __future__ import annotations

import base64
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models.auth import AppUser
from app.db.models.image_generation import AiImageGeneration, AiImageGenerationErrorLog
from app.services.image_generation_client import (
    IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS,
    IMAGE_GENERATION_TRANSIENT_RETRY_ATTEMPTS,
    ImageGenerationClient,
    ImageGenerationClientError,
    ImageGenerationProviderResult,
    ImageGenerationUnsupportedError,
    ReferenceImagePayload,
)
from app.services.image_generation_service import (
    ImageGenerationError,
    ImageGenerationService,
    UploadedReferenceImage,
)
from app.services.image_generation_storage_service import ImageGenerationStorageError

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP4z8AAAAMBAQDJ/"
    "pLvAAAAAElFTkSuQmCC"
)


class FakeImageClient:
    """图片生成测试用供应商客户端。

    创建日期：2026-05-27
    author: sunshengxian
    """

    def __init__(self, fail: bool = False, reference_supported: bool = True) -> None:
        self.fail = fail
        self.reference_supported = reference_supported
        self.reference_calls: list[ReferenceImagePayload] = []

    def generate(self, prompt: str, size: str, model: str) -> ImageGenerationProviderResult:
        if self.fail:
            raise ImageGenerationClientError("供应商失败")
        return ImageGenerationProviderResult(
            image_bytes=PNG_BYTES,
            image_url=None,
            mime_type="image/png",
            response_summary={"result_type": "b64_json"},
        )

    def generate_with_reference(
        self,
        prompt: str,
        size: str,
        model: str,
        reference_image: ReferenceImagePayload,
    ) -> ImageGenerationProviderResult:
        if not self.reference_supported:
            raise ImageGenerationUnsupportedError("当前文生图供应商暂未开放参考图 API")
        self.reference_calls.append(reference_image)
        return self.generate(prompt, size, model)


class FakeSignedUrlStorage:
    """图片生成测试用 OSS 签名 URL 存储。

    创建日期：2026-06-06
    author: sunshengxian
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.mime_types: dict[str, str] = {}
        self.signed_keys: list[str] = []

    @property
    def is_local(self) -> bool:
        return False

    def build_storage_key(self, relative_path: str) -> str:
        return f"stock-ah-premium-ai/generated-images/{relative_path}"

    def save_bytes(self, storage_key: str, content: bytes, mime_type: str) -> None:
        self.objects[storage_key] = content
        self.mime_types[storage_key] = mime_type

    def read_bytes(self, storage_key: str) -> bytes:
        if storage_key not in self.objects:
            raise ImageGenerationStorageError("图片文件不存在")
        return self.objects[storage_key]

    def signed_url(self, storage_key: str) -> str:
        self.signed_keys.append(storage_key)
        return f"https://bucket.oss-cn-hangzhou.aliyuncs.com/{storage_key}?Expires=86400"

    def local_file_path(self, storage_key: str) -> Path:
        raise ImageGenerationStorageError("OSS 存储不支持本地路径")


def make_db() -> Session:
    """创建图片生成测试数据库。

    创建日期：2026-05-27
    author: sunshengxian
    """

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def add_user(db: Session, username: str, role: str = "USER") -> AppUser:
    """写入测试用户。

    创建日期：2026-05-27
    author: sunshengxian
    """

    user = AppUser(username=username, password_hash="hash", role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_settings(tmp_path: Path) -> Settings:
    """创建图片生成测试配置，使用临时目录模拟数据盘。

    创建日期：2026-05-27
    author: sunshengxian
    """

    return Settings(
        image_gen_storage_backend="local",
        image_gen_storage_dir=tmp_path,
        image_gen_api_key="unit-test-key",
        image_gen_api_key_file=None,
        tushare_token_file=None,
        llm_api_key_file=None,
        qwen_api_key_file=None,
        pushplus_token_file=None,
        pushplus_secret_key_file=None,
    )


def test_image_generation_saves_file_and_consumes_quota(tmp_path: Path) -> None:
    """确认 local 兜底模式成功生成图片会保存文件并扣减一次额度。

    创建日期：2026-05-27
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "image-user")
    service = ImageGenerationService(db, make_settings(tmp_path), FakeImageClient())

    response = service.create_generation(user, "A green finance dashboard", "1024x1024")
    assert response.status == "GENERATING"

    service.process_generation(response.id)
    response = service.record_response(
        service.get_generation(user, response.id),
        user,
        service.get_user_quota(user.id),
    )

    assert response.status == "READY"
    assert response.image_url == f"/api/image-generation/generations/{response.id}/file"
    assert response.quota is not None
    assert response.quota.used_count == 1
    assert response.quota.remaining_count == 9
    stored_record = db.get(AiImageGeneration, response.id)
    assert stored_record is not None
    assert stored_record.file_relative_path is not None
    assert tmp_path.joinpath(stored_record.file_relative_path).exists()


def test_image_generation_returns_signed_oss_url(tmp_path: Path) -> None:
    """确认 OSS 模式生成完成后向前端返回一天有效的签名 URL。

    创建日期：2026-06-06
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "oss-url-user")
    storage = FakeSignedUrlStorage()
    service = ImageGenerationService(
        db,
        make_settings(tmp_path),
        FakeImageClient(),
        storage=storage,
    )

    response = service.create_generation(user, "A signed OSS image", "1024x1024")
    service.process_generation(response.id)
    response = service.record_response(service.get_generation(user, response.id), user)

    assert response.status == "READY"
    assert response.image_url is not None
    assert response.image_url.startswith("https://bucket.oss-cn-hangzhou.aliyuncs.com/")
    assert "Expires=86400" in response.image_url
    stored_record = db.get(AiImageGeneration, response.id)
    assert stored_record is not None
    assert stored_record.file_relative_path in storage.objects


def test_failed_generation_refunds_quota(tmp_path: Path) -> None:
    """确认供应商失败会保留失败记录并返还本次次数。

    创建日期：2026-05-27
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "refund-user")
    service = ImageGenerationService(db, make_settings(tmp_path), FakeImageClient(fail=True))

    response = service.create_generation(user, "A red error illustration", "1024x1024")
    assert response.status == "GENERATING"

    service.process_generation(response.id)
    response = service.record_response(
        service.get_generation(user, response.id),
        user,
        service.get_user_quota(user.id),
    )

    assert response.status == "FAILED"
    assert response.quota is not None
    assert response.quota.used_count == 0
    assert response.quota.remaining_count == 10
    assert "供应商失败" not in (response.error_message or "")
    assert "图片生成失败" in (response.error_message or "")
    logs = db.query(AiImageGenerationErrorLog).filter_by(generation_id=response.id).all()
    assert logs
    assert "供应商失败" in logs[0].detail_message


def test_retry_failed_generation_creates_new_task(tmp_path: Path) -> None:
    """确认失败图片可一键重试并创建新的后台生成任务。

    创建日期：2026-06-05
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "retry-user")
    failing_service = ImageGenerationService(
        db,
        make_settings(tmp_path),
        FakeImageClient(fail=True),
    )
    failed_response = failing_service.create_generation(
        user,
        "A retryable image",
        "1024x1024",
    )
    failing_service.process_generation(failed_response.id)

    retry_service = ImageGenerationService(db, make_settings(tmp_path), FakeImageClient())
    retry_response = retry_service.retry_generation(user, failed_response.id)

    assert retry_response.id != failed_response.id
    assert retry_response.status == "GENERATING"
    assert retry_response.prompt == "A retryable image"
    assert retry_response.size == "1024x1024"
    assert retry_response.quota is not None
    assert retry_response.quota.used_count == 1


def test_reference_generation_uses_reference_payload(tmp_path: Path) -> None:
    """确认参考图会压缩为 JPEG 后保存，再传给供应商适配层。

    创建日期：2026-05-27
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "reference-user")
    fake_client = FakeImageClient()
    service = ImageGenerationService(db, make_settings(tmp_path), fake_client)

    response = service.create_generation(
        user,
        "Use the reference composition",
        "1024x1024",
        UploadedReferenceImage("ref.png", PNG_BYTES, "image/png"),
    )
    assert response.status == "GENERATING"

    service.process_generation(response.id)
    response = service.record_response(service.get_generation(user, response.id), user)

    assert response.status == "READY"
    assert response.generation_mode == "IMAGE_REFERENCE"
    assert response.reference_image_url == (
        f"/api/image-generation/generations/{response.id}/reference-file"
    )
    assert fake_client.reference_calls
    assert fake_client.reference_calls[0].mime_type == "image/jpeg"
    assert fake_client.reference_calls[0].filename.endswith(".jpg")
    stored_record = db.get(AiImageGeneration, response.id)
    assert stored_record is not None
    assert stored_record.reference_mime_type == "image/jpeg"
    assert stored_record.reference_file_size_bytes is not None
    assert stored_record.reference_file_size_bytes > 0


def test_same_user_duplicate_reference_reuses_storage_object(tmp_path: Path) -> None:
    """确认同一用户重复上传相同参考图时只保存一份存储对象。

    创建日期：2026-06-06
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "duplicate-reference-user")
    storage = FakeSignedUrlStorage()
    service = ImageGenerationService(
        db,
        make_settings(tmp_path),
        FakeImageClient(),
        storage=storage,
    )

    first_response = service.create_generation(
        user,
        "First use of the same reference",
        "1024x1024",
        UploadedReferenceImage("same.png", PNG_BYTES, "image/png"),
    )
    second_response = service.create_generation(
        user,
        "Second use of the same reference",
        "1024x1024",
        UploadedReferenceImage("same-again.png", PNG_BYTES, "image/png"),
    )
    first_record = db.get(AiImageGeneration, first_response.id)
    second_record = db.get(AiImageGeneration, second_response.id)

    assert first_record is not None
    assert second_record is not None
    assert first_record.reference_file_relative_path is not None
    assert first_record.reference_file_relative_path == second_record.reference_file_relative_path
    assert len(storage.objects) == 1


def test_oversized_reference_returns_user_message(tmp_path: Path) -> None:
    """确认参考图过大时直接返回中文校验提示并返还次数。

    创建日期：2026-06-05
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "oversized-reference-user")
    service = ImageGenerationService(db, make_settings(tmp_path), FakeImageClient())

    response = service.create_generation(
        user,
        "Use an oversized reference",
        "1024x1024",
        UploadedReferenceImage(
            "huge.png",
            PNG_BYTES + (b"0" * (10 * 1024 * 1024)),
            "image/png",
        ),
    )

    assert response.status == "FAILED"
    assert response.error_message == "参考图不能超过 10MB"
    assert response.quota is not None
    assert response.quota.used_count == 0
    logs = db.query(AiImageGenerationErrorLog).filter_by(generation_id=response.id).all()
    assert logs
    assert logs[0].user_message == "参考图不能超过 10MB"
    assert logs[0].detail_message == "参考图不能超过 10MB"


def test_unsupported_reference_refunds_quota(tmp_path: Path) -> None:
    """确认供应商不支持参考图时失败可读且返还次数。

    创建日期：2026-05-27
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "unsupported-reference-user")
    service = ImageGenerationService(
        db,
        make_settings(tmp_path),
        FakeImageClient(reference_supported=False),
    )

    response = service.create_generation(
        user,
        "Use the reference composition",
        "1024x1024",
        UploadedReferenceImage("ref.png", PNG_BYTES, "image/png"),
    )
    assert response.status == "GENERATING"

    service.process_generation(response.id)
    response = service.record_response(
        service.get_generation(user, response.id),
        user,
        service.get_user_quota(user.id),
    )

    assert response.status == "FAILED"
    assert response.quota is not None
    assert response.quota.used_count == 0
    assert "参考图生成" in (response.error_message or "")


def test_regular_user_cannot_read_other_user_image(tmp_path: Path) -> None:
    """确认普通用户不能读取他人图片记录。

    创建日期：2026-05-27
    author: sunshengxian
    """

    db = make_db()
    owner = add_user(db, "owner")
    other = add_user(db, "other")
    admin = add_user(db, "admin", "ADMIN")
    service = ImageGenerationService(db, make_settings(tmp_path), FakeImageClient())
    response = service.create_generation(owner, "A private image", "1024x1024")

    try:
        service.get_generation(other, response.id)
    except ImageGenerationError as exc:
        assert "没有访问" in str(exc)
    else:
        raise AssertionError("普通用户不应读取他人图片")

    assert service.get_generation(admin, response.id).id == response.id


def test_delete_generation_hides_record_and_keeps_permission_boundary(tmp_path: Path) -> None:
    """确认图片逻辑删除后不再出现在历史列表，且他人不能删除。

    创建日期：2026-06-06
    author: sunshengxian
    """

    db = make_db()
    owner = add_user(db, "delete-owner")
    other = add_user(db, "delete-other")
    service = ImageGenerationService(db, make_settings(tmp_path), FakeImageClient())
    response = service.create_generation(owner, "A deletable image", "1024x1024")

    try:
        service.delete_generation(other, response.id)
    except ImageGenerationError as exc:
        assert "没有访问" in str(exc)
    else:
        raise AssertionError("普通用户不应删除他人图片")

    service.delete_generation(owner, response.id)
    record = db.get(AiImageGeneration, response.id)
    assert record is not None
    assert record.deleted_at is not None
    assert service.list_generations(owner).total == 0
    try:
        service.get_generation(owner, response.id)
    except ImageGenerationError as exc:
        assert "不存在" in str(exc)
    else:
        raise AssertionError("已删除图片不应继续被读取")


def test_list_generations_supports_multiple_statuses(tmp_path: Path) -> None:
    """确认历史图库可一次查询已完成和生成中两类记录。

    创建日期：2026-06-05
    author: sunshengxian
    """

    db = make_db()
    user = add_user(db, "status-user")
    service = ImageGenerationService(db, make_settings(tmp_path), FakeImageClient())
    ready_response = service.create_generation(user, "A ready image", "1024x1024")
    service.process_generation(ready_response.id)
    generating_response = service.create_generation(user, "A pending image", "1024x1024")

    response = service.list_generations(
        user,
        status="READY,GENERATING",
    )

    returned_ids = {item.id for item in response.items}
    assert ready_response.id in returned_ids
    assert generating_response.id in returned_ids


def test_rate_limit_response_retries_configured_attempts(tmp_path: Path, monkeypatch) -> None:
    """确认 input-images per min 限流会按配置次数重试。

    创建日期：2026-06-05
    author: sunshengxian
    """

    request_count = 0
    monkeypatch.setattr("app.services.image_generation_client.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            502,
            json={
                "error": {
                    "message": (
                        "Rate limit reached for gpt-image-2-codex "
                        "(for limit gpt-image) on input-images per min"
                    )
                }
            },
            request=request,
        )

    client = ImageGenerationClient(make_settings(tmp_path))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        response, retry_count = client._post_with_rate_limit_retry(
            http_client,
            "https://example.test/v1/images/generations",
            json={},
        )

    assert response.status_code == 502
    assert retry_count == IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS
    assert request_count == IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS + 1


def test_transient_image_error_retries_five_times(tmp_path: Path, monkeypatch) -> None:
    """确认非读超时的临时供应商错误会在原有限流重试之外额外重试五次。

    创建日期：2026-06-09
    author: sunshengxian
    """

    request_count = 0
    monkeypatch.setattr("app.services.image_generation_client.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            502,
            json={"error": {"message": "temporary upstream failure"}},
            request=request,
        )

    client = ImageGenerationClient(make_settings(tmp_path))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        response, retry_count = client._post_with_rate_limit_retry(
            http_client,
            "https://example.test/v1/images/generations",
            json={},
        )

    assert response.status_code == 502
    assert retry_count == IMAGE_GENERATION_TRANSIENT_RETRY_ATTEMPTS
    assert request_count == IMAGE_GENERATION_TRANSIENT_RETRY_ATTEMPTS + 1


def test_read_timeout_does_not_retry(tmp_path: Path, monkeypatch) -> None:
    """确认图片读超时不做重复请求，避免长耗时任务在供应商侧重复执行。

    创建日期：2026-06-09
    author: sunshengxian
    """

    request_count = 0
    monkeypatch.setattr("app.services.image_generation_client.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        raise httpx.ReadTimeout("read timeout", request=request)

    client = ImageGenerationClient(make_settings(tmp_path))
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        try:
            client._post_with_rate_limit_retry(
                http_client,
                "https://example.test/v1/images/generations",
                json={},
            )
        except httpx.ReadTimeout:
            pass
        else:
            raise AssertionError("读超时不应被吞掉或重试")

    assert request_count == 1
