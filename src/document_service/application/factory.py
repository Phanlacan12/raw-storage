"""UseCaseFactory: dựng use case từ bundle port và tập policy.

Tách khỏi `ServiceContainer` để mỗi lớp giữ một việc: container lo **wiring hạ tầng**
(executor, adapter, health, metrics), factory lo **dựng use case**. Nhờ đó thêm use
case mới không làm container phình ra.
"""

from __future__ import annotations

from document_service.application.context import PolicySet, PortBundle
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.application.usecase.approve_version import ApproveVersionUseCase
from document_service.application.usecase.create_version import CreateVersionUseCase
from document_service.application.usecase.issue_download import IssueDownloadUseCase
from document_service.application.usecase.register_document import RegisterDocumentUseCase
from document_service.application.usecase.relationships import (
    DeclareRelationshipUseCase,
    QueryRelationshipsUseCase,
)
from document_service.application.usecase.search_documents import (
    ListAuditUseCase,
    SearchDocumentsUseCase,
    UpdateAccessPolicyUseCase,
)


class UseCaseFactory:
    """Dựng từng use case với đúng phụ thuộc đã wiring."""

    def __init__(
        self,
        ports: PortBundle,
        policies: PolicySet,
        presign_ttl_seconds: int = 300,
        builder: CatalogMetadataBuilder | None = None,
    ) -> None:
        """Nhận bundle port, tập policy và thời hạn link tải."""
        self._ports = ports
        self._policies = policies
        self._builder = builder or CatalogMetadataBuilder()
        self._presign_ttl_seconds = presign_ttl_seconds

    def register_document(self) -> RegisterDocumentUseCase:
        """Use case đăng ký tài liệu."""
        return RegisterDocumentUseCase(self._ports, self._builder)

    def create_version(self) -> CreateVersionUseCase:
        """Use case tạo phiên bản."""
        return CreateVersionUseCase(self._ports, self._policies, self._builder)

    def approve_version(self) -> ApproveVersionUseCase:
        """Use case chuyển trạng thái phiên bản."""
        return ApproveVersionUseCase(self._ports, self._policies, self._builder)

    def declare_relationship(self) -> DeclareRelationshipUseCase:
        """Use case khai báo quan hệ."""
        return DeclareRelationshipUseCase(self._ports, self._policies)

    def query_relationships(self) -> QueryRelationshipsUseCase:
        """Use case truy vấn quan hệ."""
        return QueryRelationshipsUseCase(self._ports)

    def issue_download(self) -> IssueDownloadUseCase:
        """Use case cấp file."""
        return IssueDownloadUseCase(self._ports, self._presign_ttl_seconds)

    def search_documents(self) -> SearchDocumentsUseCase:
        """Use case tìm kiếm."""
        return SearchDocumentsUseCase(self._ports)

    def update_access_policy(self) -> UpdateAccessPolicyUseCase:
        """Use case cập nhật chính sách truy cập."""
        return UpdateAccessPolicyUseCase(self._ports, self._builder)

    def list_audit(self) -> ListAuditUseCase:
        """Use case đọc audit."""
        return ListAuditUseCase(self._ports)
