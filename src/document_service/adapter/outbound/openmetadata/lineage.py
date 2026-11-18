"""OmLineageRelationshipStore — biến thể Lineage API của quyết định Q4.

Theo mục 9 của docs/c4-04b-code-structure.md. Hai đầu edge luôn là **File entity của
phiên bản**, không phải Directory của tài liệu (bất biến I6), và `relation_type` được
mang trong `lineageDetails.description` để truy vấn ngược được theo loại quan hệ
(bất biến I7).

Chọn hiện thực này thay cho `SqliteRelationshipRegistry` khi muốn quan hệ **hiện trên
tab Lineage của giao diện OpenMetadata**: quan hệ trở thành dữ liệu của catalog chứ
không nằm trong một database riêng mà OpenMetadata không biết tới.

Phần khó nhất là phân giải danh tính. Lineage API làm việc bằng **UUID** của entity,
còn port quan hệ chỉ truyền `document_version_id` (ví dụ `VER-01M7...`), không có
`document_id` nên không dựng trực tiếp được FQN
`{service}.{root}.{document_id}.{version_id}`. `_VersionIndex` giải quyết bằng cách
liệt kê File entity của drive service và nhớ hai chiều `version_id ↔ UUID`.

Điều kiện: `getLineage` tra entity qua search index, nên File entity phải index được.
Trên OpenMetadata 1.12.0 nguyên bản thì không — chạy `make compose-ready` (hoặc
`make compose-patch`) trước, xem deploy/patch_openmetadata.py.

Giới hạn đã biết: lần tra đầu tiên sau khi khởi động phải liệt kê toàn bộ File entity.
Với kho PoC vài nghìn phiên bản là chấp nhận được; ở quy mô lớn hơn thì phải truyền
`document_id` xuống tận port để dựng FQN trực tiếp.
"""

from __future__ import annotations

from typing import Any

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.openmetadata import endpoints
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.domain.errors import DocumentNotFoundError
from document_service.domain.model import Relationship
from document_service.domain.port import RelationshipStorePort
from document_service.domain.value import Direction, DocumentVersionId, RelationType
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor

_ENTITY_TYPE = "file"
_PAGE_SIZE = 200


class _VersionIndex:
    """Nhớ hai chiều `version_id ↔ (UUID, FQN)` của File entity.

    Lineage API chỉ nhận UUID, còn quan hệ nghiệp vụ chỉ mang version id. Lớp này là
    chỗ duy nhất biết cách đi giữa hai thế giới đó.
    """

    def __init__(self, client: OmHttpClient) -> None:
        """Nhận client HTTP, chưa gọi mạng cho tới lần tra đầu tiên."""
        self._client = client
        self._by_version: dict[str, tuple[str, str]] = {}

    def remember(self, version_id: str, entity_id: str, fqn: str) -> None:
        """Ghi nhớ một File entity đã biết.

        Chỉ cần chiều version → (UUID, FQN): khi đọc lineage, FQN đã nằm sẵn trong
        cạnh nên không phải tra ngược từ UUID.
        """
        self._by_version[version_id] = (entity_id, fqn)

    async def entity_of(self, version_id: DocumentVersionId) -> tuple[str, str]:
        """(UUID, FQN) của phiên bản; làm mới cache một lần nếu chưa thấy."""
        key = str(version_id)
        if key not in self._by_version:
            await self._refresh()
        if key not in self._by_version:
            raise DocumentNotFoundError(f"version {version_id} has no file entity in the catalog")
        return self._by_version[key]

    async def _refresh(self) -> None:
        """Liệt kê toàn bộ File entity, theo trang, nạp vào cache."""
        after: str | None = None
        while True:
            params: dict[str, Any] = {"limit": _PAGE_SIZE}
            if after:
                params["after"] = after
            payload = await self._client.get(endpoints.FILES, params)
            for item in payload.get("data", []) or []:
                if not isinstance(item, dict):
                    continue
                name, entity_id = item.get("name"), item.get("id")
                if name and entity_id:
                    self.remember(
                        str(name), str(entity_id), str(item.get("fullyQualifiedName") or "")
                    )
            after = (payload.get("paging") or {}).get("after")
            if not after:
                return


