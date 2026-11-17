"""OmLineageRelationshipStore — biến thể Lineage API của quyết định Q4.

Theo mục 9 của docs/c4-04b-code-structure.md. Hai đầu edge luôn là **File entity của
phiên bản**, không phải Directory của tài liệu (bất biến I6), và `relation_type` được
mang trong `lineageDetails` để truy vấn ngược được theo loại quan hệ (bất biến I7).

Khả năng truy vấn ngược theo loại quan hệ **chưa được kiểm chứng** trên bản triển
khai; đó chính là nội dung test case POC-06 và POC-09. Nếu không đạt, đổi binding sang
`SqliteRelationshipRegistry` mà không sửa use case.
"""

from __future__ import annotations

from typing import Any

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.openmetadata import endpoints
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.domain.model import Relationship
from document_service.domain.port import RelationshipStorePort
from document_service.domain.value import Direction, DocumentVersionId, RelationType
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor

_ENTITY_TYPE = "file"
_RELATION_KEY = "relation_type"


class OmLineageRelationshipStore(RelationshipStorePort, OutboundAdapter):
    """Lưu quan hệ bằng Lineage API của OpenMetadata."""

    def __init__(self, client: OmHttpClient, executor: ResilientCallExecutor) -> None:
        """Nhận client HTTP và executor của phụ thuộc relationship."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_READ)
        self._client = client

    async def upsert(self, relationship: Relationship) -> None:
        """Ghi một lineage edge, idempotent vì PUT theo cặp entity."""
        await self._client.put(endpoints.LINEAGE, self._as_edge(relationship))

    async def query(
        self,
        version_id: DocumentVersionId,
        direction: Direction = Direction.BOTH,
        relation_type: RelationType | None = None,
    ) -> list[Relationship]:
        """Đọc lineage của một phiên bản rồi lọc theo chiều và loại quan hệ."""
        payload = await self._client.get(
            f"{endpoints.LINEAGE_GET}/{_ENTITY_TYPE}/name/{version_id}",
            {"upstreamDepth": 1, "downstreamDepth": 1},
        )
        edges = payload.get("edges", [])
        result: list[Relationship] = []
        for edge in edges if isinstance(edges, list) else []:
            relationship = self._from_edge(edge)
            if relationship is None:
                continue
            if relation_type is not None and relationship.relation_type != relation_type:
                continue
            result.extend(self._match_direction(relationship, version_id, direction))
        return result

    async def remove(self, relationship: Relationship) -> None:
        """Xoá một lineage edge."""
        await self._client.delete(
            endpoints.LINEAGE,
            {
                "fromEntity": _ENTITY_TYPE,
                "fromId": str(relationship.source_version_id),
                "toEntity": _ENTITY_TYPE,
                "toId": str(relationship.target_version_id),
            },
        )

    async def _probe_dependency(self) -> HealthResult:
        """Dùng chung phép thử với catalog: phiên bản server."""
        version = await self._client.server_version()
        return self.health_up(f"lineage api, version={version}")

    def _as_edge(self, relationship: Relationship) -> dict[str, Any]:
        """Payload lineage edge mang `relation_type` trong lineageDetails."""
        return {
            "edge": {
                "fromEntity": {
                    "id": str(relationship.source_version_id),
                    "type": _ENTITY_TYPE,
                },
                "toEntity": {
                    "id": str(relationship.target_version_id),
                    "type": _ENTITY_TYPE,
                },
                "lineageDetails": {
                    "description": str(relationship.relation_type),
                    "source": "Manual",
                    "sqlQuery": None,
                    "columnsLineage": [],
                    _RELATION_KEY: str(relationship.relation_type),
                },
            }
        }

    def _from_edge(self, edge: dict[str, Any]) -> Relationship | None:
        """Dựng Relationship từ một lineage edge, None nếu thiếu relation_type."""
        details = edge.get("lineageDetails", {}) or {}
        raw_type = details.get(_RELATION_KEY) or details.get("description")
        source = (edge.get("fromEntity") or {}).get("id")
        target = (edge.get("toEntity") or {}).get("id")
        if not raw_type or not source or not target:
            return None
        try:
            relation_type = RelationType(str(raw_type))
        except ValueError:
            return None
        return Relationship(
            relation_type=relation_type,
            source_version_id=DocumentVersionId(str(source)),
            target_version_id=DocumentVersionId(str(target)),
        )

    def _match_direction(
        self,
        relationship: Relationship,
        version_id: DocumentVersionId,
        direction: Direction,
    ) -> list[Relationship]:
        """Giữ lại quan hệ đúng chiều yêu cầu, đảo chiều khi đọc incoming."""
        matches: list[Relationship] = []
        if direction in (Direction.OUTGOING, Direction.BOTH):
            if relationship.source_version_id == version_id:
                matches.append(relationship)
        if direction in (Direction.INCOMING, Direction.BOTH):
            if relationship.target_version_id == version_id:
                matches.append(relationship.reversed_direction())
        return matches
