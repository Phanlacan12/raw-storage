"""Adapter in-memory cho profile `fake`: chạy service không cần hạ tầng.

Mọi lớp ở đây **kế thừa** đúng port ở `domain/port.py`, nên bộ contract test chạy
được trên cả fake và adapter thật. Dùng cho phát triển cục bộ và cho test; không
dùng khi chạy thật vì dữ liệu mất khi tiến trình thoát.
"""

from __future__ import annotations

import asyncio
import copy
from datetime import timedelta
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.domain.dto import (
    Decision,
    EntityRef,
    ObjectInfo,
    PutResult,
    SearchHit,
    SearchPage,
    SearchQuery,
)
from document_service.domain.errors import ConcurrencyConflictError, DocumentNotFoundError
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
from document_service.domain.port import (
    AuditPort,
    DocumentLockPort,
    EventPublisherPort,
    IntentStorePort,
    MetadataCatalogPort,
    ObjectStorePort,
    PolicyDecisionPort,
    RelationshipStorePort,
)
from document_service.domain.value import (
    Action,
    Checksum,
    Direction,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    IdempotencyKey,
    IntentState,
    RelationType,
    RequestId,
    StorageUri,
)
from document_service.infrastructure.health import DependencyKind, HealthProbeMixin, HealthResult
from document_service.utils.clock import utc_now
from document_service.utils.hashing import digest_of

T = TypeVar("T")


class InMemoryAdapter(HealthProbeMixin):
    """Base của adapter in-memory: khai báo health như adapter thật.

    Giữ cùng hợp đồng `HealthProbe` với adapter thật, nhờ đó registry health và bộ
    contract test chạy được trên cả hai hiện thực.
    """

    def __init__(self, name: str, kind: DependencyKind, cache_ttl_seconds: float = 0.0) -> None:
        """Nhận tên phụ thuộc giả lập và nhóm phụ thuộc."""
        super().__init__(cache_ttl_seconds)
        self._name = name
        self._kind = kind
        self.available = True

    @property
    def dependency_name(self) -> str:
        """Tên phụ thuộc giả lập."""
        return self._name

    @property
    def dependency_kind(self) -> DependencyKind:
        """Nhóm chức năng mà phụ thuộc này phục vụ."""
        return self._kind

    async def _probe_dependency(self) -> HealthResult:
        """UP khi cờ `available` còn bật, DOWN khi test mô phỏng sự cố."""
        if not self.available:
            return self.health_down(f"fake {self._name} is DOWN")
        return self.health_up("in-memory")


