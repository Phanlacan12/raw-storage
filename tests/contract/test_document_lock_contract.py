"""Bộ test hợp đồng của DocumentLockPort (chốt quyết định Q12 — C13).

Năm case đầu chạy trên **cả hai** hiện thực (`in_memory` và `redis`); ba case
`TestRedisDocumentLockSpecific` chỉ chạy khi có Redis thật (biến `DS_LOCK__REDIS_URL`).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from document_service.adapter.outbound.lock.redis_lock import RedisDocumentLock
from document_service.config import DependencyResiliencePolicy, LockKind, LockSettings
from document_service.domain.errors import ConcurrencyConflictError
from document_service.domain.port import DocumentLockPort
from document_service.domain.value import DocumentId
from document_service.infrastructure.resilience.executor import ResilientCallExecutor

REDIS_URL = os.environ.get("DS_LOCK__REDIS_URL", "")


class TestDocumentLockContract:
    """Hợp đồng chung của mọi DocumentLockPort."""

    async def test_with_lock_returns_operation_result(
        self, document_lock: DocumentLockPort
    ) -> None:
        """`with_lock` trả đúng kết quả của operation."""

        async def op() -> int:
            return 42

        assert await document_lock.with_lock(DocumentId("DOC-LOCK-1"), op) == 42

    async def test_concurrent_calls_same_id_serialize(
        self, document_lock: DocumentLockPort
    ) -> None:
        """Hai `with_lock` đồng thời cùng document_id ghi theo thứ tự tuần tự."""
        log: list[str] = []

        async def op(label: str, delay: float) -> None:
            log.append(f"start:{label}")
            await asyncio.sleep(delay)
            log.append(f"end:{label}")

        doc = DocumentId("DOC-LOCK-SER")
        await asyncio.gather(
            document_lock.with_lock(doc, lambda: op("A", 0.05)),
            document_lock.with_lock(doc, lambda: op("B", 0.0)),
        )
        # Một bên phải xong trước khi bên kia bắt đầu.
        assert log[0].startswith("start:")
        assert log[1].startswith("end:")
        assert log[2].startswith("start:")
        assert log[3].startswith("end:")
        assert log[0][-1] == log[1][-1]
        assert log[2][-1] == log[3][-1]

    async def test_different_ids_do_not_block(self, document_lock: DocumentLockPort) -> None:
        """Hai document_id khác nhau không chặn nhau."""
        order: list[str] = []

        async def slow() -> None:
            await asyncio.sleep(0.05)
            order.append("slow")

        async def fast() -> None:
            order.append("fast")

        await asyncio.gather(
            document_lock.with_lock(DocumentId("DOC-X"), slow),
            document_lock.with_lock(DocumentId("DOC-Y"), fast),
        )
        assert order == ["fast", "slow"]

    async def test_lock_released_after_operation_error(
        self, document_lock: DocumentLockPort
    ) -> None:
        """Operation ném lỗi vẫn nhả khóa; lần acquire sau cùng id thành công ngay."""

        async def boom() -> None:
            raise RuntimeError("boom")

        doc = DocumentId("DOC-LOCK-ERR")
        with pytest.raises(RuntimeError):
            await document_lock.with_lock(doc, boom)

        # Nhanh gọn không phải chờ timeout.
        async def ok() -> int:
            return 1

        assert await document_lock.with_lock(doc, ok) == 1

    async def test_acquire_timeout_raises_conflict(self, document_lock: DocumentLockPort) -> None:
        """Khóa đang bị giữ + `acquire_timeout_seconds` ngắn → `ConcurrencyConflictError`."""
        doc = DocumentId("DOC-LOCK-BUSY")
        holder_release = asyncio.Event()
        holder_entered = asyncio.Event()

        async def hold() -> None:
            holder_entered.set()
            await holder_release.wait()

        holder = asyncio.create_task(document_lock.with_lock(doc, hold))
        await holder_entered.wait()
        try:

            async def op() -> None:
                return None

            with pytest.raises(ConcurrencyConflictError):
                await document_lock.with_lock(doc, op)
        finally:
            holder_release.set()
            await holder


@pytest.mark.skipif(REDIS_URL == "", reason="thiếu DS_LOCK__REDIS_URL")
class TestRedisDocumentLockSpecific:
    """Kiểm bất biến chỉ có nghĩa trên Redis thật."""

    @pytest.fixture
    async def lock_and_client(self):  # type: ignore[no-untyped-def]
        """Tạo cặp (lock, client) riêng để test kiểm trực tiếp vào Redis."""
        from uuid import uuid4

        import redis.asyncio as redis_async

        client = redis_async.from_url(REDIS_URL, socket_timeout=0.5)
        prefix = f"ds:test:{uuid4().hex}"
        settings = LockSettings(
            kind=LockKind.REDIS,
            redis_url=REDIS_URL,
            key_prefix=prefix,
            acquire_timeout_seconds=0.1,
            lease_seconds=1.0,
            renew_interval_seconds=0.3,
        )
        executor = ResilientCallExecutor(
            "document_lock",
            DependencyResiliencePolicy(
                connect_timeout_seconds=0.3,
                read_timeout_seconds=1.0,
                total_timeout_seconds=1.0,
                max_attempts=1,
            ),
        )
        lock = RedisDocumentLock(settings, executor, client=client)
        yield lock, client, prefix
        await lock.aclose()

    async def test_key_has_ttl_and_cleared(  # type: ignore[no-untyped-def]
        self, lock_and_client
    ) -> None:
        """Khi đang trong `with_lock`, key có TTL > 0; thoát xong thì biến mất."""
        lock, client, prefix = lock_and_client
        doc_id = DocumentId("DOC-LOCK-TTL")
        key = f"{prefix}:doc:{doc_id}"
        seen: dict[str, int] = {}

        async def op() -> None:
            seen["pttl"] = int(await client.pttl(key))

        await lock.with_lock(doc_id, op)
        assert seen["pttl"] > 0
        assert int(await client.exists(key)) == 0

    async def test_expired_lease_is_auto_recoverable(  # type: ignore[no-untyped-def]
        self, lock_and_client
    ) -> None:
        """Lease hết hạn mà không gia hạn thì khóa tự mở; acquire mới thành công."""
        lock, client, prefix = lock_and_client
        doc_id = DocumentId("DOC-LOCK-EXP")
        key = f"{prefix}:doc:{doc_id}"
        # Ghi khóa thủ công với TTL ngắn, mô phỏng người giữ đã chết
        await client.set(key, "ghost", px=100)
        await asyncio.sleep(0.25)

        async def op() -> int:
            return 7

        assert await lock.with_lock(doc_id, op) == 7

    async def test_release_does_not_delete_foreign_token(  # type: ignore[no-untyped-def]
        self, lock_and_client
    ) -> None:
        """CAS-release token lạ không xoá khóa của người giữ mới."""
        lock, client, prefix = lock_and_client
        doc_id = DocumentId("DOC-LOCK-CAS")
        key = f"{prefix}:doc:{doc_id}"
        await client.set(key, "wrong_token", ex=10)
        # pylint: disable=protected-access
        await lock._release_key(key, "my_token")
        assert await client.get(key) == b"wrong_token"
        await client.delete(key)
