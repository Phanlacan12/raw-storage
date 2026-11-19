"""SqliteRelationshipRegistry — biến thể registry của quyết định Q4.

Dùng khi Lineage API của OpenMetadata không truy vấn ngược được theo `relation_type`
cho File entity (test case POC-06, POC-09). Khi đó registry này là nguồn sự thật cho
quan hệ và phải được đưa vào backup, đối soát và dự toán hạ tầng.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.domain.dto import Page, PageRequest, RelatedEdge
from document_service.domain.model import Relationship
from document_service.domain.port import RelationshipStorePort
from document_service.domain.value import Direction, DocumentVersionId, RelationType
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor

_COLUMNS = "relation_type, source_version_id, target_version_id, created_at, created_by"


class SqliteRelationshipRegistry(RelationshipStorePort, OutboundAdapter):
    """Registry quan hệ trên sqlite, có index cho cả hai chiều."""

    def __init__(self, database: SqliteDatabase, executor: ResilientCallExecutor) -> None:
        """Nhận database và executor của phụ thuộc relationship."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_READ)
        self._db = database

    async def upsert(self, relationship: Relationship) -> None:
        """Ghi quan hệ, idempotent theo khóa chính ba cột."""
        await self._call(
            lambda: self._db.execute(
                f"INSERT OR IGNORE INTO relationship ({_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (
                    str(relationship.relation_type),
                    str(relationship.source_version_id),
                    str(relationship.target_version_id),
                    relationship.created_at.isoformat(),
                    relationship.created_by,
                ),
            )
        )

    async def query(
        self,
        version_id: DocumentVersionId,
        direction: Direction = Direction.BOTH,
        relation_type: RelationType | None = None,
    ) -> list[RelatedEdge]:
        """Truy vấn quan hệ theo chiều và loại (bất biến I7)."""
        results: list[RelatedEdge] = []
        if direction in (Direction.OUTGOING, Direction.BOTH):
            rows = await self._select("source_version_id", version_id, relation_type)
            results.extend(RelatedEdge(self._from_row(row), Direction.OUTGOING) for row in rows)
        if direction in (Direction.INCOMING, Direction.BOTH):
            rows = await self._select("target_version_id", version_id, relation_type)
            results.extend(RelatedEdge(self._from_row(row), Direction.INCOMING) for row in rows)
        return results

    async def query_page(
        self,
        version_id: DocumentVersionId,
        direction: Direction,
        relation_type: RelationType | None,
        page: PageRequest,
    ) -> Page[RelatedEdge]:
        """Gộp hai chiều trước khi LIMIT để một offset đại diện cả trang."""
        rows = await self._call(
            lambda: self._db.query(
                """SELECT *, 'outgoing' AS direction FROM relationship
               WHERE source_version_id = ?1 AND ?2 IN ('both','outgoing')
               AND (?3 IS NULL OR relation_type = ?3)
               UNION ALL
               SELECT *, 'incoming' AS direction FROM relationship
               WHERE target_version_id = ?1 AND ?2 IN ('both','incoming')
               AND (?3 IS NULL OR relation_type = ?3)
               ORDER BY source_version_id, target_version_id, relation_type, direction
               LIMIT ?4 OFFSET ?5""",
                (str(version_id), str(direction), relation_type, page.page_size + 1, page.position),
            )
        )
        edges = [RelatedEdge(self._from_row(row), Direction(row["direction"])) for row in rows]
        return page.window(edges, page.position + page.page_size)

    async def remove(self, relationship: Relationship) -> None:
        """Xoá một quan hệ."""
        await self._call(
            lambda: self._db.execute(
                """
                DELETE FROM relationship
                WHERE relation_type = ? AND source_version_id = ? AND target_version_id = ?
                """,
                (
                    str(relationship.relation_type),
                    str(relationship.source_version_id),
                    str(relationship.target_version_id),
                ),
            )
        )

    async def _probe_dependency(self) -> HealthResult:
        """Đếm số quan hệ, thao tác chỉ đọc."""
        rows = await self._db.query("SELECT COUNT(*) AS total FROM relationship")
        total = rows[0]["total"] if rows else 0
        return self.health_up(f"sqlite ok, relationships={total}")

    async def _select(
        self, column: str, version_id: DocumentVersionId, relation_type: RelationType | None
    ) -> list[dict[str, Any]]:
        """Đọc quan hệ theo một cột đầu và loại quan hệ tùy chọn."""
        sql = f"SELECT {_COLUMNS} FROM relationship WHERE {column} = ?"
        params: list[Any] = [str(version_id)]
        if relation_type is not None:
            sql = f"{sql} AND relation_type = ?"
            params.append(str(relation_type))
        return await self._call(lambda: self._db.query(sql, tuple(params)))

    def _from_row(self, row: dict[str, Any]) -> Relationship:
        """Dựng lại quan hệ từ một dòng sqlite."""
        return Relationship(
            relation_type=RelationType(row["relation_type"]),
            source_version_id=DocumentVersionId(row["source_version_id"]),
            target_version_id=DocumentVersionId(row["target_version_id"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
        )
