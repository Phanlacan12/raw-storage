"""Outbox bền vững và worker phát sự kiện (C10, D14).

Tách ba trách nhiệm để không trộn lẫn:

- `SqliteOutbox`: **nơi lưu** sự kiện, kèm số lần đã thử và lỗi cuối.
- `OutboxEventPublisher`: hiện thực `EventPublisherPort` — use case chỉ ghi vào outbox
  trong cùng database với intent, nên ghi nghiệp vụ và ghi sự kiện không lệch nhau.
- `WebhookEventSender` + `OutboxDispatcher`: **phát đi**, có retry qua
  `ResilientCallExecutor` và ngưỡng số lần thử.

Mọi bản ghi chưa `published` là việc còn nợ downstream — đó là cách phát hiện sự kiện
thất lạc mà mục 2.5 báo cáo và test case POC-11 yêu cầu.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

import httpx

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.config import EventSettings
from document_service.domain.model import DomainEvent
from document_service.domain.port import EventPublisherPort
from document_service.domain.value import DocumentId, DocumentVersionId
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.infrastructure.resilience.retry import ClassifiedError, ErrorClass
from document_service.utils.jsonx import JsonCodec
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    """Một bản ghi trong outbox."""

    event_id: int
    event: DomainEvent
    attempts: int
    last_error: str = ""

    def as_payload(self) -> dict[str, Any]:
        """Payload gửi cho downstream."""
        version_id = self.event.version_id
        return {
            "event_id": self.event_id,
            "event_type": self.event.event_type,
            "document_id": str(self.event.document_id),
            "document_version_id": str(version_id) if version_id is not None else None,
            "occurred_at": self.event.occurred_at.isoformat(),
            "payload": dict(self.event.payload),
        }


class SqliteOutbox:
    """Nơi lưu sự kiện chờ phát, dùng chung database với intent và audit."""

    def __init__(self, database: SqliteDatabase) -> None:
        """Nhận database sqlite."""
        self._db = database
        self._codec = JsonCodec()

    async def append(self, event: DomainEvent) -> None:
        """Ghi một sự kiện vào outbox."""
        version_id = event.version_id
        await self._db.execute(
            """
            INSERT INTO outbox_event (
                event_type, document_id, version_id, payload, occurred_at, published
            ) VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                event.event_type,
                str(event.document_id),
                str(version_id) if version_id is not None else "",
                self._codec.dumps(dict(event.payload)),
                event.occurred_at.isoformat(),
            ),
        )

    async def pending(self, limit: int) -> list[OutboxRecord]:
        """Danh sách sự kiện chưa phát, cũ nhất trước."""
        rows = await self._db.query(
            """
            SELECT event_id, event_type, document_id, version_id, payload,
                   occurred_at, attempts, last_error
            FROM outbox_event
            WHERE published = 0
            ORDER BY event_id
            LIMIT ?
            """,
            (limit,),
        )
        return [self._from_row(row) for row in rows]

    async def pending_count(self) -> int:
        """Số sự kiện chưa phát, dùng cho health và metric."""
        rows = await self._db.query(
            "SELECT COUNT(*) AS total FROM outbox_event WHERE published = 0"
        )
        return int(rows[0]["total"]) if rows else 0

    async def mark_published(self, event_id: int) -> None:
        """Đánh dấu một sự kiện đã phát thành công."""
        await self._db.execute(
            "UPDATE outbox_event SET published = 1 WHERE event_id = ?", (event_id,)
        )

    async def mark_attempt_failed(self, event_id: int, error: str) -> None:
        """Tăng số lần thử và ghi lỗi cuối."""
        await self._db.execute(
            """
            UPDATE outbox_event
            SET attempts = attempts + 1, last_error = ?
            WHERE event_id = ?
            """,
            (error[:500], event_id),
        )

    def _from_row(self, row: dict[str, Any]) -> OutboxRecord:
        """Dựng bản ghi outbox từ một dòng sqlite."""
        raw_version = str(row.get("version_id") or "")
        payload = {str(key): str(value) for key, value in self._codec.loads(row["payload"]).items()}
        event = DomainEvent(
            event_type=str(row["event_type"]),
            document_id=DocumentId(str(row["document_id"])),
            version_id=DocumentVersionId(raw_version) if raw_version else None,
            occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            payload=payload,
        )
        return OutboxRecord(
            event_id=int(row["event_id"]),
            event=event,
            attempts=int(row.get("attempts", 0) or 0),
            last_error=str(row.get("last_error", "")),
        )


