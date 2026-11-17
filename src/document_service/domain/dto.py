"""Kiểu dữ liệu dùng trong hợp đồng của các port.

Đây là dữ liệu đi qua ranh giới port, không phải thực thể nghiệp vụ; tách khỏi
model.py để model chỉ còn thực thể và hành vi giữ bất biến.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from document_service.domain.model import AccessPolicy, DocumentMetadata, Principal
from document_service.domain.value import (
    Action,
    Actor,
    Checksum,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    IdempotencyKey,
    VersionLabel,
)


@dataclass(frozen=True, slots=True)
class EntityRef:
    """Tham chiếu tới một entity trong catalog."""

    entity_id: str
    entity_type: str
    fully_qualified_name: str = ""
    entity_version: float | None = None


@dataclass(frozen=True, slots=True)
class PutResult:
    """Kết quả ghi object lên Object Storage."""

    etag: str
    size_bytes: int
    checksum: Checksum
    already_existed: bool = False


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    """Thông tin một object trên Object Storage."""

    key: str
    size_bytes: int
    etag: str = ""
    checksum: Checksum | None = None


@dataclass(frozen=True, slots=True)
class UploadRequest:
    """Yêu cầu tạo một phiên bản nội dung mới."""

    document_id: DocumentId
    original_file_name: str
    content_format: str
    checksum: Checksum
    size_bytes: int
    actor: Actor
    idempotency_key: IdempotencyKey
    label: VersionLabel | None = None


@dataclass(frozen=True, slots=True)
class SearchFilter:
    """Điều kiện lọc trên một trường metadata."""

    field_name: str
    value: str


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """Truy vấn tìm kiếm theo metadata, có phân trang theo con trỏ."""

    text: str = ""
    filters: tuple[SearchFilter, ...] = ()
    page_size: int = 20
    cursor: str | None = None

    def filter_value(self, field_name: str) -> str | None:
        """Giá trị của một điều kiện lọc, nếu có."""
        for item in self.filters:
            if item.field_name == field_name:
                return item.value
        return None


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Một kết quả tìm kiếm ở mức phiên bản."""

    version_id: DocumentVersionId
    document_id: DocumentId
    status: DocumentStatus
    metadata: DocumentMetadata
    label: VersionLabel | None = None
    access_policy: AccessPolicy = field(default_factory=AccessPolicy)


@dataclass(frozen=True, slots=True)
class SearchPage:
    """Một trang kết quả tìm kiếm."""

    hits: tuple[SearchHit, ...] = ()
    next_cursor: str | None = None
    total_hits: int = 0

    def filtered(self, principal: Principal, action: Action = Action.VIEW_METADATA) -> SearchPage:
        """Lọc lại kết quả theo quyền của chủ thể (POC-02, POC-17)."""
        allowed = tuple(hit for hit in self.hits if hit.access_policy.permits(principal, action))
        return SearchPage(hits=allowed, next_cursor=self.next_cursor, total_hits=len(allowed))


@dataclass(frozen=True, slots=True)
class Decision:
    """Kết quả quyết định quyền của PolicyDecisionPort."""

    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls) -> Decision:
        """Quyết định cho phép."""
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> Decision:
        """Quyết định từ chối kèm lý do để ghi audit."""
        return cls(allowed=False, reason=reason)


@dataclass(frozen=True, slots=True)
class DownloadGrant:
    """Kết quả cấp quyền tải một phiên bản."""

    version_id: DocumentVersionId
    url: str | None = None
    proxied: bool = False
    expires_in_seconds: int = 0