class OmLineageRelationshipStore(RelationshipStorePort, OutboundAdapter):
    """Lưu quan hệ bằng Lineage API của OpenMetadata."""

    def __init__(self, client: OmHttpClient, executor: ResilientCallExecutor) -> None:
        """Nhận client HTTP và executor của phụ thuộc relationship."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_READ)
        self._client = client
        self._index = _VersionIndex(client)

    async def upsert(self, relationship: Relationship) -> None:
        """Ghi một lineage edge, idempotent vì PUT theo cặp entity."""
        source_id, _ = await self._index.entity_of(relationship.source_version_id)
        target_id, _ = await self._index.entity_of(relationship.target_version_id)
        await self._client.put(
            endpoints.LINEAGE,
            {
                "edge": {
                    "fromEntity": {"id": source_id, "type": _ENTITY_TYPE},
                    "toEntity": {"id": target_id, "type": _ENTITY_TYPE},
                    # `relation_type` đi trong `description`: LineageDetails có schema
                    # cố định, key lạ bị server bỏ đi nên không giữ được ở đâu khác.
                    "lineageDetails": {
                        "description": str(relationship.relation_type),
                        "source": "Manual",
                        "columnsLineage": [],
                    },
                }
            },
        )

    async def query(
        self,
        version_id: DocumentVersionId,
        direction: Direction = Direction.BOTH,
        relation_type: RelationType | None = None,
    ) -> list[Relationship]:
        """Đọc lineage của một phiên bản rồi lọc theo chiều và loại quan hệ."""
        try:
            _, fqn = await self._index.entity_of(version_id)
        except DocumentNotFoundError:
            # Chưa có File entity thì cũng chưa thể có quan hệ nào.
            return []
        # Phải truyền fqn/type qua query param. Dạng đường dẫn
        # `/getLineage/{type}/name/{fqn}` bị OpenMetadata 1.12 trả 405.
        payload = await self._client.get(
            endpoints.LINEAGE_GET,
            {"fqn": fqn, "type": _ENTITY_TYPE, "upstreamDepth": 1, "downstreamDepth": 1},
        )
        result: list[Relationship] = []
        for edge in self._edges_of(payload):
            relationship = self._from_edge(edge)
            if relationship is None:
                continue
            if relation_type is not None and relationship.relation_type != relation_type:
                continue
            result.extend(self._match_direction(relationship, version_id, direction))
        return result

    async def remove(self, relationship: Relationship) -> None:
        """Xoá một lineage edge."""
        source_id, _ = await self._index.entity_of(relationship.source_version_id)
        target_id, _ = await self._index.entity_of(relationship.target_version_id)
        await self._client.delete(
            endpoints.LINEAGE,
            {
                "fromEntity": _ENTITY_TYPE,
                "fromId": source_id,
                "toEntity": _ENTITY_TYPE,
                "toId": target_id,
            },
        )

    async def _probe_dependency(self) -> HealthResult:
        """Dùng chung phép thử với catalog: phiên bản server."""
        version = await self._client.server_version()
        return self.health_up(f"lineage api, version={version}")

    def _edges_of(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Gộp cạnh vào ra thành một danh sách.

        OpenMetadata 1.12 **không** trả về khoá `edges`. Nó trả `upstreamEdges` và
        `downstreamEdges`, mỗi cái là một **dict** keyed `"<fromFqn>--->“toFqn>"`.
        Đọc `payload["edges"]` sẽ luôn ra rỗng và quan hệ trông như bị mất.
        """
        edges: list[dict[str, Any]] = []
        for key in ("upstreamEdges", "downstreamEdges"):
            group = payload.get(key)
            if isinstance(group, dict):
                edges.extend(item for item in group.values() if isinstance(item, dict))
            elif isinstance(group, list):
                edges.extend(item for item in group if isinstance(item, dict))
        return edges

    def _from_edge(self, edge: dict[str, Any]) -> Relationship | None:
        """Dựng Relationship từ một lineage edge, None nếu không đọc được."""
        # `description` nằm ở cấp trên cùng của cạnh khi ĐỌC, dù lúc GHI phải đặt
        # trong `lineageDetails`. Bất đối xứng này là của API, không phải nhầm lẫn.
        raw_type = edge.get("description")
        source = self._version_from_fqn((edge.get("fromEntity") or {}).get("fullyQualifiedName"))
        target = self._version_from_fqn((edge.get("toEntity") or {}).get("fullyQualifiedName"))
        if not raw_type or source is None or target is None:
            return None
        try:
            relation_type = RelationType(str(raw_type))
        except ValueError:
            return None
        return Relationship(
            relation_type=relation_type,
            source_version_id=source,
            target_version_id=target,
        )

    def _version_from_fqn(self, fqn: Any) -> DocumentVersionId | None:
        """Lấy version id từ đoạn cuối của FQN `{service}.{root}.{doc}.{version}`."""
        if not isinstance(fqn, str) or "." not in fqn:
            return None
        name = fqn.rsplit(".", 1)[-1]
        return DocumentVersionId(name) if name else None

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
