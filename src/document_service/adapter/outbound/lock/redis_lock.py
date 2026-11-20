"""Khóa phân tán theo Redis — C13 (quyết định Q12, c4-09 mục 12).

`SET key token NX PX lease_ms` lấy khóa; token sinh bằng `UlidGenerator` để hai
nhánh gia hạn và nhả khóa chỉ tác động lên khóa **của mình** (CAS bằng Lua):

- CAS-extend: `if GET==token then PEXPIRE else 0` — mất lease trả 0.
- CAS-release: `if GET==token then DEL else 0` — không xoá khóa người giữ mới.

Mất lease giữa đường mà `cancel_on_lease_loss=True` thì hủy operation và ném
`ConcurrencyConflictError`. An toàn vì lượt duyệt dở dang để lại intent
`StatusChangePending` cho `IntentRecoveryJob` phục hồi (lý do B9 phải xong trước B17).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, TypeVar
from urllib.parse import urlsplit, urlunsplit

import redis.asyncio as redis_async

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.config import LockSettings
from document_service.domain.errors import ConcurrencyConflictError
from document_service.domain.port import DocumentLockPort
from document_service.domain.value import DocumentId
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.utils.ids import UlidGenerator

T = TypeVar("T")

_EXTEND_SCRIPT = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] "
    "then return redis.call('PEXPIRE', KEYS[1], ARGV[2]) else return 0 end"
)
_RELEASE_SCRIPT = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] "
    "then return redis.call('DEL', KEYS[1]) else return 0 end"
)


def _sanitized_url(url: str) -> str:
    """Trả URL không chứa password, dùng cho log và payload health."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    user = parts.username or ""
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    netloc = f"{user}:***@{host}" if user else f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class RedisDocumentLock(DocumentLockPort, OutboundAdapter):
    """Khóa phân tán cho mỗi document_id, lease có gia hạn tự động."""

    def __init__(
        self,
        settings: LockSettings,
        executor: ResilientCallExecutor,
        client: "redis_async.Redis | None" = None,
    ) -> None:
        """Nhận cấu hình khóa, executor `document_lock` và client tuỳ chọn.

        `client=None` thì dựng từ `settings.redis_url` với timeout khớp executor.
        """
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_WRITE)
        self._settings = settings
        if client is None:
            client = redis_async.from_url(
                settings.redis_url,
                socket_connect_timeout=executor.timeouts.connect_seconds,
                socket_timeout=executor.timeouts.read_seconds,
            )
        self._client = client
        self._ids = UlidGenerator()
        self._extend = self._client.register_script(_EXTEND_SCRIPT)
        self._release = self._client.register_script(_RELEASE_SCRIPT)

    def _key(self, document_id: DocumentId) -> str:
        """Khóa Redis của một tài liệu."""
        return f"{self._settings.key_prefix}:doc:{document_id}"

    async def with_lock(self, document_id: DocumentId, operation: Callable[[], Awaitable[T]]) -> T:
        """Lấy khóa, chạy operation, gia hạn song song, nhả khóa an toàn."""
        key = self._key(document_id)
        token = self._ids.new_id(prefix="LCK")
        lease_ms = int(self._settings.lease_seconds * 1000)
        await self._acquire(key, token, lease_ms)
        lease_lost = asyncio.Event()
        renew_task = asyncio.create_task(self._renew_loop(key, token, lease_ms, lease_lost))

        async def _run() -> T:
            return await operation()

        op_task: asyncio.Task[T] = asyncio.create_task(_run())
        try:
            done, _ = await asyncio.wait(
                {op_task, asyncio.create_task(lease_lost.wait())},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if op_task in done:
                return op_task.result()
            if self._settings.cancel_on_lease_loss:
                op_task.cancel()
                try:
                    await op_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
                raise ConcurrencyConflictError(f"document {document_id} lock lease lost")
            return await op_task
        finally:
            renew_task.cancel()
            try:
                await renew_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            await self._release_key(key, token)

    async def _acquire(self, key: str, token: str, lease_ms: int) -> None:
        """Chờ có jitter tới `acquire_timeout_seconds` để lấy khóa, hết hạn thì 409."""
        deadline = asyncio.get_event_loop().time() + self._settings.acquire_timeout_seconds
        delay = self._settings.acquire_retry_delay_seconds
        while True:
            acquired = await self._call(lambda: self._client.set(key, token, nx=True, px=lease_ms))
            if acquired:
                return
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise ConcurrencyConflictError(f"timed out waiting for lock on key {key}")
            jitter = random.uniform(0, delay)
            await asyncio.sleep(min(delay + jitter, max(remaining, 0.0)))

    async def _renew_loop(
        self, key: str, token: str, lease_ms: int, lease_lost: asyncio.Event
    ) -> None:
        """Gia hạn lease mỗi `renew_interval_seconds`; trả 0 → set `lease_lost`."""
        interval = self._settings.renew_interval_seconds
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return
            try:
                result = await self._call(lambda: self._extend(keys=[key], args=[token, lease_ms]))
            except Exception:  # noqa: BLE001 - mọi lỗi coi như mất lease
                lease_lost.set()
                return
            if int(result or 0) == 0:
                lease_lost.set()
                return

    async def _release_key(self, key: str, token: str) -> None:
        """Nhả khóa bằng Lua CAS; lỗi thì log, không che lỗi của operation."""
        try:
            await self._call(lambda: self._release(keys=[key], args=[token]))
        except Exception as error:  # noqa: BLE001 - lease đã hết thì mặc nhiên nhả
            self._logger.warning(
                "failed to release lock",
                extra={"key": key, "detail": str(error)},
            )

    async def _probe_dependency(self) -> HealthResult:
        """`PING`, không bọc `_call` (c4-09 mục 12): breaker đã được `check_health` đọc."""
        pong: Any = await self._client.ping()
        detail = _sanitized_url(self._settings.redis_url)
        if pong is True or pong == b"PONG" or pong == "PONG":
            return self.health_up(detail)
        return self.health_down(f"unexpected PING response from {detail}")

    async def aclose(self) -> None:
        """Đóng client Redis."""
        await self._client.aclose()
