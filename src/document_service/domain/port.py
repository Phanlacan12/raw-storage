"""Tám port của Document Service, khai báo bằng abstract base class.

Chữ ký lấy từ docs/c4-04b-code-structure.md mục 3, phân cấp theo mục 2.2: mỗi port
là `ABC` + `@abstractmethod`, mọi adapter và fake đều **kế thừa** port tương ứng.
Health check không nằm ở port: adapter khai báo qua `HealthProbe` (mục 10.2), vì chỉ
adapter biết phép thử rẻ và chỉ-đọc cho phụ thuộc của nó.
Các port là async vì mọi hiện thực đều gọi ra ngoài tiến trình; lõi domain vẫn là
code đồng bộ thuần.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from document_service.domain.dto import (
    Decision,
    EntityRef,
    ObjectInfo,
    PutResult,
    SearchPage,
    SearchQuery,
)
from document_service.domain.model import (
    AccessPolicy,
    AuditEvent,
    Collection,
    Document,
    DocumentVersion,
    DomainEvent,
    Principal,
    Relationship,
    UploadIntent,
)
from document_service.domain.value import (
    Action,
    Checksum,
    Direction,
    DocumentId,
    DocumentVersionId,
    IdempotencyKey,
    IntentState,
    RelationType,
    RequestId,
    StorageUri,
)

T = TypeVar("T")


class MetadataCatalogPort(ABC):
    """Đọc và ghi metadata trong catalog (hiện thực: OpenMetadata)."""

    @abstractmethod
    async def ensure_collection(self, collection: Collection) -> EntityRef:
        """Bảo đảm collection đã tồn tại trong catalog."""

    @abstractmethod
    async def register_document(self, document: Document) -> EntityRef:
        """Đăng ký một tài liệu logic."""

    @abstractmethod
    async def register_version(
        self, version: DocumentVersion, metadata: dict[str, Any]
    ) -> EntityRef:
        """Đăng ký một phiên bản nội dung kèm metadata mở rộng."""

    @abstractmethod
    async def patch_controlled_fields(
        self, document_id: DocumentId, version_id: DocumentVersionId, fields: dict[str, Any]
    ) -> None:
        """Cập nhật trường kiểm soát của một phiên bản, chỉ Document Service gọi.

        Nhận cả `document_id` vì adapter cần nó để dựng FQN và đọc thẳng entity.
        Thiếu nó thì chỉ còn đường tra qua Search API, mà index có độ trễ nên duyệt
        một phiên bản vừa tạo sẽ không tìm thấy.
        """

    @abstractmethod
    async def patch_document_fields(self, document_id: DocumentId, fields: dict[str, Any]) -> None:
        """Cập nhật trường kiểm soát ở mức tài liệu, ví dụ current_version_id."""

    @abstractmethod
    async def read_document(self, document_id: DocumentId) -> Document:
        """Đọc tài liệu kèm danh sách phiên bản."""

    @abstractmethod
    async def list_versions(self, document_id: DocumentId) -> list[DocumentVersion]:
        """Danh sách phiên bản của một tài liệu."""

    @abstractmethod
    async def search(self, query: SearchQuery) -> SearchPage:
        """Tìm kiếm theo metadata, có phân trang."""


class RelationshipStorePort(ABC):
    """Lưu và truy vấn quan hệ theo phiên bản (bất biến I6, I7)."""

    @abstractmethod
    async def upsert(self, relationship: Relationship) -> None:
        """Ghi hoặc cập nhật một quan hệ."""

    @abstractmethod
    async def query(
        self,
        version_id: DocumentVersionId,
        direction: Direction = Direction.BOTH,
        relation_type: RelationType | None = None,
    ) -> list[Relationship]:
        """Truy vấn quan hệ theo chiều và loại quan hệ."""

    @abstractmethod
    async def remove(self, relationship: Relationship) -> None:
        """Xoá một quan hệ."""


class ObjectStorePort(ABC):
    """Ghi và đọc object bất biến trên Object Storage tương thích S3."""

    @abstractmethod
    async def put_immutable(
        self, uri: StorageUri, stream: AsyncIterator[bytes], checksum: Checksum
    ) -> PutResult:
        """Ghi object theo khóa bất biến, idempotent khi retry."""

    @abstractmethod
    async def put_overwrite(
        self, uri: StorageUri, payload: bytes, content_type: str = "application/json"
    ) -> PutResult:
        """Ghi object **cho phép ghi đè**, chỉ dành cho dữ liệu điều phối.

        Dùng cho manifest intent và dữ liệu nội bộ của service. Raw file của tài liệu
        **luôn** đi qua `put_immutable` để giữ bất biến I3.
        """

    @abstractmethod
    async def head(self, uri: StorageUri) -> ObjectInfo:
        """Lấy thông tin object, dùng để đối soát."""

    @abstractmethod
    async def presign(self, uri: StorageUri, ttl: timedelta) -> str:
        """Cấp link tải có thời hạn."""

    @abstractmethod
    def open_stream(self, uri: StorageUri) -> AsyncIterator[bytes]:
        """Mở luồng đọc object để proxy qua dịch vụ."""

    @abstractmethod
    async def list_under_prefix(self, prefix: str) -> list[ObjectInfo]:
        """Liệt kê object theo prefix, dùng cho job đối soát."""


class IntentStorePort(ABC):
    """Lưu trạng thái xử lý bền vững (mục 3.5 báo cáo, bất biến I13)."""

    @abstractmethod
    async def create(self, intent: UploadIntent) -> None:
        """Ghi intent mới trước khi ghi object."""

    @abstractmethod
    async def advance(self, request_id: RequestId, state: IntentState) -> None:
        """Cập nhật trạng thái của intent."""

    @abstractmethod
    async def save(self, intent: UploadIntent) -> None:
        """Ghi lại toàn bộ intent, dùng khi tăng retry_count hoặc ghi lỗi."""

    @abstractmethod
    async def find_by_idempotency_key(self, key: IdempotencyKey) -> UploadIntent | None:
        """Tìm intent theo idempotency key để không tạo phiên bản trùng."""

    @abstractmethod
    async def find_by_request_id(self, request_id: RequestId) -> UploadIntent | None:
        """Tìm intent theo request id."""

    @abstractmethod
    async def find_unfinished(self, stale_after: timedelta) -> list[UploadIntent]:
        """Danh sách intent chưa hoàn tất, đầu vào cho job phục hồi."""


class PolicyDecisionPort(ABC):
    """Quyết định quyền cho từng hành động (mục 2.6 báo cáo)."""

    @abstractmethod
    async def decide(self, principal: Principal, action: Action, resource: str) -> Decision:
        """Cho phép hay từ chối một hành động trên một tài nguyên."""

    @abstractmethod
    async def effective_policy(self, document_id: DocumentId) -> AccessPolicy:
        """Policy đang hiệu lực của tài liệu, có thể lấy từ cache."""


class EventPublisherPort(ABC):
    """Phát sự kiện thay đổi cho downstream (mục 2.5 báo cáo)."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        """Ghi sự kiện vào outbox rồi phát đi."""


class AuditPort(ABC):
    """Ghi audit cho mọi thao tác quan trọng (bất biến I12)."""

    @abstractmethod
    async def record(self, event: AuditEvent) -> None:
        """Ghi một bản ghi audit."""

    @abstractmethod
    async def list_for_document(self, document_id: DocumentId) -> list[AuditEvent]:
        """Lịch sử audit của một tài liệu, phục vụ POC-14."""


class DocumentLockPort(ABC):
    """Tuần tự hoá thao tác trên cùng một tài liệu (bất biến I4, I5)."""

    @abstractmethod
    async def with_lock(self, document_id: DocumentId, operation: Callable[[], Awaitable[T]]) -> T:
        """Chạy thao tác trong khóa theo document_id."""
