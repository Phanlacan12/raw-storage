"""Use case khai báo và truy vấn quan hệ theo phiên bản (bất biến I6, I7)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from document_service.application.context import PolicySet, PortBundle
from document_service.application.orchestration.command_receipt import command_receipt
from document_service.application.usecase.base import (
    AuditOutcome,
    AuditTarget,
    ReadUseCase,
    WriteUseCase,
)
from document_service.domain.dto import Page, PageRequest, RelatedEdge
from document_service.domain.model import Principal, Relationship
from document_service.domain.value import Direction, DocumentVersionId, IdempotencyKey, RelationType


@dataclass(frozen=True, slots=True)
class DeclareRelationshipCommand:
    """Yêu cầu khai báo một quan hệ giữa hai phiên bản."""

    relation_type: RelationType
    source_version_id: DocumentVersionId
    target_version_id: DocumentVersionId
    principal: Principal
    idempotency_key: IdempotencyKey | None = None


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
        async with command_receipt(
            self.ports.intents,
            "relationship.declare",
            asdict(command),
            command.idempotency_key,
            command.source_version_id,
        ) as receipt:
            relationship = Relationship(
                relation_type=command.relation_type,
                source_version_id=command.source_version_id,
                target_version_id=command.target_version_id,
                created_by=command.principal.principal_id,
            )
            if receipt.replayed:
                return relationship
            self._policies.relationship.validate(relationship)
            existing = await self.ports.relationships.query(
                command.source_version_id, Direction.OUTGOING, command.relation_type
            )
            self._policies.relationship.assert_target_not_rebound(
                relationship, [edge.relationship for edge in existing]
            )
            await self.ports.relationships.upsert(relationship)
            await self._record(
                command.principal,
                "relationship.declared",
                AuditTarget(document_id="", target_id=str(command.source_version_id)),
                AuditOutcome.ok(f"{command.relation_type} -> {command.target_version_id}"),
            )
            return relationship


class QueryRelationshipsUseCase(ReadUseCase[QueryRelationshipsCommand, list[RelatedEdge]]):
    """Truy vấn quan hệ hai chiều theo loại quan hệ."""

    async def page(
        self, command: QueryRelationshipsCommand, page: PageRequest
    ) -> Page[RelatedEdge]:
        """Đọc một trang theo cùng chính sách quyền như truy vấn nội bộ."""
        await self._authorize_view(command.principal, str(command.version_id))
        return await self.ports.relationships.query_page(
            command.version_id, command.direction, command.relation_type, page
        )

    async def execute(self, command: QueryRelationshipsCommand) -> list[RelatedEdge]:
        """Trả về quan hệ theo chiều yêu cầu, sau khi kiểm tra quyền xem metadata."""
        await self._authorize_view(command.principal, str(command.version_id))
        return await self.ports.relationships.query(
            command.version_id, command.direction, command.relation_type
        )
