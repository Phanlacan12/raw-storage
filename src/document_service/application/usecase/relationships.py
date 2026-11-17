"""Use case khai báo và truy vấn quan hệ theo phiên bản (bất biến I6, I7)."""

from __future__ import annotations

from dataclasses import dataclass

from document_service.application.context import PolicySet, PortBundle
from document_service.application.usecase.base import (
    AuditOutcome,
    AuditTarget,
    ReadUseCase,
    WriteUseCase,
)
from document_service.domain.model import Principal, Relationship
from document_service.domain.value import Direction, DocumentVersionId, RelationType


@dataclass(frozen=True, slots=True)
class DeclareRelationshipCommand:
    """Yêu cầu khai báo một quan hệ giữa hai phiên bản."""

    relation_type: RelationType
    source_version_id: DocumentVersionId
    target_version_id: DocumentVersionId
    principal: Principal


@dataclass(frozen=True, slots=True)
class QueryRelationshipsCommand:
    """Yêu cầu truy vấn quan hệ của một phiên bản."""

    version_id: DocumentVersionId
    principal: Principal
    direction: Direction = Direction.BOTH
    relation_type: RelationType | None = None


class DeclareRelationshipUseCase(WriteUseCase[DeclareRelationshipCommand, Relationship]):
    """Ghi quan hệ mới sau khi kiểm tra quyền và ràng buộc không đổi đích."""

    def __init__(self, ports: PortBundle, policies: PolicySet) -> None:
        """Nhận bundle port và tập policy."""
        super().__init__(ports)
        self._policies = policies

    async def execute(self, command: DeclareRelationshipCommand) -> Relationship:
        """Khai báo quan hệ, chặn việc đổi đích của quan hệ đã có."""
        await self._authorize_write(command.principal, str(command.source_version_id))
        relationship = Relationship(
            relation_type=command.relation_type,
            source_version_id=command.source_version_id,
            target_version_id=command.target_version_id,
            created_by=command.principal.principal_id,
        )
        self._policies.relationship.validate(relationship)
        existing = await self.ports.relationships.query(
            command.source_version_id, Direction.OUTGOING, command.relation_type
        )
        self._policies.relationship.assert_target_not_rebound(relationship, existing)
        await self.ports.relationships.upsert(relationship)
        await self._record(
            command.principal,
            "relationship.declared",
            AuditTarget(
                document_id="", target_id=str(command.source_version_id)
            ),
            AuditOutcome.ok(f"{command.relation_type} -> {command.target_version_id}"),
        )
        return relationship


class QueryRelationshipsUseCase(
    ReadUseCase[QueryRelationshipsCommand, list[Relationship]]
):
    """Truy vấn quan hệ hai chiều theo loại quan hệ."""

    async def execute(self, command: QueryRelationshipsCommand) -> list[Relationship]:
        """Trả về quan hệ theo chiều yêu cầu, sau khi kiểm tra quyền xem metadata."""
        await self._authorize_view(command.principal, str(command.version_id))
        return await self.ports.relationships.query(
            command.version_id, command.direction, command.relation_type
        )
