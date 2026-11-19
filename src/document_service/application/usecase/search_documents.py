"""Use case tìm kiếm theo metadata (D18).

Tìm kiếm luôn lọc lại kết quả theo quyền của chủ thể trước khi trả ra, theo yêu cầu
mục 2.6 báo cáo và test case POC-02, POC-17.
"""

from __future__ import annotations

from dataclasses import dataclass

from document_service.application.usecase.base import ReadUseCase
from document_service.domain.dto import SearchPage, SearchQuery
from document_service.domain.model import Principal
from document_service.domain.value import Action


@dataclass(frozen=True, slots=True)
class SearchCommand:
    """Yêu cầu tìm kiếm theo metadata."""

    query: SearchQuery
    principal: Principal


class SearchDocumentsUseCase(ReadUseCase[SearchCommand, SearchPage]):
    """Dịch truy vấn nghiệp vụ sang catalog rồi lọc quyền trên kết quả."""

    async def execute(self, command: SearchCommand) -> SearchPage:
        """Trả về trang kết quả đã lọc theo quyền."""
        await self._authorize(command.principal, Action.SEARCH, "search")
        page = await self.ports.catalog.search(command.query)
        return page.filtered(command.principal, Action.VIEW_METADATA)
