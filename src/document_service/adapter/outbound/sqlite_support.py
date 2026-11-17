"""Hạ tầng sqlite dùng chung cho intent store, relationship registry, audit và outbox.

sqlite ở đây đóng vai **registry database** của biến thể B trong quyết định Q2: đủ để
kiểm chứng idempotency, concurrency và phục hồi sau restart trong PoC. Khi triển khai
thật, đổi sang PostgreSQL chỉ cần thay lớp này, vì adapter chỉ gọi `execute`/`query`.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Sequence

from document_service.utils.asyncx import ThreadOffloader
from document_service.utils.files import LocalPaths

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS upload_intent (
        request_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        document_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        expected_checksum TEXT NOT NULL,
        state TEXT NOT NULL,
        retry_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_error TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS relationship (
        relation_type TEXT NOT NULL,
        source_version_id TEXT NOT NULL,
        target_version_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (relation_type, source_version_id, target_version_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_relationship_source ON relationship(source_version_id)",
    "CREATE INDEX IF NOT EXISTS idx_relationship_target ON relationship(target_version_id)",
    """
    CREATE TABLE IF NOT EXISTS audit_event (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target_id TEXT NOT NULL,
        document_id TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        occurred_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_event(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_document ON audit_event(document_id)",
    """
    CREATE TABLE IF NOT EXISTS outbox_event (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        document_id TEXT NOT NULL,
        version_id TEXT NOT NULL DEFAULT '',
        payload TEXT NOT NULL DEFAULT '{}',
        occurred_at TEXT NOT NULL,
        published INTEGER NOT NULL DEFAULT 0,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox_event(published, event_id)",
)


class SqliteDatabase:
    """Bọc sqlite3 để gọi được từ code async mà không chặn event loop."""

    def __init__(self, path: str, timeout_seconds: float = 5.0) -> None:
        """Tạo thư mục chứa file, bật WAL và dựng schema."""
        self._path = str(LocalPaths().ensure_parent(path))
        self._timeout = timeout_seconds
        self._offloader = ThreadOffloader()
        self._initialize()

    @property
    def path(self) -> str:
        """Đường dẫn file sqlite."""
        return self._path

    def connect(self) -> sqlite3.Connection:
        """Mở kết nối mới, mỗi thao tác một kết nối để an toàn với thread."""
        connection = sqlite3.connect(self._path, timeout=self._timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Chạy một câu lệnh ghi, trả số dòng bị ảnh hưởng."""
        return await self._offloader.call(self._execute_sync, sql, tuple(params))

    async def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Chạy một câu lệnh đọc, trả danh sách dict."""
        return await self._offloader.call(self._query_sync, sql, tuple(params))

    def _initialize(self) -> None:
        """Tạo bảng và index nếu chưa có."""
        with self.connect() as connection:
            self._apply_schema(connection, SCHEMA_STATEMENTS)

    def _apply_schema(self, connection: sqlite3.Connection, statements: Iterable[str]) -> None:
        """Chạy danh sách câu lệnh DDL."""
        for statement in statements:
            connection.execute(statement)

    def _execute_sync(self, sql: str, params: tuple[Any, ...]) -> int:
        """Phần đồng bộ của execute, chạy trên thread pool."""
        with self.connect() as connection:
            cursor = connection.execute(sql, params)
            return cursor.rowcount

    def _query_sync(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Phần đồng bộ của query, chạy trên thread pool."""
        with self.connect() as connection:
            cursor = connection.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
