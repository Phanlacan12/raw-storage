"""Use case tìm kiếm, cập nhật policy và đọc audit.

Tìm kiếm luôn lọc lại kết quả theo quyền của chủ thể trước khi trả ra, theo yêu cầu
mục 2.6 báo cáo và test case POC-02, POC-17.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from document_service.application.context import PortBundle
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.application.usecase.base import (
    AuditOutcome,
    AuditTarget,
    ReadUseCase,
    WriteUseCase,
)
from document_service.domain.dto import SearchPage, SearchQuery
from document_service.domain.model import AccessPolicy, AuditEvent, Principal
from document_service.domain.value import Action, DocumentId


@dataclass(frozen=True, slots=True)
class SearchCommand:
    """Yêu cầu tìm kiếm theo metadata."""

    query: SearchQuery
    principal: Principal


@dataclass(frozen=True, slots=True)
class UpdateAccessPolicyCommand:
    """Yêu cầu cập nhật chính sách truy cập của tài liệu."""

    document_id: DocumentId
    principal: Principal
    access_policy: AccessPolicy = field(default_factory=AccessPolicy)


@dataclass(frozen=True, slots=True)
class ListAuditCommand:
    """Yêu cầu đọc lịch sử audit của một tài liệu."""

    document_id: DocumentId
    principal: Principal


class SearchDocumentsUseCase(ReadUseCase[SearchCommand, SearchPage]):
    """Dịch truy vấn nghiệp vụ sang catalog rồi lọc quyền trên kết quả."""

    async def execute(self, command: SearchCommand) -> SearchPage:
        """Trả về trang kết quả đã lọc theo quyền."""
        await self._authorize(command.principal, Action.SEARCH, "search")
        page = await self.ports.catalog.search(command.query)
        return page.filtered(command.principal, Action.VIEW_METADATA)


class UpdateAccessPolicyUseCase(WriteUseCase[UpdateAccessPolicyCommand, AccessPolicy]):
    """Cập nhật access_policy và ghi audit để downstream đồng bộ."""

    def __init__(
        self, ports: PortBundle, builder: CatalogMetadataBuilder | None = None
    ) -> None:
        """Nhận bundle port và bộ dựng metadata."""
        super().__init__(ports)
        self._builder = builder or CatalogMetadataBuilder()

    async def execute(self, command: UpdateAccessPolicyCommand) -> AccessPolicy:
        """Ghi policy mới qua Document Service, không qua catalog UI."""
        await self._authorize(
            command.principal, Action.MANAGE_POLICY, str(command.document_id)
        )
        document = await self.ports.catalog.read_document(command.document_id)
        document.access_policy = command.access_policy
        await self.ports.catalog.patch_document_fields(
            command.document_id, self._builder.document_fields(document)
        )
        await self._record(
            command.principal,
            "document.access_policy_changed",
            AuditTarget.of_document(command.document_id),
            AuditOutcome.ok(command.access_policy.classification),
        )
        return command.access_policy


class ListAuditUseCase(ReadUseCase[ListAuditCommand, list[AuditEvent]]):
    """Đọc lịch sử audit của một tài liệu (test case POC-14)."""

    async def execute(self, command: ListAuditCommand) -> list[AuditEvent]:
        """Trả về audit của tài liệu nếu chủ thể có quyền xem metadata."""
        await self._authorize_view(command.principal, str(command.document_id))
        return await self.ports.audit.list_for_document(command.document_id)
