"""Bộ test hợp đồng của MetadataCatalogPort (plan B9).

Chạy trên **cả hai** hiện thực: `InMemoryCatalog` và `OpenMetadataCatalogAdapter` nói
chuyện với server giả lập ở `fake_openmetadata.py`. Nhờ vậy lỗi ánh xạ Document →
Directory, DocumentVersion → File và metadata → `extension` bị phát hiện ngay, thay vì
chờ tới lúc có hạ tầng thật.
"""

from __future__ import annotations

from typing import Iterator

import pytest
import respx

from document_service.adapter.outbound.fake.in_memory import InMemoryCatalog
from document_service.adapter.outbound.openmetadata.bootstrap import OmDriveServiceProvisioner
from document_service.adapter.outbound.openmetadata.catalog_adapter import (
    OpenMetadataCatalogAdapter,
)
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.config import CatalogSettings, DependencyResiliencePolicy
from document_service.domain.dto import SearchFilter, SearchQuery
from document_service.domain.model import AccessPolicy, Document, DocumentMetadata, DocumentVersion
from document_service.domain.port import MetadataCatalogPort
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    StorageUri,
    VersionLabel,
)
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from tests.contract.fake_openmetadata import FakeOpenMetadataServer

BASE_URL = "http://om.contract.test"
BUCKET = "raw-documents"
CHECKSUM = Checksum.parse("sha256:" + "1" * 64)
BUILDER = CatalogMetadataBuilder()


@pytest.fixture
def om_server() -> Iterator[FakeOpenMetadataServer]:
    """Server OpenMetadata giả lập, đã gắn route."""
    server = FakeOpenMetadataServer(BASE_URL)
    with respx.mock(assert_all_called=False) as router:
        server.install(router)
        yield server


@pytest.fixture(params=["in_memory", "openmetadata"])
def catalog(request: pytest.FixtureRequest) -> MetadataCatalogPort:
    """Hai hiện thực của catalog port."""
    if request.param == "in_memory":
        return InMemoryCatalog()
    request.getfixturevalue("om_server")
    settings = CatalogSettings(
        base_url=BASE_URL,
        bot_token="token",
        pinned_version="1.12",
        drive_service_name="raw",
        root_directory="documents",
    )
    executor = ResilientCallExecutor(
        "catalog", DependencyResiliencePolicy(max_attempts=1, base_delay_seconds=0.01)
    )
    client = OmHttpClient(settings, executor)
    return OpenMetadataCatalogAdapter(client, settings, executor)


def _document(suffix: str = "0001") -> Document:
    """Tài liệu mẫu."""
    return Document(
        document_id=DocumentId(f"DOC-{suffix}"),
        metadata=DocumentMetadata(
            title=f"SRS {suffix}",
            description="tai lieu mau",
            document_type="SRS",
            collection_id="PROJECT-A",
            owner="tester",
        ),
        access_policy=AccessPolicy(classification="internal"),
    )


def _version(document: Document, suffix: str, label: str) -> DocumentVersion:
    """Phiên bản mẫu của một tài liệu."""
    version_id = DocumentVersionId(f"VER-{suffix}")
    return DocumentVersion(
        version_id=version_id,
        document_id=document.document_id,
        label=VersionLabel(label),
        checksum=CHECKSUM,
        storage_uri=StorageUri.for_version(BUCKET, document.document_id, version_id),
        original_file_name="srs.pdf",
        content_format="application/pdf",
        size_bytes=11,
        status=DocumentStatus.DRAFT,
    )


async def _register(catalog: MetadataCatalogPort, document: Document) -> None:
    """Đăng ký tài liệu, tạo sẵn thư mục gốc nếu là adapter thật."""
    if isinstance(catalog, OpenMetadataCatalogAdapter):
        settings = CatalogSettings(
            base_url=BASE_URL, drive_service_name="raw", root_directory="documents"
        )
        client = OmHttpClient(
            settings, ResilientCallExecutor("catalog", DependencyResiliencePolicy())
        )
        provisioner = OmDriveServiceProvisioner(client, settings)
        await provisioner.ensure_root_directory()
    await catalog.register_document(document)