class InMemoryCatalog(MetadataCatalogPort, InMemoryAdapter):
    """Catalog giả lập, giữ Document và DocumentVersion trong bộ nhớ."""

    def __init__(self) -> None:
        """Khởi tạo kho rỗng."""
        InMemoryAdapter.__init__(self, "catalog", DependencyKind.REQUIRED_FOR_READ)
        self._documents: dict[str, Document] = {}
        self._collections: dict[str, Collection] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._builder = CatalogMetadataBuilder()
        self.registered_calls = 0

    async def ensure_collection(self, collection: Collection) -> EntityRef:
        """Ghi nhận collection."""
        self._collections[collection.collection_id] = collection
        return EntityRef(entity_id=collection.collection_id, entity_type="directory")

    async def register_document(self, document: Document) -> EntityRef:
        """Upsert tài liệu, **giữ nguyên** các phiên bản đã đăng ký.

        PUT một Directory trên catalog thật không xoá các File entity con, nên fake
        cũng không được xoá: nếu ghi đè, mỗi lần đồng bộ lại sẽ làm mất lịch sử phiên
        bản và che một lỗi chỉ xuất hiện ở bản thật.
        """
        key = str(document.document_id)
        existing = self._documents.get(key)
        if existing is None:
            self._documents[key] = document
        else:
            existing.metadata = document.metadata
            existing.access_policy = document.access_policy
            existing.retention_policy = document.retention_policy
        return EntityRef(entity_id=key, entity_type="directory")

    async def register_version(
        self, version: DocumentVersion, metadata: dict[str, Any]
    ) -> EntityRef:
        """Ghi nhận phiên bản, idempotent theo version_id."""
        self.registered_calls += 1
        document = self._require(version.document_id)
        if all(item.version_id != version.version_id for item in document.versions):
            document.versions.append(version)
        self._metadata[str(version.version_id)] = dict(metadata)
        return EntityRef(entity_id=str(version.version_id), entity_type="file")

    async def patch_controlled_fields(
        self, version_id: DocumentVersionId, fields: dict[str, Any]
    ) -> None:
        """Cập nhật metadata kiểm soát của một phiên bản và entity đã lưu."""
        self._metadata.setdefault(str(version_id), {}).update(fields)
        if "status" in fields:
            self._apply_status(version_id, str(fields["status"]))

    async def patch_document_fields(self, document_id: DocumentId, fields: dict[str, Any]) -> None:
        """Cập nhật metadata kiểm soát ở mức tài liệu và entity đã lưu."""
        self._metadata.setdefault(str(document_id), {}).update(fields)
        document = self._documents.get(str(document_id))
        if document is None:
            return
        if "current_version_id" in fields:
            raw = str(fields["current_version_id"])
            document.current_version_id = DocumentVersionId(raw) if raw else None
        if "classification" in fields:
            document.access_policy = AccessPolicy(
                classification=str(fields["classification"]),
                allowed_groups=document.access_policy.allowed_groups,
                allowed_principals=document.access_policy.allowed_principals,
                require_proxy_download=document.access_policy.require_proxy_download,
            )

    async def read_document(self, document_id: DocumentId) -> Document:
        """Đọc tài liệu dưới dạng **bản sao**, như một catalog ở xa.

        Trả bản sao để lớp application không vô tình sửa trực tiếp dữ liệu đã lưu —
        nếu trả nguyên instance, fake sẽ che mất những lỗi chỉ xuất hiện với catalog
        thật.
        """
        return copy.deepcopy(self._require(document_id))

    async def list_versions(self, document_id: DocumentId) -> list[DocumentVersion]:
        """Danh sách phiên bản của tài liệu."""
        return copy.deepcopy(list(self._require(document_id).versions))

    def _apply_status(self, version_id: DocumentVersionId, status: str) -> None:
        """Áp trạng thái mới lên phiên bản đã lưu."""
        for document in self._documents.values():
            for version in document.versions:
                if version.version_id == version_id:
                    version.status = DocumentStatus(status)
                    return

    async def search(self, query: SearchQuery) -> SearchPage:
        """Lọc theo tên và các điều kiện metadata cơ bản."""
        hits: list[SearchHit] = []
        for document in self._documents.values():
            for version in document.versions:
                if self._matches(document, version, query):
                    hits.append(self._to_hit(document, version))
        return SearchPage(hits=tuple(hits), total_hits=len(hits))

    def _matches(self, document: Document, version: DocumentVersion, query: SearchQuery) -> bool:
        """So khớp một phiên bản với truy vấn, dựa trên metadata **đã đăng ký**.

        Catalog thật index đúng những gì được ghi vào, nên fake cũng phải tra theo
        metadata đã nhận ở `register_version` và `patch_controlled_fields`, không suy
        lại từ entity.
        """
        metadata = self._indexed_metadata(document, version)
        for item in query.filters:
            if str(metadata.get(item.field_name, "")) != item.value:
                return False
        if query.text and query.text.lower() not in str(metadata.get("title", "")).lower():
            return False
        return True

    def _indexed_metadata(self, document: Document, version: DocumentVersion) -> dict[str, Any]:
        """Metadata đã đăng ký của một phiên bản, bù phần thiếu từ entity."""
        base = self._builder.build(document, version)
        base.update(self._metadata.get(str(version.version_id), {}))
        return base

    def _to_hit(self, document: Document, version: DocumentVersion) -> SearchHit:
        """Chuyển phiên bản thành một kết quả tìm kiếm."""
        indexed = self._indexed_metadata(document, version)
        return SearchHit(
            version_id=version.version_id,
            document_id=document.document_id,
            status=DocumentStatus(str(indexed.get("status", version.status))),
            metadata=document.metadata,
            label=version.label,
            access_policy=document.access_policy,
        )

    def _require(self, document_id: DocumentId) -> Document:
        """Lấy tài liệu, lỗi nếu chưa đăng ký."""
        document = self._documents.get(str(document_id))
        if document is None:
            raise DocumentNotFoundError(f"document {document_id} is not registered")
        return document


