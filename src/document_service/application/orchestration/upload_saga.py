"""UploadSaga: chuỗi ghi object rồi đăng ký catalog, có thể phục hồi.

Theo mục 3.5 báo cáo và mục 6 của docs/c4-04b-code-structure.md. Hai hệ thống không
có giao dịch chung, nên saga ghi intent bền vững trước, rồi tiến từng bước; mỗi bước
đều idempotent để `IntentRecoveryJob` chạy lại được sau khi service restart.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from document_service.application.orchestration.snapshot import VersionSnapshot
from document_service.domain.dto import PutResult
from document_service.domain.model import DocumentVersion, UploadIntent
from document_service.domain.port import IntentStorePort, MetadataCatalogPort, ObjectStorePort
from document_service.domain.value import IntentState
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)
StreamFactory = Callable[[], AsyncIterator[bytes]]


class UploadSaga:
    """Điều phối ba bước: ghi object, đăng ký catalog, chốt intent."""

    def __init__(
        self,
        objects: ObjectStorePort,
        catalog: MetadataCatalogPort,
        intents: IntentStorePort,
    ) -> None:
        """Nhận ba port mà saga cần."""
        self._objects = objects
        self._catalog = catalog
        self._intents = intents
        self._snapshot = VersionSnapshot()

    async def run(
        self,
        intent: UploadIntent,
        version: DocumentVersion,
        metadata: dict[str, Any],
        stream_factory: StreamFactory,
    ) -> PutResult:
        """Chạy saga từ trạng thái Received cho tới Completed."""
        result = await self._store_object(intent, version, stream_factory)
        await self._register_catalog(intent, version, metadata)
        await self._intents.advance(intent.request_id, IntentState.COMPLETED)
        intent.advance(IntentState.COMPLETED)
        return result

    async def resume(self, intent: UploadIntent, metadata: dict[str, Any]) -> bool:
        """Tiếp tục một intent dở dang sau khi service restart.

        Không có bytes gốc trong tay, nên saga chỉ phục hồi được khi object đã nằm
        trên Object Storage. Nếu object không tồn tại thì intent được đánh Failed để
        vận hành xử lý, thay vì tạo một phiên bản rỗng.
        """
        if not intent.payload:
            await self._fail(intent, "intent is missing the version snapshot")
            return False
        version = self._snapshot.from_payload(intent.payload)
        try:
            info = await self._objects.head(version.storage_uri)
        except Exception as error:  # phụ thuộc ngoài, đã được adapter phân loại
            _LOGGER.warning(
                "cannot read the object while recovering",
                extra={"request_id": str(intent.request_id), "error": str(error)},
            )
            raise
        if info.size_bytes <= 0 and info.etag == "":
            await self._fail(intent, "object does not exist yet, cannot recover")
            return False
        await self._register_catalog(intent, version, metadata)
        await self._intents.advance(intent.request_id, IntentState.COMPLETED)
        intent.advance(IntentState.COMPLETED)
        return True

    async def _store_object(
        self, intent: UploadIntent, version: DocumentVersion, stream_factory: StreamFactory
    ) -> PutResult:
        """Ghi object bất biến và chuyển intent sang ObjectStored."""
        result = await self._objects.put_immutable(
            version.storage_uri, stream_factory(), version.checksum
        )
        await self._intents.advance(intent.request_id, IntentState.OBJECT_STORED)
        intent.advance(IntentState.OBJECT_STORED)
        return result

    async def _register_catalog(
        self, intent: UploadIntent, version: DocumentVersion, metadata: dict[str, Any]
    ) -> None:
        """Đăng ký entity phiên bản và chuyển intent sang CatalogRegistered."""
        await self._catalog.register_version(version, metadata)
        await self._intents.advance(intent.request_id, IntentState.CATALOG_REGISTERED)
        intent.advance(IntentState.CATALOG_REGISTERED)

    async def _fail(self, intent: UploadIntent, reason: str) -> None:
        """Đánh dấu intent thất bại kèm lý do để cảnh báo."""
        intent.last_error = reason
        intent.state = IntentState.FAILED
        await self._intents.save(intent)
        _LOGGER.error(
            "intent cannot be recovered",
            extra={"request_id": str(intent.request_id), "reason": reason},
        )
