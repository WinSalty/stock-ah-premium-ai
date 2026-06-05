from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings

IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS = 10
IMAGE_GENERATION_RATE_LIMIT_RETRY_SECONDS = 0.2


class ImageGenerationClientError(RuntimeError):
    """图片生成供应商调用错误。

    创建日期：2026-05-27
    author: sunshengxian
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_count = 0


class ImageGenerationUnsupportedError(ImageGenerationClientError):
    """供应商暂不支持参考图能力。

    创建日期：2026-05-27
    author: sunshengxian
    """


@dataclass(frozen=True)
class ReferenceImagePayload:
    """供应商调用用参考图载荷。

    创建日期：2026-05-27
    author: sunshengxian
    """

    filename: str
    content: bytes
    mime_type: str


@dataclass(frozen=True)
class ImageGenerationProviderResult:
    """供应商图片生成结果。

    创建日期：2026-05-27
    author: sunshengxian
    """

    image_bytes: bytes | None
    image_url: str | None
    mime_type: str
    response_summary: dict[str, Any]


class ImageGenerationClient:
    """86GameStore OpenAI 兼容图片生成客户端。

    创建日期：2026-05-27
    author: sunshengxian
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate(self, prompt: str, size: str, model: str) -> ImageGenerationProviderResult:
        """调用纯文生图接口。

        创建日期：2026-05-27
        author: sunshengxian
        """

        api_key = self._api_key()
        payload = {"model": model, "prompt": prompt, "size": size, "n": 1}
        with httpx.Client(timeout=self.settings.image_gen_timeout_seconds) as client:
            response, retry_count = self._post_with_rate_limit_retry(
                client,
                f"{self.settings.image_gen_base_url.rstrip('/')}/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        result = self._parse_response(response, retry_count)
        result.response_summary["retry_count"] = retry_count
        return result

    def generate_with_reference(
        self,
        prompt: str,
        size: str,
        model: str,
        reference_image: ReferenceImagePayload,
    ) -> ImageGenerationProviderResult:
        """调用 OpenAI 兼容图片编辑接口，使用用户上传图片作为参考。

        创建日期：2026-05-27
        author: sunshengxian
        """

        api_key = self._api_key()
        with httpx.Client(timeout=self.settings.image_gen_timeout_seconds) as client:
            response, retry_count = self._post_with_rate_limit_retry(
                client,
                f"{self.settings.image_gen_base_url.rstrip('/')}/v1/images/edits",
                headers={"Authorization": f"Bearer {api_key}"},
                data={"model": model, "prompt": prompt, "size": size, "n": "1"},
                files={
                    "image": (
                        reference_image.filename,
                        reference_image.content,
                        reference_image.mime_type,
                    )
                },
            )
        if response.status_code in {404, 405}:
            raise ImageGenerationUnsupportedError(
                "当前文生图供应商暂未开放参考图 API",
                response.status_code,
            )
        result = self._parse_response(response, retry_count)
        result.response_summary["retry_count"] = retry_count
        return result

    def _post_with_rate_limit_retry(
        self,
        client: httpx.Client,
        url: str,
        **kwargs: Any,
    ) -> tuple[httpx.Response, int]:
        """对图片输入频率限制做短重试，避免毫秒级限流直接打断用户任务。

        创建日期：2026-06-05
        author: sunshengxian
        """

        retry_count = 0
        for attempt in range(IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS + 1):
            response = client.post(url, **kwargs)
            if not self._is_rate_limit_response(response):
                return response, retry_count
            if attempt >= IMAGE_GENERATION_RATE_LIMIT_RETRY_ATTEMPTS:
                return response, retry_count
            retry_count += 1
            time.sleep(self._rate_limit_retry_seconds(response))
        return response, retry_count

    def _is_rate_limit_response(self, response: httpx.Response) -> bool:
        """识别供应商返回的图片输入频率限制错误。

        创建日期：2026-06-05
        author: sunshengxian
        """

        message = self._error_message(response).lower()
        return "rate limit reached" in message and "input-images per min" in message

    def _rate_limit_retry_seconds(self, response: httpx.Response) -> float:
        """按响应头读取重试间隔，缺省使用保守短等待。

        创建日期：2026-06-05
        author: sunshengxian
        """

        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(float(retry_after), IMAGE_GENERATION_RATE_LIMIT_RETRY_SECONDS)
            except ValueError:
                return IMAGE_GENERATION_RATE_LIMIT_RETRY_SECONDS
        return IMAGE_GENERATION_RATE_LIMIT_RETRY_SECONDS

    def _api_key(self) -> str:
        """读取供应商 API Key，避免上层误把空密钥发给外部服务。

        创建日期：2026-05-27
        author: sunshengxian
        """

        api_key = self.settings.resolve_image_gen_api_key()
        if not api_key:
            raise ImageGenerationClientError("文生图服务密钥未配置")
        return api_key

    def _parse_response(
        self,
        response: httpx.Response,
        retry_count: int = 0,
    ) -> ImageGenerationProviderResult:
        """解析 OpenAI Images 兼容返回。

        创建日期：2026-05-27
        author: sunshengxian
        """

        if not response.is_success:
            error = ImageGenerationClientError(self._error_message(response), response.status_code)
            error.retry_count = retry_count
            raise error
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise ImageGenerationClientError("文生图服务未返回图片数据", response.status_code)
        first_item = data[0]
        if not isinstance(first_item, dict):
            raise ImageGenerationClientError("文生图服务返回格式异常", response.status_code)
        response_summary = {
            "created": payload.get("created"),
            "data_count": len(data),
            "result_type": "url" if first_item.get("url") else "b64_json",
        }
        if first_item.get("b64_json"):
            encoded_image = str(first_item["b64_json"])
            if "," in encoded_image and encoded_image.startswith("data:"):
                encoded_image = encoded_image.split(",", maxsplit=1)[1]
            return ImageGenerationProviderResult(
                image_bytes=base64.b64decode(encoded_image),
                image_url=None,
                mime_type="image/png",
                response_summary=response_summary,
            )
        if first_item.get("url"):
            return ImageGenerationProviderResult(
                image_bytes=None,
                image_url=str(first_item["url"]),
                mime_type="image/png",
                response_summary=response_summary,
            )
        raise ImageGenerationClientError(
            "文生图服务未返回可识别的图片 URL 或 Base64 数据",
            response.status_code,
        )

    def _error_message(self, response: httpx.Response) -> str:
        """提取供应商错误摘要，避免记录完整响应里的敏感细节。

        创建日期：2026-05-27
        author: sunshengxian
        """

        try:
            payload = response.json()
        except ValueError:
            return f"文生图服务请求失败，状态码 {response.status_code}"
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:512]
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])[:512]
        return f"文生图服务请求失败，状态码 {response.status_code}"