class InMemoryObjectStore(ObjectStorePort, InMemoryAdapter):
    """Object store giả lập, giữ bytes trong bộ nhớ."""

    def __init__(self) -> None:
        """Khởi tạo kho object rỗng."""
        InMemoryAdapter.__init__(self, "object_store", DependencyKind.REQUIRED_FOR_DOWNLOAD)
        self._objects: dict[str, bytes] = {}

    async def put_immutable(
        self, uri: StorageUri, stream: AsyncIterator[bytes], checksum: Checksum
    ) -> PutResult:
        """Ghi object nếu chưa có, bỏ qua nếu đã tồn tại."""
        self._assert_available()
        key = str(uri)
        if key in self._objects:
            data = self._objects[key]
            return PutResult(
                etag=f"etag-{len(data)}",
                size_bytes=len(data),
                checksum=checksum,
                already_existed=True,
            )
        chunks = [chunk async for chunk in stream]
        data = b"".join(chunks)
        self._objects[key] = data
        return PutResult(etag=f"etag-{len(data)}", size_bytes=len(data), checksum=checksum)

    async def put_overwrite(
        self, uri: StorageUri, payload: bytes, content_type: str = "application/json"
    ) -> PutResult:
        """Ghi object cho phép ghi đè, dùng cho manifest điều phối."""
        del content_type
        self._assert_available()
        self._objects[str(uri)] = payload
        return PutResult(
            etag=f"etag-{len(payload)}",
            size_bytes=len(payload),
            checksum=Checksum(algorithm="sha256", hex_digest=digest_of(payload)),
        )

    async def head(self, uri: StorageUri) -> ObjectInfo:
        """Thông tin object, size 0 nếu chưa tồn tại."""
        self._assert_available()
        data = self._objects.get(str(uri))
        if data is None:
            return ObjectInfo(key=uri.key, size_bytes=0)
        return ObjectInfo(key=uri.key, size_bytes=len(data), etag=f"etag-{len(data)}")

    async def presign(self, uri: StorageUri, ttl: timedelta) -> str:
        """Link tải giả lập có tham số thời hạn."""
        self._assert_available()
        return f"memory://{uri.bucket}/{uri.key}?ttl={int(ttl.total_seconds())}"

    def open_stream(self, uri: StorageUri) -> AsyncIterator[bytes]:
        """Luồng đọc object."""
        data = self._objects.get(str(uri), b"")

        async def _iterator() -> AsyncIterator[bytes]:
            yield data

        return _iterator()

    async def list_under_prefix(self, prefix: str) -> list[ObjectInfo]:
        """Liệt kê object theo prefix, trả **object key** như adapter S3 thật.

        Fake phải trả cùng dạng key với bản thật, nếu không job đối soát sẽ chạy
        đúng trong test mà sai khi gặp Object Storage thực.
        """
        items: list[ObjectInfo] = []
        for uri, value in self._objects.items():
            key = StorageUri.parse(uri).key
            if key.startswith(prefix):
                items.append(ObjectInfo(key=key, size_bytes=len(value)))
        return items

    def _assert_available(self) -> None:
        """Mô phỏng phụ thuộc sập, phục vụ test chế độ suy giảm."""
        if not self.available:
            raise ConnectionError("fake object store is DOWN")


class InMemoryIntentStore(IntentStorePort, InMemoryAdapter):
    """Intent store giả lập."""

    def __init__(self) -> None:
        """Khởi tạo kho intent rỗng."""
        InMemoryAdapter.__init__(self, "intent_store", DependencyKind.REQUIRED_FOR_WRITE)
        self._by_request: dict[str, UploadIntent] = {}
        self._by_key: dict[str, str] = {}

    async def create(self, intent: UploadIntent) -> None:
        """Ghi intent mới, từ chối nếu idempotency key đã dùng.

        Fake phải giữ **cùng ràng buộc** với hiện thực sqlite, nếu không profile fake
        sẽ cho qua những lượt gọi mà bản thật từ chối (bất biến I13).
        """
        if str(intent.idempotency_key) in self._by_key:
            raise ConcurrencyConflictError(
                f"idempotency_key {intent.idempotency_key} is already used"
            )
        self._by_request[str(intent.request_id)] = intent
        self._by_key[str(intent.idempotency_key)] = str(intent.request_id)

    async def advance(self, request_id: RequestId, state: IntentState) -> None:
        """Cập nhật trạng thái intent."""
        intent = self._by_request.get(str(request_id))
        if intent is not None and intent.state is not state:
            intent.advance(state)

    async def save(self, intent: UploadIntent) -> None:
        """Ghi lại toàn bộ intent."""
        intent.updated_at = utc_now()
        self._by_request[str(intent.request_id)] = intent
        self._by_key[str(intent.idempotency_key)] = str(intent.request_id)

    async def find_by_idempotency_key(self, key: IdempotencyKey) -> UploadIntent | None:
        """Tra intent theo idempotency key."""
        request_id = self._by_key.get(str(key))
        return self._by_request.get(request_id) if request_id else None

    async def find_by_request_id(self, request_id: RequestId) -> UploadIntent | None:
        """Tra intent theo request id."""
        return self._by_request.get(str(request_id))

    async def find_unfinished(self, stale_after: timedelta) -> list[UploadIntent]:
        """Intent chưa kết thúc và đã đủ cũ."""
        threshold = utc_now() - stale_after
        return [
            intent
            for intent in self._by_request.values()
            if not intent.state.is_terminal and intent.updated_at <= threshold
        ]