class TestCatalogContract:
    """Hợp đồng chung cho mọi hiện thực catalog."""

    async def test_register_then_read_document(self, catalog: MetadataCatalogPort) -> None:
        """Đăng ký rồi đọc lại giữ nguyên metadata mô tả."""
        document = _document()
        await _register(catalog, document)
        loaded = await catalog.read_document(document.document_id)
        assert loaded.document_id == document.document_id
        assert loaded.metadata.document_type == "SRS"
        assert loaded.metadata.collection_id == "PROJECT-A"
        assert loaded.access_policy.classification == "internal"

    async def test_register_version_is_idempotent(self, catalog: MetadataCatalogPort) -> None:
        """Đăng ký lại cùng phiên bản không tạo bản trùng (I13)."""
        document = _document()
        await _register(catalog, document)
        version = _version(document, "0001", "1.0")
        metadata = BUILDER.build(document, version)
        await catalog.register_version(version, metadata)
        await catalog.register_version(version, metadata)
        versions = await catalog.list_versions(document.document_id)
        assert len(versions) == 1
        assert versions[0].version_id == version.version_id

    async def test_list_versions_round_trip(self, catalog: MetadataCatalogPort) -> None:
        """Đọc lại phiên bản giữ nguyên nhãn, checksum và storage_uri (I10)."""
        document = _document()
        await _register(catalog, document)
        version = _version(document, "0002", "2.0")
        await catalog.register_version(version, BUILDER.build(document, version))
        loaded = (await catalog.list_versions(document.document_id))[0]
        assert loaded.label == version.label
        assert loaded.checksum == version.checksum
        assert loaded.storage_uri == version.storage_uri
        assert loaded.status is DocumentStatus.DRAFT

    async def test_patch_controlled_fields_changes_status(
        self, catalog: MetadataCatalogPort
    ) -> None:
        """Cập nhật `status` của một phiên bản rồi đọc lại thấy giá trị mới."""
        document = _document()
        await _register(catalog, document)
        version = _version(document, "0003", "1.0")
        await catalog.register_version(version, BUILDER.build(document, version))
        await catalog.patch_controlled_fields(
            document.document_id, version.version_id, {"status": str(DocumentStatus.APPROVED)}
        )
        loaded = (await catalog.list_versions(document.document_id))[0]
        assert loaded.status is DocumentStatus.APPROVED

    async def test_patch_document_fields_sets_current_version(
        self, catalog: MetadataCatalogPort
    ) -> None:
        """Cập nhật `current_version_id` ở mức tài liệu (I14)."""
        document = _document()
        await _register(catalog, document)
        version = _version(document, "0004", "1.0")
        await catalog.register_version(version, BUILDER.build(document, version))
        document.current_version_id = version.version_id
        await catalog.patch_document_fields(document.document_id, BUILDER.document_fields(document))
        loaded = await catalog.read_document(document.document_id)
        assert loaded.current_version_id == version.version_id

    async def test_search_filters_on_metadata(self, catalog: MetadataCatalogPort) -> None:
        """Lọc tổ hợp theo metadata trả đúng phiên bản (POC-02, POC-19)."""
        document = _document()
        await _register(catalog, document)
        first = _version(document, "0005", "1.0")
        second = _version(document, "0006", "2.0")
        await catalog.register_version(first, BUILDER.build(document, first))
        approved_metadata = {
            **BUILDER.build(document, second),
            "status": str(DocumentStatus.APPROVED),
        }
        await catalog.register_version(second, approved_metadata)
        page = await catalog.search(
            SearchQuery(
                filters=(
                    SearchFilter(field_name="document_type", value="SRS"),
                    SearchFilter(field_name="status", value=str(DocumentStatus.APPROVED)),
                )
            )
        )
        assert [hit.version_id for hit in page.hits] == [second.version_id]

    async def test_search_returns_empty_for_unknown_value(
        self, catalog: MetadataCatalogPort
    ) -> None:
        """Lọc theo giá trị không tồn tại trả về rỗng, không trả hết."""
        document = _document()
        await _register(catalog, document)
        version = _version(document, "0007", "1.0")
        await catalog.register_version(version, BUILDER.build(document, version))
        page = await catalog.search(
            SearchQuery(filters=(SearchFilter(field_name="document_type", value="LLD"),))
        )
        assert page.hits == ()

    async def test_read_unknown_document_raises(self, catalog: MetadataCatalogPort) -> None:
        """Tài liệu chưa đăng ký thì báo lỗi rõ ràng."""
        from document_service.domain.errors import DomainError

        with pytest.raises(DomainError):
            await catalog.read_document(DocumentId("DOC-KHONG-CO"))

    async def test_health_probe_reports_up(self, catalog: MetadataCatalogPort) -> None:
        """Catalog tự khai báo health và không tạo entity khi kiểm tra."""
        from document_service.infrastructure.health import HealthProbe

        assert isinstance(catalog, HealthProbe)
        document = _document()
        await _register(catalog, document)
        before = len(await catalog.list_versions(document.document_id))
        result = await catalog.check_health()
        after = len(await catalog.list_versions(document.document_id))
        assert result.healthy is True
        assert before == after
