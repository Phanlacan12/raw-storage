"""Bộ test hợp đồng của IntentStorePort (chốt quyết định Q2).

Khẳng định chính, theo mục 14: tra theo idempotency key đúng khi gọi song song, trạng
thái không mất sau khi ghi lại, và `find_unfinished` trả đủ intent dở dang — đó là
điều kiện cần cho POC-18, POC-21 và POC-22.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

from document_service.domain.errors import ConcurrencyConflictError
from document_service.domain.model import ProcessingIntent
from document_service.domain.port import IntentStorePort
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentVersionId,
    IdempotencyKey,
    IntentKind,
    IntentState,
    RequestId,
)
from document_service.utils.clock import utc_now

CHECKSUM = Checksum.parse("sha256:" + "a" * 64)


def _intent(suffix: str, key: str = "") -> ProcessingIntent:
    """Dựng intent mẫu."""
    return ProcessingIntent(
        request_id=RequestId(f"REQ-{suffix}"),
        idempotency_key=IdempotencyKey(key or f"idem-key-{suffix}"),
        document_id=DocumentId("DOC-1"),
        version_id=DocumentVersionId(f"VER-{suffix}"),
        expected_checksum=CHECKSUM,
        payload={"version_id": f"VER-{suffix}"},
    )


class TestIntentStoreContract:
    """Hợp đồng chung cho mọi hiện thực intent store."""

    async def test_create_then_find_by_key(self, intent_store: IntentStorePort) -> None:
        """Ghi rồi tra lại được theo idempotency key."""
        intent = _intent("0001")
        await intent_store.create(intent)
        found = await intent_store.find_by_idempotency_key(intent.idempotency_key)
        assert found is not None
        assert found.version_id == intent.version_id
        assert found.payload["version_id"] == "VER-0001"

    async def test_find_unfinished_by_kind(self, intent_store: IntentStorePort) -> None:
        """Giữ loại và checksum qua lượt đọc lại, lọc đúng các thao tác phục hồi."""
        upload = _intent("upload")
        status = _intent("status")
        status.kind = IntentKind.STATUS_CHANGE
        status.expected_checksum = None
        command = replace(
            _intent("command"), kind=IntentKind.COMMAND, version_id=None, expected_checksum=None
        )
        for item in (upload, status, command):
            await intent_store.create(item)
        window = timedelta(seconds=-1)
        for item in (upload, status, command):
            found = await intent_store.find_unfinished(window, item.kind)
            assert [result.request_id for result in found] == [item.request_id]
            assert found[0].version_id == item.version_id
            assert found[0].kind is item.kind
            assert found[0].expected_checksum == item.expected_checksum
        assert len(await intent_store.find_unfinished(window)) == 3

    async def test_advance_persists_state(self, intent_store: IntentStorePort) -> None:
        """Chuyển trạng thái được ghi lại bền vững."""
        intent = _intent("0002")
        await intent_store.create(intent)
        await intent_store.advance(intent.request_id, IntentState.OBJECT_STORED)
        found = await intent_store.find_by_request_id(intent.request_id)
        assert found is not None
        assert found.state is IntentState.OBJECT_STORED

    async def test_retry_count_survives_save(self, intent_store: IntentStorePort) -> None:
        """Ghi lại intent giữ nguyên retry_count và lỗi cuối."""
        intent = _intent("0003")
        await intent_store.create(intent)
        intent.register_retry("catalog 503")
        await intent_store.save(intent)
        found = await intent_store.find_by_request_id(intent.request_id)
        assert found is not None
        assert found.retry_count == 1
        assert found.state is IntentState.RETRY_PENDING
        assert "503" in found.last_error

    async def test_find_unfinished_excludes_terminal(self, intent_store: IntentStorePort) -> None:
        """Intent đã Completed không còn nằm trong hàng đợi phục hồi."""
        pending = _intent("0004")
        done = _intent("0005")
        await intent_store.create(pending)
        await intent_store.create(done)
        await intent_store.advance(done.request_id, IntentState.COMPLETED)
        unfinished = await intent_store.find_unfinished(timedelta(seconds=-1))
        ids = {str(item.request_id) for item in unfinished}
        assert str(pending.request_id) in ids
        assert str(done.request_id) not in ids

    async def test_find_unfinished_respects_stale_window(
        self, intent_store: IntentStorePort
    ) -> None:
        """Intent vừa cập nhật chưa bị coi là dở dang."""
        intent = _intent("0006")
        await intent_store.create(intent)
        unfinished = await intent_store.find_unfinished(timedelta(seconds=300))
        assert unfinished == []

    async def test_concurrent_same_key_rejected_or_single(
        self, intent_store: IntentStorePort
    ) -> None:
        """Hai request đồng thời cùng idempotency key không tạo hai intent (I13)."""
        shared_key = "idem-shared-key"
        first = _intent("0007", shared_key)
        second = _intent("0008", shared_key)
        results = await asyncio.gather(
            intent_store.create(first),
            intent_store.create(second),
            return_exceptions=True,
        )
        failures = [item for item in results if isinstance(item, Exception)]
        found = await intent_store.find_by_idempotency_key(IdempotencyKey(shared_key))
        assert found is not None
        assert len(failures) == 1 and isinstance(failures[0], ConcurrencyConflictError)
        winner = second if isinstance(results[0], Exception) else first
        assert found.request_id == winner.request_id
        unfinished = await intent_store.find_unfinished(timedelta(seconds=-1))
        assert [item.request_id for item in unfinished] == [winner.request_id]

    async def test_updated_at_moves_forward(self, intent_store: IntentStorePort) -> None:
        """Mỗi lần ghi lại cập nhật thời điểm, phục vụ ngưỡng stale."""
        intent = _intent("0009")
        await intent_store.create(intent)
        before = utc_now()
        await intent_store.save(intent)
        found = await intent_store.find_by_request_id(intent.request_id)
        assert found is not None
        assert found.updated_at >= before - timedelta(seconds=1)
