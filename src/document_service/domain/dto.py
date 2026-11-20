"""Kiểu dữ liệu dùng trong hợp đồng của các port.

Đây là dữ liệu đi qua ranh giới port, không phải thực thể nghiệp vụ; tách khỏi
model.py để model chỉ còn thực thể và hành vi giữ bất biến.
"""

from __future__ import annotations

from base64 import b64decode, urlsafe_b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass, field
from typing import Generic, Sequence, TypeVar

from document_service.domain.errors import InvalidValueError
from document_service.domain.model import AccessPolicy, DocumentMetadata, Principal, Relationship
from document_service.domain.value import (
    Action,
    Actor,
    Checksum,
    Direction,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    IdempotencyKey,
    VersionLabel,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Page(Generic[T]):
    """Trang dữ liệu, con trỏ rỗng khi đã tới cuối."""

    items: tuple[T, ...]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class PageRequest:
    """Giới hạn kết quả và con trỏ opaque mang offset hoặc khóa cuối."""

    page_size: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.page_size <= 200:
            raise InvalidValueError("page_size must be between 1 and 200")

    @property
    def position(self) -> int:
        """Vị trí offset hoặc khóa của dòng cuối."""
        if self.cursor is None:
            return 0
        try:
            raw = b64decode(self.cursor, altchars=b"-_", validate=True)
            if not raw.isdigit() or len(raw) > 18:
                raise ValueError
            return int(raw)
        except (ValueError, Base64Error) as error:
            raise InvalidValueError("invalid page cursor") from error

    def window(self, items: Sequence[T], next_position: int) -> Page[T]:
        """Đọc thêm một bản ghi để xác định có trang tiếp theo."""
        cursor = None
        if len(items) > self.page_size:
            cursor = urlsafe_b64encode(str(next_position).encode()).decode()
        return Page(tuple(items[: self.page_size]), cursor)

    def slice(self, items: Sequence[T]) -> Page[T]:
        """Phân trang theo offset trên tập đã sắp xếp."""
        start = self.position
        end = start + self.page_size
        return self.window(items[start : end + 1], end)


@dataclass(frozen=True, slots=True)
class RelatedEdge:
    """Cạnh giữ nguyên hai đầu đã khai báo và chiều nhìn từ phiên bản được hỏi."""

    relationship: Relationship
    direction: Direction


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

    @property
    def offset(self) -> int:
        """Search API dùng offset dạng số."""
        if self.cursor is None:
            return 0
        if not self.cursor.isascii() or not self.cursor.isdigit() or len(self.cursor) > 18:
            raise InvalidValueError("invalid search cursor")
        return int(self.cursor)

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

    @property
    def visible_hits(self) -> int:
        """Số kết quả thực tế trong trang."""
        return len(self.hits)

    def filtered(self, principal: Principal, action: Action = Action.VIEW_METADATA) -> SearchPage:
        """Giữ tổng từ catalog và con trỏ, kể cả khi trang rỗng sau lọc quyền."""
        allowed = tuple(hit for hit in self.hits if hit.access_policy.permits(principal, action))
        return SearchPage(hits=allowed, next_cursor=self.next_cursor, total_hits=self.total_hits)


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
