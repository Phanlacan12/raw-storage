"""StructuredAuditLogger và OutboxEventPublisher (D14, D16).

Phân vai rõ với `utils/logging_setup.py`: lớp ở đây quyết định **nội dung audit
nghiệp vụ** (ai tải file, ai chuyển trạng thái, ai đổi quyền — bất biến I12), còn
*cách hiển thị* log là việc của utils. Audit vừa được ghi vào log để hệ thống log tập
trung thu được, vừa lưu xuống sqlite để trả lời được test case POC-14.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.domain.model import AuditEvent, DomainEvent
from document_service.domain.port import AuditPort, EventPublisherPort
from document_service.domain.value import Actor, DocumentId
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.utils.jsonx import JsonCodec
from document_service.utils.logging_setup import get_logger

_AUDIT_LOGGER = get_logger("document_service.audit")


class StructuredAuditLogger(AuditPort, OutboundAdapter):
    """Ghi audit vào log có cấu trúc và lưu bền vững xuống sqlite."""

    def __init__(self, database: SqliteDatabase, executor: ResilientCallExecutor) -> None:
        """Nhận database và executor của phụ thuộc intent/registry."""
        OutboundAdapter.__init__(self, executor, DependencyKind.OPTIONAL)
        self._db = database

    async def record(self, event: AuditEvent) -> None:
        """Ghi một bản ghi audit."""
        _AUDIT_LOGGER.info(
            "audit",
            extra={
                "actor": event.actor.principal_id,
                "action": event.action,
                "target_id": event.target_id,
                "result": event.result,
                "detail": event.detail,
            },
        )
        await self._call(
            lambda: self._db.execute(
                """
                INSERT INTO audit_event (
                    actor, action, target_id, document_id, result, detail, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.actor.principal_id,
                    event.action,
                    event.target_id,
                    event.document_id,
                    event.result,
                    event.detail,
                    event.occurred_at.isoformat(),
                ),
            )
        )

    async def list_for_document(self, document_id: DocumentId) -> list[AuditEvent]:
        """Audit của một tài liệu và các phiên bản của nó (POC-14)."""
        rows = await self._call(
            lambda: self._db.query(
                """
                SELECT actor, action, target_id, document_id, result, detail, occurred_at
                FROM audit_event
                WHERE document_id = ? OR target_id LIKE ?
                ORDER BY event_id
                """,
                (str(document_id), f"%{document_id}%"),
            )
        )
        return [self._from_row(row) for row in rows]

    async def _probe_dependency(self) -> HealthResult:
        """Đếm số bản ghi audit, thao tác chỉ đọc."""
        rows = await self._db.query("SELECT COUNT(*) AS total FROM audit_event")
        total = rows[0]["total"] if rows else 0
        return self.health_up(f"audit rows={total}")

    def _from_row(self, row: dict[str, Any]) -> AuditEvent:
        """Dựng lại bản ghi audit từ sqlite."""
        return AuditEvent(
            actor=Actor(principal_id=row["actor"]),
            action=row["action"],
            target_id=row["target_id"],
            document_id=row.get("document_id", ""),
            result=row["result"],
            detail=row["detail"],
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
        )


class OutboxEventPublisher(EventPublisherPort, OutboundAdapter):
    """Ghi sự kiện vào outbox bền vững rồi để worker phát đi.

    Ghi outbox trong cùng database với intent giúp phát hiện sự kiện thất lạc: mọi
    bản ghi chưa `published` đều là việc còn nợ downstream (test case POC-11).
    """

    def __init__(self, database: SqliteDatabase, executor: ResilientCallExecutor) -> None:
        """Nhận database và executor."""
        OutboundAdapter.__init__(self, executor, DependencyKind.OPTIONAL)
        self._db = database
        self._codec = JsonCodec()

    async def publish(self, event: DomainEvent) -> None:
        """Ghi sự kiện vào outbox."""
        await self._call(
            lambda: self._db.execute(
                """
                INSERT INTO outbox_event (
                    event_type, document_id, version_id, payload, occurred_at, published
                ) VALUES (?, ?, ?, ?, ?, 0)
                """,
                (
                    event.event_type,
                    str(event.document_id),
                    str(event.version_id) if event.version_id is not None else "",
                    self._codec.dumps(dict(event.payload)),
                    event.occurred_at.isoformat(),
                ),
            )
        )

    async def pending_count(self) -> int:
        """Số sự kiện chưa phát, dùng cho health và metric."""
        rows = await self._db.query(
            "SELECT COUNT(*) AS total FROM outbox_event WHERE published = 0"
        )
        return int(rows[0]["total"]) if rows else 0

    async def mark_published(self, event_ids: list[int]) -> None:
        """Đánh dấu các sự kiện đã phát thành công."""
        for event_id in event_ids:
            await self._db.execute(
                "UPDATE outbox_event SET published = 1 WHERE event_id = ?", (event_id,)
            )

    async def _probe_dependency(self) -> HealthResult:
        """Đo độ sâu hàng đợi outbox."""
        pending = await self.pending_count()
        if pending > 0:
            return self.health_degraded(f"outbox còn {pending} sự kiện chưa phát")
        return self.health_up("outbox trống")
