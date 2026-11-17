"""Job đối soát và phục hồi (C8, docs/c4-04b mục 7 và luồng 7 ở c4-05).

Ba việc, chạy định kỳ:

1. `IntentRecoveryJob` — đọc lại intent dở dang và tiếp tục saga với **cùng**
   `document_version_id` và `idempotency_key`, nên không mất và không nhân đôi phiên
   bản (bất biến I13, test case POC-18, POC-21).
2. `OrphanObjectScanner` — object đã ghi nhưng chưa đăng ký catalog.
3. `DanglingEntityScanner` — tài liệu có `current_version_id` trỏ tới phiên bản không
   ở trạng thái Approved, tức lệch bất biến I4/I14.

Việc không tự xử lý được thì ghi cảnh báo để vận hành can thiệp, thay vì âm thầm bỏ qua.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta

from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.application.orchestration.snapshot import VersionSnapshot
from document_service.application.orchestration.upload_saga import UploadSaga
from document_service.config import Settings, get_settings
from document_service.domain.errors import DomainError
from document_service.domain.model import UploadIntent
from document_service.domain.port import IntentStorePort, MetadataCatalogPort, ObjectStorePort
from document_service.domain.value import DocumentId, IntentState
from document_service.infrastructure.container import ServiceContainer
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)


@dataclass(slots=True)
class ReconcileReport:
    """Kết quả một lượt đối soát."""

    recovered: int = 0
    failed: int = 0
    orphan_objects: list[str] = field(default_factory=list)
    dangling_documents: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, object]:
        """Dạng dict để log và trả qua API nội bộ."""
        return {
            "recovered": self.recovered,
            "failed": self.failed,
            "orphan_objects": len(self.orphan_objects),
            "dangling_documents": len(self.dangling_documents),
        }


class IntentRecoveryJob:
    """Tiếp tục các intent dở dang sau khi service restart hoặc phụ thuộc lỗi."""

    def __init__(
        self,
        intents: IntentStorePort,
        saga: UploadSaga,
        catalog: MetadataCatalogPort,
        settings: Settings,
    ) -> None:
        """Nhận intent store, saga, catalog và cấu hình ngưỡng retry."""
        self._intents = intents
        self._saga = saga
        self._catalog = catalog
        self._settings = settings
        self._builder = CatalogMetadataBuilder()
        self._snapshot = VersionSnapshot()

    async def run_once(self) -> ReconcileReport:
        """Quét và phục hồi một lượt."""
        report = ReconcileReport()
        stale = timedelta(seconds=self._settings.intent.stale_after_seconds)
        for intent in await self._intents.find_unfinished(stale):
            if intent.retry_count >= self._settings.intent.max_retry_before_failed:
                await self._give_up(intent)
                report.failed += 1
                continue
            if await self._resume(intent):
                report.recovered += 1
            else:
                report.failed += 1
        return report

    async def _resume(self, intent: UploadIntent) -> bool:
        """Thử hoàn tất một intent, trả False nếu chưa xử lý được."""
        try:
            document = await self._catalog.read_document(intent.document_id)
            version = self._snapshot.from_payload(intent.payload)
            metadata = self._builder.build(document, version)
            return await self._saga.resume(intent, metadata)
        except DomainError as error:
            intent.register_retry(str(error))
            await self._intents.save(intent)
            _LOGGER.warning(
                "phục hồi intent thất bại, sẽ thử lại",
                extra={"request_id": str(intent.request_id), "error": str(error)},
            )
            return False

    async def _give_up(self, intent: UploadIntent) -> None:
        """Đánh dấu Failed và cảnh báo khi vượt ngưỡng retry."""
        intent.state = IntentState.FAILED
        intent.last_error = f"vượt ngưỡng retry {intent.retry_count}"
        await self._intents.save(intent)
        _LOGGER.error(
            "intent vượt ngưỡng retry, cần can thiệp thủ công",
            extra={
                "request_id": str(intent.request_id),
                "version_id": str(intent.version_id),
                "retry_count": intent.retry_count,
            },
        )


class OrphanObjectScanner:
    """Tìm object đã ghi mà chưa có entity tương ứng trong catalog."""

    def __init__(
        self, objects: ObjectStorePort, catalog: MetadataCatalogPort, prefix: str = "objects"
    ) -> None:
        """Nhận object store, catalog và prefix cần quét."""
        self._objects = objects
        self._catalog = catalog
        self._prefix = prefix

    async def scan(self) -> list[str]:
        """Danh sách object key chưa đăng ký."""
        orphans: list[str] = []
        for info in await self._objects.list_under_prefix(self._prefix):
            document_id = self._document_of(info.key)
            if document_id is None:
                continue
            try:
                versions = await self._catalog.list_versions(document_id)
            except DomainError:
                orphans.append(info.key)
                continue
            if all(str(version.version_id) not in info.key for version in versions):
                orphans.append(info.key)
        return orphans

    def _document_of(self, key: str) -> DocumentId | None:
        """Đọc document_id từ object key theo quy ước ở mục 4.6."""
        parts = key.split("/")
        if len(parts) < 3:
            return None
        try:
            return DocumentId(parts[1])
        except DomainError:
            return None


class DanglingEntityScanner:
    """Tìm tài liệu có bản hiện hành không ở trạng thái Approved."""

    def __init__(self, catalog: MetadataCatalogPort) -> None:
        """Nhận catalog."""
        self._catalog = catalog

    async def scan(self, document_ids: list[DocumentId]) -> list[str]:
        """Danh sách tài liệu bị lệch trạng thái."""
        dangling: list[str] = []
        for document_id in document_ids:
            try:
                document = await self._catalog.read_document(document_id)
            except DomainError:
                dangling.append(str(document_id))
                continue
            current = document.current_version_id
            if current is None:
                continue
            match = [item for item in document.versions if item.version_id == current]
            if not match or not match[0].is_approved:
                dangling.append(str(document_id))
        return dangling


class ReconcileRunner:
    """Điều phối một lượt đối soát đầy đủ, dùng cho CLI và cho job định kỳ."""

    def __init__(self, container: ServiceContainer | None = None) -> None:
        """Dựng runner từ container."""
        self._container = container or ServiceContainer()
        ports = self._container.ports
        self._settings = self._container.settings
        self._recovery = IntentRecoveryJob(
            ports.intents,
            UploadSaga(ports.objects, ports.catalog, ports.intents),
            ports.catalog,
            self._settings,
        )
        self._orphans = OrphanObjectScanner(
            ports.objects, ports.catalog, self._settings.storage.object_prefix
        )
        self._dangling = DanglingEntityScanner(ports.catalog)

    async def run_once(self, document_ids: list[DocumentId] | None = None) -> ReconcileReport:
        """Chạy phục hồi intent, quét object mồ côi và entity lệch trạng thái."""
        report = await self._recovery.run_once()
        report.orphan_objects = await self._orphans.scan()
        report.dangling_documents = await self._dangling.scan(document_ids or [])
        _LOGGER.info("đối soát xong", extra=report.as_payload())
        return report

    async def run_forever(self) -> None:
        """Chạy lặp theo chu kỳ trong cấu hình."""
        interval = self._settings.intent.reconcile_interval_seconds
        while True:
            await self.run_once()
            await asyncio.sleep(interval)


def main() -> None:
    """Điểm vào CLI: chạy một lượt đối soát rồi in kết quả."""
    settings = get_settings()
    runner = ReconcileRunner()
    report = asyncio.run(runner.run_once())
    _LOGGER.info(
        "kết quả đối soát",
        extra={"profile": str(settings.app.profile), **report.as_payload()},
    )


if __name__ == "__main__":
    main()