class InMemoryRelationshipStore(RelationshipStorePort, InMemoryAdapter):
    """Relationship store giả lập, truy vấn được hai chiều."""

    def __init__(self) -> None:
        """Khởi tạo danh sách quan hệ rỗng."""
        InMemoryAdapter.__init__(self, "relationship_store", DependencyKind.REQUIRED_FOR_READ)
        self._items: list[Relationship] = []

    async def upsert(self, relationship: Relationship) -> None:
        """Ghi quan hệ, bỏ qua nếu đã có đúng cạnh đó."""
        if relationship not in self._items:
            self._items.append(relationship)

    async def query(
        self,
        version_id: DocumentVersionId,
        direction: Direction = Direction.BOTH,
        relation_type: RelationType | None = None,
    ) -> list[Relationship]:
        """Truy vấn quan hệ theo chiều và loại (bất biến I7)."""
        result: list[Relationship] = []
        for item in self._items:
            if relation_type is not None and item.relation_type != relation_type:
                continue
            if direction in (Direction.OUTGOING, Direction.BOTH):
                if item.source_version_id == version_id:
                    result.append(item)
            if direction in (Direction.INCOMING, Direction.BOTH):
                if item.target_version_id == version_id:
                    result.append(item.reversed_direction())
        return result

    async def remove(self, relationship: Relationship) -> None:
        """Xoá quan hệ nếu có."""
        self._items = [item for item in self._items if item != relationship]


class AllowAllPolicyDecision(PolicyDecisionPort):
    """Quyết định quyền cho profile fake: cho phép, trừ khi bị cấu hình chặn."""

    def __init__(self) -> None:
        """Khởi tạo không có hành động nào bị chặn."""
        self.denied_actions: set[Action] = set()
        self.policies: dict[str, AccessPolicy] = {}

    async def decide(self, principal: Principal, action: Action, resource: str) -> Decision:
        """Cho phép nếu hành động không nằm trong danh sách chặn."""
        if action in self.denied_actions and not principal.is_admin:
            return Decision.deny(f"action {action} is blocked in the fake profile")
        return Decision.allow()

    async def effective_policy(self, document_id: DocumentId) -> AccessPolicy:
        """Policy đang hiệu lực, mặc định là nội bộ."""
        return self.policies.get(str(document_id), AccessPolicy(classification="internal"))


class InMemoryEventPublisher(EventPublisherPort, InMemoryAdapter):
    """Outbox giả lập, giữ sự kiện trong bộ nhớ để test kiểm tra."""

    def __init__(self) -> None:
        """Khởi tạo danh sách sự kiện rỗng."""
        InMemoryAdapter.__init__(self, "event_publisher", DependencyKind.OPTIONAL)
        self.events: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        """Ghi sự kiện vào danh sách."""
        self.events.append(event)


class InMemoryAuditLog(AuditPort):
    """Audit log giả lập."""

    def __init__(self) -> None:
        """Khởi tạo audit rỗng."""
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> None:
        """Ghi một bản ghi audit."""
        self.events.append(event)

    async def list_for_document(self, document_id: DocumentId) -> list[AuditEvent]:
        """Audit của tài liệu, kể cả thao tác trên các phiên bản của nó."""
        needle = str(document_id)
        return [
            event
            for event in self.events
            if event.document_id == needle or needle in event.target_id
        ]


class InMemoryDocumentLock(DocumentLockPort, InMemoryAdapter):
    """Khóa trong tiến trình, đủ cho một instance và cho test.

    Chạy nhiều instance cần khóa phân tán; đó là việc còn lại đã nêu trong plan.
    """

    def __init__(self) -> None:
        """Khởi tạo bảng khóa theo document_id."""
        InMemoryAdapter.__init__(self, "document_lock", DependencyKind.REQUIRED_FOR_WRITE)
        self._locks: dict[str, asyncio.Lock] = {}

    async def with_lock(self, document_id: DocumentId, operation: Callable[[], Awaitable[T]]) -> T:
        """Chạy thao tác trong khóa của tài liệu."""
        lock = self._locks.setdefault(str(document_id), asyncio.Lock())
        async with lock:
            return await operation()
