"""Hiện thực `EventPublisherPort` bằng outbox bền vững (D14).

Use case chỉ ghi vào outbox trong cùng database với intent, nên ghi nghiệp vụ và ghi
sự kiện không lệch nhau; việc phát đi do `OutboxDispatcher` lo.
"""

from __future__ import annotations

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.observability.outbox_store import SqliteOutbox
from document_service.domain.model import DomainEvent
from document_service.domain.port import EventPublisherPort
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor


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
