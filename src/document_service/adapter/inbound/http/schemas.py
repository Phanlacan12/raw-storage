"""Schema request/response của API công khai.

Theo mục 12 của docs/c4-04b-code-structure.md: API **không** phơi bày khái niệm của
OpenMetadata — không có `fqn`, `extension`, `entityType` trong payload. Đổi phiên bản
hay sản phẩm catalog không được làm vỡ hợp đồng này.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from document_service.domain.dto import DownloadGrant, SearchPage
from document_service.domain.model import (
    AccessPolicy,
    AuditEvent,
    Document,
    DocumentVersion,
    Relationship,
)
from document_service.domain.value import DocumentStatus, RelationType


class AccessPolicyPayload(BaseModel):
    """Chính sách truy cập trong payload API."""

    classification: str = "restricted"
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_principals: list[str] = Field(default_factory=list)
    require_proxy_download: bool = False

    def to_domain(self) -> AccessPolicy:
        """Chuyển sang AccessPolicy của miền nghiệp vụ."""
        return AccessPolicy(
            classification=self.classification,
            allowed_groups=tuple(self.allowed_groups),
            allowed_principals=tuple(self.allowed_principals),
            require_proxy_download=self.require_proxy_download,
        )

    @classmethod
    def from_domain(cls, policy: AccessPolicy) -> AccessPolicyPayload:
        """Dựng payload từ AccessPolicy."""
        return cls(
            classification=policy.classification,
            allowed_groups=list(policy.allowed_groups),
            allowed_principals=list(policy.allowed_principals),
            require_proxy_download=policy.require_proxy_download,
        )


class CreateDocumentRequest(BaseModel):
    """Yêu cầu đăng ký tài liệu mới."""

    title: str = ""
    description: str = ""
    document_type: str = ""
    tags: list[str] = Field(default_factory=list)
    language: str = ""
    owner: str = ""
    department: str = ""
    collection_id: str = ""
    retention_policy: str = ""
    document_id: str | None = None
    access_policy: AccessPolicyPayload = Field(default_factory=AccessPolicyPayload)


class DocumentResponse(BaseModel):
    """Thông tin tài liệu trả về."""

    document_id: str
    title: str
    document_type: str
    collection_id: str
    classification: str
    current_version_id: str | None = None
    version_count: int = 0

    @classmethod
    def from_domain(cls, document: Document) -> DocumentResponse:
        """Dựng response từ Document."""
        current = document.current_version_id
        return cls(
            document_id=str(document.document_id),
            title=document.metadata.title,
            document_type=document.metadata.document_type,
            collection_id=document.metadata.collection_id,
            classification=document.access_policy.classification,
            current_version_id=str(current) if current is not None else None,
            version_count=len(document.versions),
        )


class VersionResponse(BaseModel):
    """Thông tin một phiên bản nội dung."""

    document_version_id: str
    document_id: str
    version_label: str
    status: DocumentStatus
    checksum: str
    original_file_name: str
    size_bytes: int
    created: bool = True
    duplicate_of: str | None = None

    @classmethod
    def from_domain(
        cls, version: DocumentVersion, created: bool = True, duplicate: bool = False
    ) -> VersionResponse:
        """Dựng response từ DocumentVersion."""
        return cls(
            document_version_id=str(version.version_id),
            document_id=str(version.document_id),
            version_label=str(version.label),
            status=version.status,
            checksum=str(version.checksum),
            original_file_name=version.original_file_name,
            size_bytes=version.size_bytes,
            created=created,
            duplicate_of=str(version.version_id) if duplicate else None,
        )


class TransitionStatusRequest(BaseModel):
    """Yêu cầu chuyển trạng thái một phiên bản."""

    status: DocumentStatus


class DeclareRelationshipRequest(BaseModel):
    """Yêu cầu khai báo quan hệ giữa hai phiên bản."""

    relation_type: RelationType
    source_version_id: str
    target_version_id: str


class RelationshipResponse(BaseModel):
    """Một quan hệ theo phiên bản."""

    relation_type: RelationType
    source_version_id: str
    target_version_id: str

    @classmethod
    def from_domain(cls, relationship: Relationship) -> RelationshipResponse:
        """Dựng response từ Relationship."""
        return cls(
            relation_type=relationship.relation_type,
            source_version_id=str(relationship.source_version_id),
            target_version_id=str(relationship.target_version_id),
        )


class SearchHitResponse(BaseModel):
    """Một kết quả tìm kiếm."""

    document_version_id: str
    document_id: str
    status: DocumentStatus
    title: str
    document_type: str
    collection_id: str
    version_label: str | None = None


class SearchResponse(BaseModel):
    """Trang kết quả tìm kiếm."""

    hits: list[SearchHitResponse]
    next_cursor: str | None = None
    total_hits: int = 0

    @classmethod
    def from_domain(cls, page: SearchPage) -> SearchResponse:
        """Dựng response từ SearchPage."""
        return cls(
            hits=[
                SearchHitResponse(
                    document_version_id=str(hit.version_id),
                    document_id=str(hit.document_id),
                    status=hit.status,
                    title=hit.metadata.title,
                    document_type=hit.metadata.document_type,
                    collection_id=hit.metadata.collection_id,
                    version_label=str(hit.label) if hit.label is not None else None,
                )
                for hit in page.hits
            ],
            next_cursor=page.next_cursor,
            total_hits=page.total_hits,
        )


class DownloadResponse(BaseModel):
    """Kết quả cấp quyền tải."""

    document_version_id: str
    url: str | None = None
    proxied: bool = False
    expires_in_seconds: int = 0

    @classmethod
    def from_domain(cls, grant: DownloadGrant) -> DownloadResponse:
        """Dựng response từ DownloadGrant."""
        return cls(
            document_version_id=str(grant.version_id),
            url=grant.url,
            proxied=grant.proxied,
            expires_in_seconds=grant.expires_in_seconds,
        )


class AuditEventResponse(BaseModel):
    """Một bản ghi audit."""

    actor: str
    action: str
    target_id: str
    result: str
    detail: str
    occurred_at: str

    @classmethod
    def from_domain(cls, event: AuditEvent) -> AuditEventResponse:
        """Dựng response từ AuditEvent."""
        return cls(
            actor=event.actor.principal_id,
            action=event.action,
            target_id=event.target_id,
            result=event.result,
            detail=event.detail,
            occurred_at=event.occurred_at.isoformat(),
        )
