"""Use case đọc lịch sử audit của một tài liệu (D16, test case POC-14)."""

from __future__ import annotations

from dataclasses import dataclass

from document_service.application.usecase.base import ReadUseCase
from document_service.domain.dto import Page, PageRequest
from document_service.domain.model import AuditEvent, Principal
from document_service.domain.value import DocumentId


@dataclass(frozen=True, slots=True)
class ListAuditCommand:
    """Yêu cầu đọc lịch sử audit của một tài liệu."""

    document_id: DocumentId
    principal: Principal
    page: PageRequest = PageRequest()


class ListAuditUseCase(ReadUseCase[ListAuditCommand, Page[AuditEvent]]):
    """Đọc lịch sử audit của một tài liệu (test case POC-14)."""

    async def execute(self, command: ListAuditCommand) -> Page[AuditEvent]:
        """Trả về audit của tài liệu nếu chủ thể có quyền xem metadata."""
        await self._authorize_view(command.principal, str(command.document_id))
        return await self.ports.audit.list_page(command.document_id, command.page)
