"""OmHttpClient và các lớp phụ trợ: auth bot, pin phiên bản, dịch lỗi.

Theo mục 4 và 12 của docs/c4-04b-code-structure.md. Mọi lời gọi HTTP đi qua
`ResilientCallExecutor` của phụ thuộc `catalog`, và mọi lỗi HTTP được dịch sang
`ClassifiedError` để executor quyết định có retry hay không (mục 11.2).
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from document_service.adapter.outbound.openmetadata import endpoints
from document_service.config import CatalogSettings
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.infrastructure.resilience.retry import ClassifiedError, ErrorClass
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)


class OmAuthProvider:
    """Cấp header Authorization từ bot token, làm mới có khóa chống đồng thời."""

    def __init__(self, token: str) -> None:
        """Nhận bot token lấy từ biến môi trường."""
        self._token = token
        self._lock = asyncio.Lock()
        self._refresh_count = 0

    @property
    def refresh_count(self) -> int:
        """Số lần đã làm mới token, dùng cho test và metric."""
        return self._refresh_count

    def authorization_header(self) -> dict[str, str]:
        """Header Authorization, rỗng nếu chưa cấu hình token."""
        if not self._token:
            return {}
        return {"Authorization": f"Bearer {self._token}"}

    async def refresh(self) -> bool:
        """Làm mới token đúng một lần cho mỗi lượt 401."""
        async with self._lock:
            self._refresh_count += 1
            return bool(self._token)


class OmApiVersionPin:
    """Giữ phiên bản OpenMetadata đã cố định và phát hiện lệch bản."""

    def __init__(self, pinned_version: str) -> None:
        """Nhận phiên bản được cố định, rỗng nghĩa là chưa chốt."""
        self._pinned = pinned_version

    @property
    def pinned_version(self) -> str:
        """Phiên bản đã cố định."""
        return self._pinned

    def matches(self, server_version: str) -> bool:
        """Phiên bản server có khớp bản đã cố định hay không."""
        if not self._pinned:
            return True
        return server_version.startswith(self._pinned)


class OmErrorTranslator:
    """Phân loại lỗi HTTP thành năm nhóm ở mục 11.2."""

    def classify(self, status_code: int) -> ErrorClass:
        """Nhóm lỗi tương ứng một mã HTTP."""
        if status_code == 401:
            return ErrorClass.AUTH_REFRESHABLE
        if status_code == 409:
            return ErrorClass.NON_RETRYABLE_CONFLICT
        if status_code == 429:
            return ErrorClass.RETRYABLE_THROTTLED
        if status_code in (502, 503, 504):
            return ErrorClass.RETRYABLE_TRANSIENT
        if 400 <= status_code < 500:
            return ErrorClass.NON_RETRYABLE_CLIENT
        return ErrorClass.RETRYABLE_TRANSIENT

    def translate(self, response: httpx.Response) -> ClassifiedError:
        """Dựng ClassifiedError từ một response lỗi."""
        error_class = self.classify(response.status_code)
        retry_after = self._retry_after(response)
        return ClassifiedError(
            error_class,
            f"OpenMetadata trả {response.status_code}: {response.text[:200]}",
            retry_after,
        )

    def translate_transport(self, error: httpx.HTTPError) -> ClassifiedError:
        """Lỗi tầng vận chuyển luôn là lỗi tạm thời."""
        return ClassifiedError(ErrorClass.RETRYABLE_TRANSIENT, f"lỗi kết nối: {error}")

    def _retry_after(self, response: httpx.Response) -> float | None:
        """Đọc header Retry-After nếu server có gửi."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None


class OmHttpClient:
    """Client HTTP tới OpenMetadata, cố định phiên bản và bọc resilience."""

    def __init__(self, settings: CatalogSettings, executor: ResilientCallExecutor) -> None:
        """Nhận cấu hình catalog và executor của phụ thuộc catalog."""
        self._settings = settings
        self._executor = executor
        self._auth = OmAuthProvider(settings.bot_token)
        self._pin = OmApiVersionPin(settings.pinned_version)
        self._errors = OmErrorTranslator()
        timeouts = executor.timeouts
        self._client = httpx.AsyncClient(
            base_url=settings.base_url.rstrip("/"),
            timeout=httpx.Timeout(
                timeouts.read_seconds, connect=timeouts.connect_seconds
            ),
        )

    @property
    def pin(self) -> OmApiVersionPin:
        """Bộ pin phiên bản, health check dùng để báo lệch bản."""
        return self._pin

    @property
    def executor(self) -> ResilientCallExecutor:
        """Executor của phụ thuộc catalog."""
        return self._executor

    async def aclose(self) -> None:
        """Đóng connection pool khi service dừng."""
        await self._client.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET một tài nguyên."""
        return await self._request("GET", path, params=params)

    async def put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """PUT một entity, idempotent theo FQN."""
        return await self._request("PUT", path, json_body=payload)

    async def patch(self, path: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        """PATCH theo JSON Patch, chỉ dùng phép `replace` trên đường dẫn cố định."""
        return await self._request(
            "PATCH",
            path,
            json_body=operations,
            content_type=endpoints.JSON_PATCH_CONTENT_TYPE,
        )

    async def delete(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """DELETE một entity."""
        return await self._request("DELETE", path, params=params)

    async def server_version(self) -> str:
        """Phiên bản server, dùng cho health check và kiểm tra pin."""
        payload = await self.get(endpoints.SYSTEM_VERSION)
        return str(payload.get("version", ""))

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Gửi một request qua executor, có xử lý 401 làm mới token một lần."""

        async def _send() -> dict[str, Any]:
            headers = dict(self._auth.authorization_header())
            if content_type:
                headers["Content-Type"] = content_type
            try:
                response = await self._client.request(
                    method, path, params=params, json=json_body, headers=headers
                )
            except httpx.HTTPError as error:
                raise self._errors.translate_transport(error) from error
            if response.status_code == 401:
                await self._auth.refresh()
                raise self._errors.translate(response)
            if response.status_code >= 400:
                raise self._errors.translate(response)
            return self._as_dict(response)

        return await self._executor.call(_send)

    def _as_dict(self, response: httpx.Response) -> dict[str, Any]:
        """Đọc body JSON, chấp nhận body rỗng cho DELETE."""
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError:
            _LOGGER.warning("body không phải JSON", extra={"status": response.status_code})
            return {}
        if isinstance(payload, dict):
            return payload
        return {"data": payload}
