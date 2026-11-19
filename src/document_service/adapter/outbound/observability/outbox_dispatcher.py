"""Phát sự kiện từ outbox tới downstream (C10, D26).

`WebhookEventSender` + `OutboxDispatcher` là phần **phát đi**, có retry qua
`ResilientCallExecutor` và ngưỡng số lần thử: vượt ngưỡng thì cảnh báo thay vì thử lại
vô hạn, theo mục 2.5 báo cáo và test case POC-11.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from document_service.adapter.outbound.observability.outbox_store import OutboxRecord, SqliteOutbox
from document_service.config import EventSettings
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.infrastructure.resilience.retry import ClassifiedError, ErrorClass
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)


class EventSender(ABC):
    """Base class của cơ chế gửi sự kiện tới downstream."""

    async def aclose(self) -> None:
        """Đóng tài nguyên của sender nếu có."""

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

    async def aclose(self) -> None:
        """Đóng sender sau lượt cuối cùng."""
        await self._sender.aclose()

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
        records = await self._outbox.pending(self._settings.batch_size, self._settings.max_attempts)
        for record in records:
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
