"""Bộ test hợp đồng của EventPublisherPort và worker phát sự kiện (plan B9).

Khẳng định theo mục 14 và test case POC-11: sự kiện **không mất** khi downstream lỗi,
mọi bản ghi chưa phát đều đếm được (nên phát hiện được sự kiện thất lạc), và vượt
ngưỡng thử thì cảnh báo thay vì thử lại vô hạn.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from document_service.adapter.outbound.fake.in_memory import InMemoryEventPublisher
from document_service.adapter.outbound.observability.outbox_dispatcher import (
    OutboxDispatcher,
    WebhookEventSender,
)
from document_service.adapter.outbound.observability.outbox_publisher import OutboxEventPublisher
from document_service.adapter.outbound.observability.outbox_store import SqliteOutbox
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.config import DependencyResiliencePolicy, EventSettings
from document_service.domain.model import DomainEvent
from document_service.domain.port import EventPublisherPort
from document_service.domain.value import DocumentId, DocumentVersionId
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.worker.dispatch import OutboxDispatchRunner

WEBHOOK = "http://downstream.test/events"
DOCUMENT_ID = DocumentId("DOC-EVENT-0001")
VERSION_ID = DocumentVersionId("VER-EVENT-0001")


def _event(event_type: str = "version.created") -> DomainEvent:
    """Sự kiện mẫu."""
    return DomainEvent(
        event_type=event_type,
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        payload={"version_label": "1.0"},
    )


@pytest.fixture
def outbox(tmp_path: Path) -> SqliteOutbox:
    """Outbox trên sqlite riêng cho mỗi test."""
    return SqliteOutbox(SqliteDatabase(str(tmp_path / "events.sqlite")))


@pytest.fixture
def executor() -> ResilientCallExecutor:
    """Executor nhanh cho test."""
    return ResilientCallExecutor(
        "events",
        DependencyResiliencePolicy(
            max_attempts=1, base_delay_seconds=0.01, total_timeout_seconds=2.0
        ),
    )


@pytest.fixture(params=["in_memory", "outbox_sqlite"])
def publisher(
    request: pytest.FixtureRequest, outbox: SqliteOutbox, executor: ResilientCallExecutor
) -> EventPublisherPort:
    """Hai hiện thực của EventPublisherPort."""
    if request.param == "in_memory":
        return InMemoryEventPublisher()
    return OutboxEventPublisher(outbox, executor)


async def _published_types(publisher: EventPublisherPort) -> list[str]:
    """Danh sách loại sự kiện đã ghi, đọc theo từng hiện thực."""
    if isinstance(publisher, InMemoryEventPublisher):
        return [event.event_type for event in publisher.events]
    records = await publisher.outbox.pending(100)
    return [record.event.event_type for record in records]


class TestEventPublisherContract:
    """Hợp đồng chung: ghi sự kiện bền vững, giữ thứ tự, không mất."""

    async def test_publish_records_event(self, publisher: EventPublisherPort) -> None:
        """Sự kiện được ghi lại."""
        await publisher.publish(_event())
        assert await _published_types(publisher) == ["version.created"]

    async def test_order_is_preserved(self, publisher: EventPublisherPort) -> None:
        """Thứ tự sự kiện của cùng một tài liệu được giữ."""
        for event_type in ("version.created", "version.approved", "access.changed"):
            await publisher.publish(_event(event_type))
        assert await _published_types(publisher) == [
            "version.created",
            "version.approved",
            "access.changed",
        ]

    async def test_event_keeps_identifiers(self, publisher: EventPublisherPort) -> None:
        """Sự kiện mang `document_id` và `document_version_id` cho downstream."""
        await publisher.publish(_event())
        if isinstance(publisher, InMemoryEventPublisher):
            stored = publisher.events[0]
        else:
            stored = (await publisher.outbox.pending(1))[0].event
        assert stored.document_id == DOCUMENT_ID
        assert stored.version_id == VERSION_ID
        assert stored.payload["version_label"] == "1.0"


class TestOutboxDispatcher:
    """Phát sự kiện tới downstream, có retry và ngưỡng thử."""

    @pytest.fixture
    def settings(self) -> EventSettings:
        """Cấu hình bật gửi sự kiện tới một webhook."""
        return EventSettings(enabled=True, webhook_urls=[WEBHOOK], batch_size=10, max_attempts=3)

    @pytest.fixture
    def sender(
        self, settings: EventSettings, executor: ResilientCallExecutor
    ) -> Iterator[WebhookEventSender]:
        """Bộ gửi webhook dùng client HTTP của respx."""
        yield WebhookEventSender(settings, executor, httpx.AsyncClient(timeout=2.0))

    @respx.mock
    async def test_sends_pending_events(
        self, outbox: SqliteOutbox, sender: WebhookEventSender, settings: EventSettings
    ) -> None:
        """Sự kiện được gửi và đánh dấu đã phát."""
        route = respx.post(WEBHOOK).mock(return_value=httpx.Response(200))
        await outbox.append(_event())
        report = await OutboxDispatcher(outbox, sender, settings).run_once()
        assert report.sent == 1
        assert report.pending == 0
        assert route.called
        body = respx.calls.last.request.read().decode()
        assert "version.created" in body
        assert str(VERSION_ID) in body

    @respx.mock
    async def test_failure_keeps_event_pending(
        self, outbox: SqliteOutbox, sender: WebhookEventSender, settings: EventSettings
    ) -> None:
        """POC-11: downstream lỗi thì sự kiện vẫn còn trong outbox."""
        respx.post(WEBHOOK).mock(return_value=httpx.Response(503))
        await outbox.append(_event())
        report = await OutboxDispatcher(outbox, sender, settings).run_once()
        assert report.sent == 0
        assert report.retried == 1
        assert report.pending == 1
        record = (await outbox.pending(1))[0]
        assert record.attempts == 1
        assert "503" in record.last_error

    @respx.mock
    async def test_retry_then_success(
        self, outbox: SqliteOutbox, sender: WebhookEventSender, settings: EventSettings
    ) -> None:
        """Lượt sau downstream khỏe thì sự kiện được phát, không mất."""
        respx.post(WEBHOOK).mock(return_value=httpx.Response(503))
        await outbox.append(_event())
        dispatcher = OutboxDispatcher(outbox, sender, settings)
        await dispatcher.run_once()
        respx.post(WEBHOOK).mock(return_value=httpx.Response(202))
        report = await dispatcher.run_once()
        assert report.sent == 1
        assert await outbox.pending_count() == 0

    @respx.mock
    async def test_gives_up_after_max_attempts(
        self, outbox: SqliteOutbox, sender: WebhookEventSender, settings: EventSettings
    ) -> None:
        """Vượt ngưỡng thử thì bỏ lại và cảnh báo, không thử vô hạn."""
        respx.post(WEBHOOK).mock(return_value=httpx.Response(500))
        await outbox.append(_event())
        dispatcher = OutboxDispatcher(outbox, sender, settings)
        for _ in range(settings.max_attempts):
            await dispatcher.run_once()
        report = await dispatcher.run_once()
        assert report.given_up == 1
        assert report.sent == 0
        assert await outbox.pending_count() == 1

    @respx.mock
    async def test_client_rejection_is_not_retried_forever(
        self, outbox: SqliteOutbox, sender: WebhookEventSender, settings: EventSettings
    ) -> None:
        """Downstream trả 400 là lỗi phía payload: ghi lỗi, không coi là tạm thời."""
        respx.post(WEBHOOK).mock(return_value=httpx.Response(400))
        await outbox.append(_event())
        report = await OutboxDispatcher(outbox, sender, settings).run_once()
        assert report.retried == 1
        record = (await outbox.pending(1))[0]
        assert "400" in record.last_error

    async def test_disabled_dispatcher_only_counts(
        self, outbox: SqliteOutbox, sender: WebhookEventSender
    ) -> None:
        """Chưa bật gửi thì chỉ đếm hàng đợi, không gọi downstream."""
        disabled = EventSettings(enabled=False, webhook_urls=[WEBHOOK])
        await outbox.append(_event())
        report = await OutboxDispatcher(outbox, sender, disabled).run_once()
        assert report.sent == 0
        assert report.pending == 1

    async def test_publisher_health_reflects_backlog(
        self, outbox: SqliteOutbox, executor: ResilientCallExecutor
    ) -> None:
        """Hàng đợi outbox còn sự kiện thì health báo DEGRADED."""
        publisher = OutboxEventPublisher(outbox, executor)
        assert (await publisher.check_health()).status.value == "UP"
        await publisher.publish(_event())
        publisher.invalidate_health_cache()
        assert (await publisher.check_health()).status.value == "DEGRADED"


async def test_worker_dispatches_and_closes_sender(
    outbox: SqliteOutbox, executor: ResilientCallExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker gọi dispatcher thật và đóng HTTP client khi hủy vòng lặp."""
    settings = EventSettings(enabled=True, webhook_urls=[WEBHOOK], batch_size=1)
    await outbox.append(_event())
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(204))
    ) as client:
        sender = WebhookEventSender(settings, executor, client)
        dispatcher = OutboxDispatcher(outbox, sender, settings)
        runner = OutboxDispatchRunner(dispatcher, 10)
        monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError))
        with pytest.raises(asyncio.CancelledError):
            await runner.run_forever()
        assert client.is_closed
    assert await outbox.pending_count() == 0
