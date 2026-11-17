"""SqliteRegistryIntentStore — biến thể B của quyết định Q2.

Intent được ghi **trước** khi ghi object (mục 3.5 báo cáo). Bảng có UNIQUE trên
`idempotency_key`, nên hai request đồng thời cùng khóa không thể tạo hai intent —
đây là ràng buộc cần cho bất biến I13 và test case POC-22.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.domain.errors import ConcurrencyConflictError
from document_service.domain.model import UploadIntent
from document_service.domain.port import IntentStorePort
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentVersionId,
    IdempotencyKey,
    IntentState,
    RequestId,
)
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.utils.clock import utc_now
from document_service.utils.jsonx import JsonCodec

_INSERT = """
INSERT INTO upload_intent (
    request_id, idempotency_key, document_id, version_id, expected_checksum,
    state, retry_count, created_at, updated_at, last_error, payload
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""
_SELECT = """
SELECT request_id, idempotency_key, document_id, version_id, expected_checksum,
       state, retry_count, created_at, updated_at, last_error, payload
FROM upload_intent
"""


class SqliteRegistryIntentStore(IntentStorePort, OutboundAdapter):
    """Intent store trên sqlite, có health check riêng của phụ thuộc."""

    def __init__(self, database: SqliteDatabase, executor: ResilientCallExecutor) -> None:
        """Nhận database và executor của phụ thuộc intent."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_WRITE)
        self._db = database
        self._codec = JsonCodec()

    async def create(self, intent: UploadIntent) -> None:
        """Ghi intent mới, báo xung đột nếu idempotency key đã tồn tại."""
        try:
            await self._call(lambda: self._db.execute(_INSERT, self._as_row(intent)))
        except sqlite3.IntegrityError as error:
            raise ConcurrencyConflictError(
                f"idempotency_key {intent.idempotency_key} đã được dùng"
            ) from error

    async def advance(self, request_id: RequestId, state: IntentState) -> None:
        """Cập nhật trạng thái intent."""
        await self._call(
            lambda: self._db.execute(
                "UPDATE upload_intent SET state = ?, updated_at = ? WHERE request_id = ?",
                (str(state), utc_now().isoformat(), str(request_id)),
            )
        )

    async def save(self, intent: UploadIntent) -> None:
        """Ghi lại toàn bộ intent, dùng khi tăng retry_count hoặc ghi lỗi."""
        intent.updated_at = utc_now()
        await self._call(
            lambda: self._db.execute(
                """
                UPDATE upload_intent
                SET state = ?, retry_count = ?, updated_at = ?, last_error = ?, payload = ?
                WHERE request_id = ?
                """,
                (
                    str(intent.state),
                    intent.retry_count,
                    intent.updated_at.isoformat(),
                    intent.last_error,
                    self._codec.dumps(dict(intent.payload)),
                    str(intent.request_id),
                ),
            )
        )

    async def find_by_idempotency_key(self, key: IdempotencyKey) -> UploadIntent | None:
        """Tra intent theo idempotency key."""
        rows = await self._call(
            lambda: self._db.query(f"{_SELECT} WHERE idempotency_key = ?", (str(key),))
        )
        return self._from_row(rows[0]) if rows else None

    async def find_by_request_id(self, request_id: RequestId) -> UploadIntent | None:
        """Tra intent theo request id."""
        rows = await self._call(
            lambda: self._db.query(f"{_SELECT} WHERE request_id = ?", (str(request_id),))
        )
        return self._from_row(rows[0]) if rows else None

    async def find_unfinished(self, stale_after: timedelta) -> list[UploadIntent]:
        """Intent chưa kết thúc và đã đủ cũ, đầu vào cho job phục hồi."""
        threshold = (utc_now() - stale_after).isoformat()
        rows = await self._call(
            lambda: self._db.query(
                f"{_SELECT} WHERE state NOT IN (?, ?) AND updated_at <= ? ORDER BY updated_at",
                (str(IntentState.COMPLETED), str(IntentState.FAILED), threshold),
            )
        )
        return [self._from_row(row) for row in rows]

    async def _probe_dependency(self) -> HealthResult:
        """Đọc một dòng đếm, là thao tác chỉ đọc và rẻ."""
        rows = await self._db.query("SELECT COUNT(*) AS total FROM upload_intent")
        total = rows[0]["total"] if rows else 0
        return self.health_up(f"sqlite ok, intents={total}")

    def _as_row(self, intent: UploadIntent) -> tuple[Any, ...]:
        """Chuyển intent sang tuple tham số cho câu INSERT."""
        return (
            str(intent.request_id),
            str(intent.idempotency_key),
            str(intent.document_id),
            str(intent.version_id),
            str(intent.expected_checksum),
            str(intent.state),
            intent.retry_count,
            intent.created_at.isoformat(),
            intent.updated_at.isoformat(),
            intent.last_error,
            self._codec.dumps(dict(intent.payload)),
        )

    def _from_row(self, row: dict[str, Any]) -> UploadIntent:
        """Dựng lại intent từ một dòng sqlite."""
        payload = {str(key): str(value) for key, value in self._codec.loads(row["payload"]).items()}
        return UploadIntent(
            request_id=RequestId(row["request_id"]),
            idempotency_key=IdempotencyKey(row["idempotency_key"]),
            document_id=DocumentId(row["document_id"]),
            version_id=DocumentVersionId(row["version_id"]),
            expected_checksum=Checksum.parse(row["expected_checksum"]),
            state=IntentState(row["state"]),
            retry_count=int(row["retry_count"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_error=row["last_error"],
            payload=payload,
        )
