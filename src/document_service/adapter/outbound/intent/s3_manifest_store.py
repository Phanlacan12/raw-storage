"""S3ManifestIntentStore — biến thể A của quyết định Q2.

Lưu intent dưới dạng manifest JSON trên Object Storage, không cần database riêng. Đây
là phương án mà mục 3.5 báo cáo muốn thử trước, và cũng là phương án plan ghi rõ phải
**kiểm chứng race condition, liệt kê/đối soát và khả năng phục hồi sau restart**.

**Giới hạn đã biết, không che:** API S3 chuẩn không có phép ghi có điều kiện dùng được
trên mọi sản phẩm tương thích, nên hai request đồng thời cùng `idempotency_key` đều có
thể ghi index và lượt sau ghi đè lượt trước. Store này vì vậy **không** bảo đảm tính
duy nhất ở mức hạ tầng như `SqliteRegistryIntentStore` (UNIQUE). Bộ
`IntentStorePortContractTest` phơi đúng khác biệt đó ra để chốt Q2 bằng số liệu.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.domain.model import UploadIntent
from document_service.domain.port import IntentStorePort, ObjectStorePort
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentVersionId,
    IdempotencyKey,
    IntentState,
    RequestId,
    StorageUri,
)
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.utils.clock import utc_now
from document_service.utils.jsonx import JsonCodec


class S3ManifestIntentStore(IntentStorePort, OutboundAdapter):
    """Intent store dùng manifest trên Object Storage."""

    def __init__(
        self,
        objects: ObjectStorePort,
        bucket: str,
        executor: ResilientCallExecutor,
        prefix: str = "intents",
    ) -> None:
        """Nhận object store, bucket, executor và prefix chứa manifest."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_WRITE)
        self._objects = objects
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._codec = JsonCodec()

    async def create(self, intent: UploadIntent) -> None:
        """Ghi manifest và index theo idempotency key."""
        await self._write(intent)
        await self._write_index(intent)

    async def advance(self, request_id: RequestId, state: IntentState) -> None:
        """Đọc lại manifest, cập nhật trạng thái rồi ghi lại."""
        intent = await self.find_by_request_id(request_id)
        if intent is None:
            return
        intent.advance(state)
        await self._write(intent)

    async def save(self, intent: UploadIntent) -> None:
        """Ghi lại toàn bộ manifest."""
        intent.updated_at = utc_now()
        await self._write(intent)

    async def find_by_idempotency_key(self, key: IdempotencyKey) -> UploadIntent | None:
        """Đọc index rồi lấy manifest tương ứng."""
        payload = await self._read(self._index_uri(key))
        if payload is None:
            return None
        request_id = str(payload.get("request_id", ""))
        if not request_id:
            return None
        return await self.find_by_request_id(RequestId(request_id))

    async def find_by_request_id(self, request_id: RequestId) -> UploadIntent | None:
        """Đọc manifest theo request id."""
        payload = await self._read(self._manifest_uri(request_id))
        return self._from_payload(payload) if payload else None

    async def find_unfinished(self, stale_after: timedelta) -> list[UploadIntent]:
        """Liệt kê manifest rồi lọc những intent chưa kết thúc và đủ cũ.

        Đây là chỗ tốn kém nhất của biến thể này: phải `list_objects` toàn bộ prefix,
        chi phí tăng theo số intent đã từng ghi, kể cả intent đã hoàn tất.
        """
        threshold = utc_now() - stale_after
        found: list[UploadIntent] = []
        for info in await self._objects.list_under_prefix(f"{self._prefix}/manifests/"):
            payload = await self._read(StorageUri(bucket=self._bucket, key=info.key))
            if payload is None:
                continue
            intent = self._from_payload(payload)
            if not intent.state.is_terminal and intent.updated_at <= threshold:
                found.append(intent)
        return sorted(found, key=lambda item: item.updated_at)

    async def _probe_dependency(self) -> HealthResult:
        """Đếm manifest, thao tác chỉ đọc trên Object Storage."""
        items = await self._objects.list_under_prefix(f"{self._prefix}/manifests/")
        return self.health_up(f"manifests={len(items)}")

    def _manifest_uri(self, request_id: RequestId) -> StorageUri:
        """Vị trí manifest của một request."""
        return StorageUri(
            bucket=self._bucket, key=f"{self._prefix}/manifests/{request_id}.json"
        )

    def _index_uri(self, key: IdempotencyKey) -> StorageUri:
        """Vị trí index theo idempotency key."""
        return StorageUri(bucket=self._bucket, key=f"{self._prefix}/by-key/{key}.json")

    async def _write(self, intent: UploadIntent) -> None:
        """Ghi manifest, cho phép ghi đè vì trạng thái thay đổi theo thời gian."""
        await self._put(self._manifest_uri(intent.request_id), self._to_payload(intent))

    async def _write_index(self, intent: UploadIntent) -> None:
        """Ghi index idempotency key → request id."""
        await self._put(
            self._index_uri(intent.idempotency_key),
            {"request_id": str(intent.request_id)},
        )

    async def _put(self, uri: StorageUri, payload: dict[str, Any]) -> None:
        """Ghi một object JSON, ghi đè nếu đã tồn tại."""
        body = self._codec.dumpb(payload)
        await self._call(lambda: self._objects.put_overwrite(uri, body))

    async def _read(self, uri: StorageUri) -> dict[str, Any] | None:
        """Đọc một object JSON, None nếu chưa tồn tại."""
        info = await self._objects.head(uri)
        if info.size_bytes == 0 and not info.etag:
            return None
        chunks = [chunk async for chunk in self._objects.open_stream(uri)]
        raw = b"".join(chunks)
        if not raw:
            return None
        return self._codec.loads(raw)

    def _to_payload(self, intent: UploadIntent) -> dict[str, Any]:
        """Serialize intent thành manifest."""
        return {
            "request_id": str(intent.request_id),
            "idempotency_key": str(intent.idempotency_key),
            "document_id": str(intent.document_id),
            "version_id": str(intent.version_id),
            "expected_checksum": str(intent.expected_checksum),
            "state": str(intent.state),
            "retry_count": intent.retry_count,
            "created_at": intent.created_at.isoformat(),
            "updated_at": intent.updated_at.isoformat(),
            "last_error": intent.last_error,
            "payload": dict(intent.payload),
        }

    def _from_payload(self, payload: dict[str, Any]) -> UploadIntent:
        """Dựng lại intent từ manifest."""
        raw_payload = payload.get("payload", {}) or {}
        return UploadIntent(
            request_id=RequestId(str(payload["request_id"])),
            idempotency_key=IdempotencyKey(str(payload["idempotency_key"])),
            document_id=DocumentId(str(payload["document_id"])),
            version_id=DocumentVersionId(str(payload["version_id"])),
            expected_checksum=Checksum.parse(str(payload["expected_checksum"])),
            state=IntentState(str(payload.get("state", IntentState.RECEIVED))),
            retry_count=int(payload.get("retry_count", 0) or 0),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            updated_at=datetime.fromisoformat(str(payload["updated_at"])),
            last_error=str(payload.get("last_error", "")),
            payload={str(key): str(value) for key, value in raw_payload.items()},
        )
