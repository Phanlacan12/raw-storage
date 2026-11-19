"""Test `_VersionIndex` sau B18.

Khẳng định X34: cache có TTL và `forget()` để entity bị xoá không ở lại cache.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from document_service.adapter.outbound.openmetadata.lineage import _VersionIndex
from document_service.domain.errors import DocumentNotFoundError
from document_service.domain.value import DocumentVersionId


class _StubClock:
    """Clock có thể dịch thời gian theo yêu cầu."""

    def __init__(self, start: datetime | None = None) -> None:
        """Khởi điểm giả, mặc định một thời điểm cố định."""
        self._now = start or datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        """Trả về thời điểm hiện tại giả."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Dời đồng hồ về phía trước `seconds` giây."""
        self._now = self._now + timedelta(seconds=seconds)


class _NoCallClient:
    """Client không được gọi: nếu `_refresh` kích hoạt, test đỏ."""

    async def get(self, *args, **kwargs):
        """Không được gọi."""
        raise AssertionError(f"_refresh should not fire for cached entry: {args} {kwargs}")


async def test_forget_removes_entry() -> None:
    """Sau `forget`, entry không còn trong cache."""
    index = _VersionIndex(  # type: ignore[arg-type]
        _NoCallClient(), ttl_seconds=60.0, clock=_StubClock()
    )
    index.remember("VER-1", "uuid-1", "svc.root.doc.VER-1")
    entity_id, fqn = await index.entity_of(DocumentVersionId("VER-1"))
    assert entity_id == "uuid-1"
    assert fqn.endswith("VER-1")
    index.forget("VER-1")
    # Client sẽ không được gọi nhưng vì entry đã bị quên, entity_of phải
    # kích hoạt refresh — ở đây refresh raise AssertionError, nên chúng ta
    # biến thành DocumentNotFoundError bằng clock và ttl bình thường:
    client = _NoCallClient()

    async def _empty_get(*_args, **_kwargs):
        return {"data": [], "paging": {}}

    client.get = _empty_get  # type: ignore[method-assign]
    index._client = client  # type: ignore[attr-defined]
    with pytest.raises(DocumentNotFoundError):
        await index.entity_of(DocumentVersionId("VER-1"))


async def test_ttl_expires_and_triggers_refresh() -> None:
    """Hết TTL thì cache coi như không có, trigger `_refresh`."""
    clock = _StubClock()
    client = _NoCallClient()
    refreshed = {"n": 0}

    async def _refresh(*_args, **_kwargs):
        refreshed["n"] += 1
        return {"data": [], "paging": {}}

    client.get = _refresh  # type: ignore[method-assign]
    index = _VersionIndex(client, ttl_seconds=1.0, clock=clock)  # type: ignore[arg-type]
    index.remember("VER-2", "uuid-2", "svc.root.doc.VER-2")
    # Trong TTL: không refresh.
    entity_id, _ = await index.entity_of(DocumentVersionId("VER-2"))
    assert entity_id == "uuid-2"
    assert refreshed["n"] == 0
    # Dời đồng hồ qua TTL: refresh phải chạy.
    clock.advance(10)
    with pytest.raises(DocumentNotFoundError):
        await index.entity_of(DocumentVersionId("VER-2"))
    assert refreshed["n"] == 1
