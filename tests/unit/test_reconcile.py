"""Test job đối soát và phục hồi (POC-08, POC-18, POC-21).

Kịch bản chính: object đã ghi nhưng đăng ký catalog lỗi → intent ở RetryPending →
job phục hồi hoàn tất được **mà không nhân đôi phiên bản**.
"""

from __future__ import annotations

from typing import Any

import pytest

from document_service.adapter.outbound.fake.in_memory import (
    InMemoryCatalog,
    InMemoryIntentStore,
    InMemoryObjectStore,
)
from document_service.application.orchestration.snapshot import VersionSnapshot
from document_service.application.orchestration.upload_saga import UploadSaga
from document_service.config import Settings
from document_service.domain.errors import DependencyUnavailableError
from document_service.domain.model import Document, DocumentMetadata, DocumentVersion, UploadIntent
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentVersionId,
    IdempotencyKey,
    IntentState,
    RequestId,
    StorageUri,
    VersionLabel,
)
from document_service.worker.reconcile import (  # noqa: I001
    DanglingEntityScanner,
    IntentRecoveryJob,
    OrphanObjectScanner,
)

CHECKSUM = Checksum.parse("sha256:" + "e" * 64)
DOCUMENT_ID = DocumentId("DOC-1")
VERSION_ID = DocumentVersionId("VER-1")


class FailingCatalog(InMemoryCatalog):
    """Catalog giả lập lỗi đúng N lần đầu khi đăng ký phiên bản."""

    def __init__(self, failures: int) -> None:
        """Nhận số lần lỗi trước khi hoạt động bình thường."""
        super().__init__()
        self._remaining = failures

    async def register_version(self, version: DocumentVersion, metadata: dict[str, Any]) -> Any:
        """Lỗi phụ thuộc cho tới khi hết số lần đã định."""
        if self._remaining > 0:
            self._remaining -= 1
            raise DependencyUnavailableError("catalog", "đăng ký thất bại")
        return await super().register_version(version, metadata)


def _version() -> DocumentVersion:
    """Phiên bản mẫu."""
    return DocumentVersion(
        version_id=VERSION_ID,
        document_id=DOCUMENT_ID,
        label=VersionLabel("1.0"),
        checksum=CHECKSUM,
        storage_uri=StorageUri.for_version("test-bucket", DOCUMENT_ID, VERSION_ID),
        original_file_name="srs.pdf",
        content_format="application/pdf",
        size_bytes=4,
    )


def _intent(version: DocumentVersion) -> UploadIntent:
    """Intent mẫu kèm snapshot phiên bản."""
    return UploadIntent(
        request_id=RequestId("REQ-1"),
        idempotency_key=IdempotencyKey("idem-key-0001"),
        document_id=DOCUMENT_ID,
        version_id=version.version_id,
        expected_checksum=CHECKSUM,
        payload=VersionSnapshot().to_payload(version),
    )


def _stream(payload: bytes) -> Any:
    """Factory luồng dữ liệu."""

    def factory() -> Any:
        async def iterator() -> Any:
            yield payload

        return iterator()

    return factory


@pytest.fixture
def recovery_settings(settings: Settings) -> Settings:
    """Cấu hình đối soát nhìn thấy cả intent vừa cập nhật."""
    settings.intent.stale_after_seconds = -1.0
    return settings


