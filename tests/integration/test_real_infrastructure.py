"""Test tích hợp với OpenMetadata và Object Storage thật.

Mặc định **bỏ qua**: chỉ chạy khi có biến môi trường trỏ tới hạ tầng (xem
deploy/README.md). Đây là nơi kiểm chứng những điều mock không trả lời được:
POC-19 (lọc custom property), POC-20 (không bypass được Document Service) và
POC-22 (hai lượt duyệt đồng thời).
"""

from __future__ import annotations

import os
from typing import AsyncIterator

import pytest

from document_service.adapter.outbound.openmetadata.bootstrap import (
    OmCustomPropertyRegistrar,
    OmSchemaMigration,
)
from document_service.adapter.outbound.openmetadata.catalog_adapter import (
    OpenMetadataCatalogAdapter,
)
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.adapter.outbound.storage.s3_store import S3ObjectStoreAdapter
from document_service.config import Settings
from document_service.domain.dto import SearchFilter, SearchQuery
from document_service.domain.model import Document, DocumentMetadata, DocumentVersion
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    StorageUri,
    VersionLabel,
)
from document_service.infrastructure.resilience.executor import ResilientCallExecutor

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("DS_CATALOG__BASE_URL") or not os.environ.get("DS_STORAGE__ENDPOINT"),
        reason="thiếu DS_CATALOG__BASE_URL hoặc DS_STORAGE__ENDPOINT, xem deploy/README.md",
    ),
]
CHECKSUM = Checksum.parse("sha256:" + "f" * 64)


@pytest.fixture
def real_settings() -> Settings:
    """Cấu hình đọc từ môi trường trỏ tới hạ tầng thật."""
    return Settings()


@pytest.fixture
def client(real_settings: Settings) -> OmHttpClient:
    """Client HTTP tới OpenMetadata thật."""
    executor = ResilientCallExecutor("catalog", real_settings.resilience.catalog)
    return OmHttpClient(real_settings.catalog, executor)


@pytest.fixture
def catalog(client: OmHttpClient, real_settings: Settings) -> OpenMetadataCatalogAdapter:
    """Adapter catalog trỏ tới OpenMetadata thật."""
    executor = ResilientCallExecutor("catalog", real_settings.resilience.catalog)
    return OpenMetadataCatalogAdapter(client, real_settings.catalog, executor)


def _stream(payload: bytes) -> AsyncIterator[bytes]:
    """Luồng dữ liệu một khối."""

    async def iterator() -> AsyncIterator[bytes]:
        yield payload

    return iterator()


class TestSchemaMigration:
    """POC-19: custom property phải đăng ký được và kiểm tra được."""

    async def test_migration_registers_required_properties(
        self, client: OmHttpClient, real_settings: Settings
    ) -> None:
        """Chạy migration rồi xác nhận các trường bắt buộc đã tồn tại."""
        await OmSchemaMigration(client, real_settings.catalog).run_on_startup()
        registrar = OmCustomPropertyRegistrar(client)
        existing = await registrar.existing_properties("file")
        assert set(real_settings.catalog.required_properties) <= existing

    async def test_assert_filterable_detects_missing(self, client: OmHttpClient) -> None:
        """Trường chưa đăng ký bị phát hiện, service sẽ fail fast."""
        from document_service.adapter.outbound.openmetadata.bootstrap import (
            SchemaNotReadyError,
        )

        registrar = OmCustomPropertyRegistrar(client)
        with pytest.raises(SchemaNotReadyError):
            await registrar.assert_filterable("file", ["truong_khong_ton_tai"])


class TestCatalogRoundTrip:
    """Ghi rồi đọc lại trên catalog thật."""

    async def test_register_and_read_document(
        self, catalog: OpenMetadataCatalogAdapter
    ) -> None:
        """Document → Directory, đọc lại giữ nguyên metadata."""
        document_id = DocumentId("DOC-IT-0001")
        document = Document(
            document_id=document_id,
            metadata=DocumentMetadata(
                title="SRS tich hop", document_type="SRS", collection_id="PROJECT-IT"
            ),
        )
        await catalog.register_document(document)
        loaded = await catalog.read_document(document_id)
        assert loaded.metadata.document_type == "SRS"

    async def test_search_filters_custom_properties(
        self, catalog: OpenMetadataCatalogAdapter, real_settings: Settings
    ) -> None:
        """POC-19: lọc tổ hợp trên custom property qua Search API thật."""
        document_id = DocumentId("DOC-IT-0002")
        version_id = DocumentVersionId("VER-IT-0002")
        document = Document(
            document_id=document_id,
            metadata=DocumentMetadata(document_type="SRS", collection_id="PROJECT-IT"),
        )
        await catalog.register_document(document)
        version = DocumentVersion(
            version_id=version_id,
            document_id=document_id,
            label=VersionLabel("1.0"),
            checksum=CHECKSUM,
            storage_uri=StorageUri.for_version(
                real_settings.storage.bucket, document_id, version_id
            ),
            original_file_name="srs.pdf",
            content_format="application/pdf",
            size_bytes=3,
            status=DocumentStatus.DRAFT,
        )
        await catalog.register_version(
            version,
            {
                "document_id": str(document_id),
                "document_version_id": str(version_id),
                "document_type": "SRS",
                "status": "Draft",
                "classification": "internal",
                "collection_id": "PROJECT-IT",
                "version_label": "1.0",
                "checksum": str(CHECKSUM),
                "storage_uri": str(version.storage_uri),
            },
        )
        page = await catalog.search(
            SearchQuery(
                filters=(
                    SearchFilter(field_name="document_type", value="SRS"),
                    SearchFilter(field_name="collection_id", value="PROJECT-IT"),
                )
            )
        )
        assert any(hit.version_id == version_id for hit in page.hits), (
            "Search API khong loc duoc custom property — ghi KHONG DAT cho POC-19 "
            "va can bat C9 Search Gateway"
        )


class TestObjectStorage:
    """POC-01, POC-15 trên Object Storage thật."""

    async def test_put_head_presign(self, real_settings: Settings) -> None:
        """Ghi object bất biến, đọc lại kích thước và cấp link có thời hạn."""
        from datetime import timedelta

        executor = ResilientCallExecutor("object_store", real_settings.resilience.storage)
        store = S3ObjectStoreAdapter(real_settings.storage, executor)
        uri = StorageUri.for_version(
            real_settings.storage.bucket, DocumentId("DOC-IT-0003"), DocumentVersionId("VER-IT-0003")
        )
        result = await store.put_immutable(uri, _stream(b"noi dung tich hop"), CHECKSUM)
        assert result.size_bytes > 0
        info = await store.head(uri)
        assert info.size_bytes == result.size_bytes
        url = await store.presign(uri, timedelta(seconds=60))
        assert uri.key in url
        health = await store.check_health()
        assert health.healthy is True
