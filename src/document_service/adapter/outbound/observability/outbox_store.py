"""Nơi lưu sự kiện chờ phát (D14, D20).

`SqliteOutbox` là **nơi lưu** sự kiện, kèm số lần đã thử và lỗi cuối. Nó dùng chung
database với intent và audit, nên ghi nghiệp vụ và ghi sự kiện không lệch nhau.

Mọi bản ghi chưa `published` là việc còn nợ downstream — đó là cách phát hiện sự kiện
thất lạc mà mục 2.5 báo cáo và test case POC-11 yêu cầu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.domain.model import DomainEvent
from document_service.domain.value import DocumentId, DocumentVersionId
from document_service.utils.jsonx import JsonCodec


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
                event_type, document_id, version_id, payload, occurred_at, published, delivery_id
            ) VALUES (?, ?, ?, ?, ?, 0, ?) ON CONFLICT(delivery_id) DO NOTHING
            """,
            (
                event.event_type,
                str(event.document_id),
                str(version_id) if version_id is not None else "",
                self._codec.dumps(dict(event.payload)),
                event.occurred_at.isoformat(),
                event.delivery_id,
            ),
        )

    async def pending(self, limit: int, max_attempts: int = 2**31) -> list[OutboxRecord]:
        """Danh sách sự kiện chưa phát, cũ nhất trước."""
        rows = await self._db.query(
            """
            SELECT event_id, event_type, document_id, version_id, payload,
                   occurred_at, delivery_id, attempts, last_error
            FROM outbox_event
            WHERE published = 0
            ORDER BY attempts >= ?, event_id
            LIMIT ?
            """,
            (max_attempts, limit),
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
            delivery_id=row["delivery_id"],
        )
        return OutboxRecord(
            event_id=int(row["event_id"]),
            event=event,
            attempts=int(row.get("attempts", 0) or 0),
            last_error=str(row.get("last_error", "")),
        )