class OutboxEventPublisher(EventPublisherPort, OutboundAdapter):
    """Ghi sự kiện vào outbox bền vững; việc phát đi do dispatcher lo."""

    def __init__(self, outbox: SqliteOutbox, executor: ResilientCallExecutor) -> None:
        """Nhận outbox và executor của phụ thuộc lưu trữ trạng thái."""
        OutboundAdapter.__init__(self, executor, DependencyKind.OPTIONAL)
        self._outbox = outbox

    @property
    def outbox(self) -> SqliteOutbox:
        """Outbox đang dùng, để dispatcher và health đọc."""
        return self._outbox

    async def publish(self, event: DomainEvent) -> None:
        """Ghi sự kiện vào outbox."""
        await self._call(lambda: self._outbox.append(event))

    async def _probe_dependency(self) -> HealthResult:
        """Đo độ sâu hàng đợi outbox."""
        pending = await self._outbox.pending_count()
        if pending > 0:
            return self.health_degraded(f"outbox still holds {pending} unpublished events")
        return self.health_up("outbox is empty")


class EventSender(ABC):
    """Base class của cơ chế gửi sự kiện tới downstream."""

    @abstractmethod
    async def send(self, record: OutboxRecord) -> None:
        """Gửi một sự kiện; phát lỗi nếu không thành công."""


class WebhookEventSender(EventSender):
    """Gửi sự kiện tới các endpoint webhook đã cấu hình."""

    def __init__(
        self,
        settings: EventSettings,
        executor: ResilientCallExecutor,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Nhận cấu hình, executor và client HTTP."""
        self._settings = settings
        self._executor = executor
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(executor.timeouts.read_seconds)
        )

    async def aclose(self) -> None:
        """Đóng client HTTP."""
        await self._client.aclose()

    async def send(self, record: OutboxRecord) -> None:
        """Gửi sự kiện tới mọi endpoint, lỗi ở một endpoint là lỗi của cả lượt."""
        for url in self._settings.webhook_urls:
            await self._executor.call(self._operation(url, record))

    def _operation(self, url: str, record: OutboxRecord) -> Callable[[], Awaitable[None]]:
        """Dựng coroutine gửi tới một endpoint, để executor bọc retry."""

        async def _run() -> None:
            await self._post(url, record)

        return _run

    async def _post(self, url: str, record: OutboxRecord) -> None:
        """POST một sự kiện, dịch lỗi HTTP sang nhóm có/không retry được."""
        try:
            response = await self._client.post(url, json=record.as_payload())
        except httpx.HTTPError as error:
            raise ClassifiedError(
                ErrorClass.RETRYABLE_TRANSIENT, f"webhook send failed: {error}"
            ) from error
        if response.status_code >= 500 or response.status_code == 429:
            raise ClassifiedError(
                ErrorClass.RETRYABLE_TRANSIENT,
                f"downstream returned {response.status_code}",
            )
        if response.status_code >= 400:
            raise ClassifiedError(
                ErrorClass.NON_RETRYABLE_CLIENT,
                f"downstream rejected with {response.status_code}",
            )


@dataclass(slots=True)
class DispatchReport:
    """Kết quả một lượt phát sự kiện."""

    sent: int = 0
    retried: int = 0
    given_up: int = 0
    pending: int = 0

    def as_payload(self) -> dict[str, object]:
        """Dạng dict để log."""
        return {
            "sent": self.sent,
            "retried": self.retried,
            "given_up": self.given_up,
            "pending": self.pending,
        }


class OutboxDispatcher:
    """Lấy sự kiện chưa phát và gửi đi, có ngưỡng số lần thử."""

    def __init__(self, outbox: SqliteOutbox, sender: EventSender, settings: EventSettings) -> None:
        """Nhận outbox, bộ gửi và cấu hình."""
        self._outbox = outbox
        self._sender = sender
        self._settings = settings

    @property
    def enabled(self) -> bool:
        """Có bật gửi sự kiện hay không."""
        return self._settings.enabled and bool(self._settings.webhook_urls)

    async def run_once(self) -> DispatchReport:
        """Phát một lượt; sự kiện vượt ngưỡng thử được ghi lỗi và bỏ lại."""
        report = DispatchReport()
        if not self.enabled:
            report.pending = await self._outbox.pending_count()
            return report
        for record in await self._outbox.pending(self._settings.batch_size):
            if record.attempts >= self._settings.max_attempts:
                report.given_up += 1
                _LOGGER.error(
                    "event exceeded the attempt limit, manual intervention needed",
                    extra={"event_id": record.event_id, "error": record.last_error},
                )
                continue
            await self._dispatch(record, report)
        report.pending = await self._outbox.pending_count()
        _LOGGER.info("event dispatch finished", extra=report.as_payload())
        return report

    async def _dispatch(self, record: OutboxRecord, report: DispatchReport) -> None:
        """Gửi một sự kiện và cập nhật trạng thái tương ứng."""
        try:
            await self._sender.send(record)
        except Exception as error:  # phụ thuộc ngoài: đã được sender phân loại
            await self._outbox.mark_attempt_failed(record.event_id, str(error))
            report.retried += 1
            _LOGGER.warning(
                "event send failed, will retry",
                extra={"event_id": record.event_id, "error": str(error)},
            )
            return
        await self._outbox.mark_published(record.event_id)
        report.sent += 1