class TestIntentRecovery:
    """Phục hồi intent dở dang."""

    async def test_recovers_after_catalog_failure(self, recovery_settings: Settings) -> None:
        """POC-18: object đã ghi, catalog lỗi, job phục hồi hoàn tất được."""
        catalog = FailingCatalog(failures=1)
        objects = InMemoryObjectStore()
        intents = InMemoryIntentStore()
        document = Document(
            document_id=DOCUMENT_ID,
            metadata=DocumentMetadata(title="SRS", document_type="SRS"),
        )
        await catalog.register_document(document)
        version = _version()
        intent = _intent(version)
        await intents.create(intent)
        saga = UploadSaga(objects, catalog, intents)
        with pytest.raises(DependencyUnavailableError):
            await saga.run(intent, version, {"document_id": "DOC-1"}, _stream(b"data"))
        intent.register_retry("catalog 503")
        await intents.save(intent)
        assert intent.state is IntentState.RETRY_PENDING

        job = IntentRecoveryJob(intents, saga, catalog, recovery_settings)
        report = await job.run_once()
        assert report.recovered == 1
        recovered = await intents.find_by_request_id(intent.request_id)
        assert recovered is not None
        assert recovered.state is IntentState.COMPLETED
        versions = await catalog.list_versions(DOCUMENT_ID)
        assert len(versions) == 1

    async def test_marks_failed_after_retry_budget(self, recovery_settings: Settings) -> None:
        """Vượt ngưỡng retry thì intent chuyển Failed để vận hành xử lý."""
        catalog = InMemoryCatalog()
        objects = InMemoryObjectStore()
        intents = InMemoryIntentStore()
        version = _version()
        intent = _intent(version)
        intent.retry_count = recovery_settings.intent.max_retry_before_failed
        intent.state = IntentState.RETRY_PENDING
        await intents.create(intent)
        job = IntentRecoveryJob(
            intents, UploadSaga(objects, catalog, intents), catalog, recovery_settings
        )
        report = await job.run_once()
        assert report.failed == 1
        stored = await intents.find_by_request_id(intent.request_id)
        assert stored is not None
        assert stored.state is IntentState.FAILED

    async def test_resume_fails_when_object_missing(self, recovery_settings: Settings) -> None:
        """Không có object thì không tạo phiên bản rỗng, intent bị đánh Failed."""
        catalog = InMemoryCatalog()
        objects = InMemoryObjectStore()
        intents = InMemoryIntentStore()
        document = Document(document_id=DOCUMENT_ID)
        await catalog.register_document(document)
        version = _version()
        intent = _intent(version)
        await intents.create(intent)
        saga = UploadSaga(objects, catalog, intents)
        job = IntentRecoveryJob(intents, saga, catalog, recovery_settings)
        report = await job.run_once()
        assert report.failed == 1
        stored = await intents.find_by_request_id(intent.request_id)
        assert stored is not None
        assert stored.state is IntentState.FAILED
        assert "không thể phục hồi" in stored.last_error


class TestScanners:
    """Quét object mồ côi và entity lệch trạng thái."""

    async def test_orphan_object_detected(self) -> None:
        """Object đã ghi mà chưa đăng ký bị phát hiện."""
        catalog = InMemoryCatalog()
        objects = InMemoryObjectStore()
        await catalog.register_document(Document(document_id=DOCUMENT_ID))
        version = _version()
        await objects.put_immutable(version.storage_uri, _stream(b"x")(), CHECKSUM)
        orphans = await OrphanObjectScanner(objects, catalog).scan()
        assert any(str(VERSION_ID) in key for key in orphans)

    async def test_registered_object_is_not_orphan(self) -> None:
        """Object đã có entity thì không bị coi là mồ côi."""
        catalog = InMemoryCatalog()
        objects = InMemoryObjectStore()
        document = Document(document_id=DOCUMENT_ID)
        await catalog.register_document(document)
        version = _version()
        await objects.put_immutable(version.storage_uri, _stream(b"x")(), CHECKSUM)
        await catalog.register_version(version, {"document_id": "DOC-1"})
        orphans = await OrphanObjectScanner(objects, catalog).scan()
        assert orphans == []

    async def test_dangling_current_version_detected(self) -> None:
        """current_version_id trỏ tới bản không Approved là lệch bất biến I4/I14."""
        catalog = InMemoryCatalog()
        document = Document(document_id=DOCUMENT_ID)
        version = _version()
        document.versions.append(version)
        document.current_version_id = version.version_id
        await catalog.register_document(document)
        dangling = await DanglingEntityScanner(catalog).scan([DOCUMENT_ID])
        assert dangling == [str(DOCUMENT_ID)]
