from __future__ import annotations

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

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


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
    """确认成功生成图片会落盘并扣减一次额度。

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


def test_reference_generation_uses_reference_payload(tmp_path: Path) -> None:
    """确认参考图会先本地落盘，再传给供应商适配层。

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
    assert fake_client.reference_calls[0].mime_type == "image/png"


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


def test_rate_limit_response_retries_five_times(tmp_path: Path) -> None:
    """确认 gpt-image rate limit 会按约定最多重试 5 次。

    创建日期：2026-06-05
    author: sunshengxian
    """

    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            429,
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

    assert response.status_code == 429
    assert retry_count == IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS
    assert request_count == IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS + 1
