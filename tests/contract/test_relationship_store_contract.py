"""Bộ test hợp đồng của RelationshipStorePort (chốt quyết định Q4).

Khẳng định chính: truy vấn **hai chiều** đúng `relation_type`, và tạo phiên bản mới
không làm đổi đích của quan hệ cũ — nội dung của test case POC-06 và POC-09.
"""

from __future__ import annotations

from document_service.domain.model import Relationship
from document_service.domain.port import RelationshipStorePort
from document_service.domain.value import Direction, DocumentVersionId, RelationType

SRS_V20 = DocumentVersionId("VER-SRS-0020")
URD_V12 = DocumentVersionId("VER-URD-0012")
SAD_V11 = DocumentVersionId("VER-SAD-0011")


def _relationship(
    relation_type: RelationType,
    source: DocumentVersionId,
    target: DocumentVersionId,
) -> Relationship:
    """Dựng quan hệ mẫu."""
    return Relationship(
        relation_type=relation_type,
        source_version_id=source,
        target_version_id=target,
        created_by="tester",
    )


class TestRelationshipStoreContract:
    """Hợp đồng chung cho mọi hiện thực relationship store."""

    async def test_outgoing_query(self, relationship_store: RelationshipStorePort) -> None:
        """Đọc được quan hệ theo chiều đi."""
        await relationship_store.upsert(
            _relationship(RelationType.DERIVED_FROM, SRS_V20, URD_V12)
        )
        items = await relationship_store.query(SRS_V20, Direction.OUTGOING)
        assert len(items) == 1
        assert items[0].target_version_id == URD_V12

    async def test_incoming_query_reverses_edge(
        self, relationship_store: RelationshipStorePort
    ) -> None:
        """Truy vấn ngược trả về đúng loại quan hệ và đúng phiên bản đối diện."""
        await relationship_store.upsert(
            _relationship(RelationType.DERIVED_FROM, SRS_V20, URD_V12)
        )
        items = await relationship_store.query(URD_V12, Direction.INCOMING)
        assert len(items) == 1
        assert items[0].relation_type is RelationType.DERIVED_FROM
        assert items[0].target_version_id == SRS_V20

    async def test_filter_by_relation_type(
        self, relationship_store: RelationshipStorePort
    ) -> None:
        """Lọc theo loại quan hệ không trả lẫn loại khác."""
        await relationship_store.upsert(
            _relationship(RelationType.DERIVED_FROM, SRS_V20, URD_V12)
        )
        await relationship_store.upsert(
            _relationship(RelationType.REFERENCES, SAD_V11, SRS_V20)
        )
        derived = await relationship_store.query(
            SRS_V20, Direction.BOTH, RelationType.DERIVED_FROM
        )
        assert len(derived) == 1
        assert derived[0].relation_type is RelationType.DERIVED_FROM

    async def test_upsert_is_idempotent(
        self, relationship_store: RelationshipStorePort
    ) -> None:
        """Ghi lại cùng một cạnh không tạo bản trùng."""
        relationship = _relationship(RelationType.REFERENCES, SAD_V11, SRS_V20)
        await relationship_store.upsert(relationship)
        await relationship_store.upsert(relationship)
        items = await relationship_store.query(SAD_V11, Direction.OUTGOING)
        assert len(items) == 1

    async def test_both_direction_returns_two_edges(
        self, relationship_store: RelationshipStorePort
    ) -> None:
        """Một phiên bản ở giữa chuỗi có cả quan hệ đi và đến."""
        await relationship_store.upsert(
            _relationship(RelationType.DERIVED_FROM, SRS_V20, URD_V12)
        )
        await relationship_store.upsert(
            _relationship(RelationType.REFERENCES, SAD_V11, SRS_V20)
        )
        items = await relationship_store.query(SRS_V20, Direction.BOTH)
        assert len(items) == 2
        assert {item.relation_type for item in items} == {
            RelationType.DERIVED_FROM,
            RelationType.REFERENCES,
        }

    async def test_remove_edge(self, relationship_store: RelationshipStorePort) -> None:
        """Xoá quan hệ thì truy vấn không còn trả về."""
        relationship = _relationship(RelationType.SUPERSEDES, SRS_V20, URD_V12)
        await relationship_store.upsert(relationship)
        await relationship_store.remove(relationship)
        assert await relationship_store.query(SRS_V20, Direction.OUTGOING) == []

    async def test_new_version_does_not_rebind(
        self, relationship_store: RelationshipStorePort
    ) -> None:
        """POC-09: thêm quan hệ cho phiên bản mới không đổi đích quan hệ cũ."""
        srs_v21 = DocumentVersionId("VER-SRS-0021")
        await relationship_store.upsert(
            _relationship(RelationType.DERIVED_FROM, SRS_V20, URD_V12)
        )
        await relationship_store.upsert(
            _relationship(RelationType.SUPERSEDES, srs_v21, SRS_V20)
        )
        old_edges = await relationship_store.query(
            SRS_V20, Direction.OUTGOING, RelationType.DERIVED_FROM
        )
        assert len(old_edges) == 1
        assert old_edges[0].target_version_id == URD_V12
