"""Test adapter OpenMetadata bằng HTTP mock (respx).

Kiểm chứng phần tôi kiểm soát được mà không cần hạ tầng: ánh xạ Document → Directory,
DocumentVersion → File, metadata → `extension`, JSON Patch chỉ dùng `replace`, và
phân loại lỗi HTTP theo mục 11.2. Khả năng **thực sự** lọc được custom property qua
Search API vẫn phải đo trên bản triển khai (POC-19) — test mock không thay thế được.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from document_service.adapter.outbound.openmetadata.catalog_adapter import (
    OpenMetadataCatalogAdapter,
)
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.config import CatalogSettings, DependencyResiliencePolicy
from document_service.domain.dto import SearchFilter, SearchQuery
from document_service.domain.errors import DependencyUnavailableError
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

BASE_URL = "http://openmetadata.test"
CHECKSUM = Checksum.parse("sha256:" + "c" * 64)


@pytest.fixture
def adapter() -> OpenMetadataCatalogAdapter:
    """Adapter trỏ vào host giả lập."""
    settings = CatalogSettings(
        base_url=BASE_URL, bot_token="token", pinned_version="1.12", drive_service_name="raw"
    )
    executor = ResilientCallExecutor(
        "catalog", DependencyResiliencePolicy(max_attempts=2, base_delay_seconds=0.01)
    )
    return OpenMetadataCatalogAdapter(OmHttpClient(settings, executor), settings, executor)


def _version() -> DocumentVersion:
    """Phiên bản mẫu."""
    document_id = DocumentId("DOC-1")
    version_id = DocumentVersionId("VER-1")
    return DocumentVersion(
        version_id=version_id,
        document_id=document_id,
        label=VersionLabel("2.0"),
        checksum=CHECKSUM,
        storage_uri=StorageUri.for_version("raw-documents", document_id, version_id),
        original_file_name="srs.pdf",
        content_format="application/pdf",
        size_bytes=11,
        status=DocumentStatus.DRAFT,
    )


def _metadata() -> dict[str, object]:
    """Metadata mẫu gửi sang catalog."""
    return {
        "document_id": "DOC-1",
        "document_version_id": "VER-1",
        "version_label": "2.0",
        "status": "Draft",
        "classification": "internal",
        "collection_id": "PROJECT-A",
        "document_type": "SRS",
        "checksum": str(CHECKSUM),
        "storage_uri": "s3://raw-documents/objects/DOC-1/VER-1/source",
        "tags": ["a", "b"],
    }


class TestOpenMetadataAdapter:
    """Ánh xạ và xử lý lỗi của adapter."""

    @respx.mock
    async def test_register_version_maps_to_file_entity(
        self, adapter: OpenMetadataCatalogAdapter
    ) -> None:
        """Phiên bản được ghi thành File entity với `extension`."""
        route = respx.put(f"{BASE_URL}/api/v1/drives/files").mock(
            return_value=httpx.Response(
                200, json={"id": "file-1", "fullyQualifiedName": "raw.documents.DOC-1.VER-1"}
            )
        )
        ref = await adapter.register_version(_version(), _metadata())
        assert ref.entity_id == "file-1"
        assert ref.entity_type == "file"
        payload = respx.calls.last.request.read().decode()
        assert '"directory":"raw.documents.DOC-1"' in payload
        assert '"extension"' in payload
        assert '"document_version_id":"VER-1"' in payload
        assert route.called

    @respx.mock
    async def test_register_document_maps_to_directory(
        self, adapter: OpenMetadataCatalogAdapter
    ) -> None:
        """Tài liệu được ghi thành Directory **đặt trực tiếp dưới thư mục gốc**.

        Không đặt dưới Directory của collection: FQN phải ổn định khi tài liệu chuyển
        collection, và `read_document(document_id)` phải tra được mà không cần biết
        collection. Quan hệ với collection nằm ở `extension.collection_id`.
        """
        respx.put(f"{BASE_URL}/api/v1/drives/directories").mock(
            return_value=httpx.Response(200, json={"id": "dir-1"})
        )
        document = Document(
            document_id=DocumentId("DOC-1"),
            metadata=DocumentMetadata(title="SRS", document_type="SRS", collection_id="PROJECT-A"),
        )
        ref = await adapter.register_document(document)
        assert ref.entity_id == "dir-1"
        payload = respx.calls.last.request.read().decode()
        assert '"parent":"raw.documents"' in payload
        assert '"collection_id":"PROJECT-A"' in payload

    @respx.mock
    async def test_patch_uses_replace_only(self, adapter: OpenMetadataCatalogAdapter) -> None:
        """JSON Patch chỉ dùng `replace`, vì `add` vào mảng không idempotent."""
        respx.get(f"{BASE_URL}/api/v1/search/query").mock(
            return_value=httpx.Response(
                200,
                json={
                    "hits": {
                        "total": {"value": 1},
                        "hits": [{"_source": {"extension": _metadata()}}],
                    }
                },
            )
        )
        respx.get(f"{BASE_URL}/api/v1/drives/files/name/raw.documents.DOC-1.VER-1").mock(
            return_value=httpx.Response(200, json={"id": "file-1", "version": 1.0})
        )
        respx.patch(f"{BASE_URL}/api/v1/drives/files/file-1").mock(
            return_value=httpx.Response(200, json={"id": "file-1", "version": 1.1})
        )
        await adapter.patch_controlled_fields(DocumentVersionId("VER-1"), {"status": "Approved"})
        body = respx.calls.last.request.read().decode()
        assert '"op":"replace"' in body
        assert '"path":"/extension/status"' in body
        assert '"op":"add"' not in body

    @respx.mock
    async def test_search_filters_on_extension_fields(
        self, adapter: OpenMetadataCatalogAdapter
    ) -> None:
        """Lọc tổ hợp đi vào `query_filter` trên `extension.<field>`."""
        respx.get(f"{BASE_URL}/api/v1/search/query").mock(
            return_value=httpx.Response(
                200,
                json={
                    "hits": {
                        "total": {"value": 1},
                        "hits": [{"_source": {"extension": _metadata()}}],
                    }
                },
            )
        )
        query = SearchQuery(
            filters=(
                SearchFilter(field_name="document_type", value="SRS"),
                SearchFilter(field_name="status", value="Draft"),
            )
        )
        page = await adapter.search(query)
        assert page.total_hits == 1
        assert str(page.hits[0].version_id) == "VER-1"
        request_url = str(respx.calls.last.request.url)
        assert "extension.document_type" in request_url
        assert "extension.status" in request_url

    @respx.mock
    async def test_read_document_builds_versions(self, adapter: OpenMetadataCatalogAdapter) -> None:
        """Đọc Directory kèm các File entity con thành một Document đầy đủ."""
        respx.get(f"{BASE_URL}/api/v1/drives/directories/name/raw.documents.DOC-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "dir-1",
                    "name": "DOC-1",
                    "extension": {
                        "document_id": "DOC-1",
                        "title": "SRS",
                        "document_type": "SRS",
                        "collection_id": "PROJECT-A",
                        "classification": "internal",
                        "current_version_id": "VER-1",
                    },
                },
            )
        )
        respx.get(f"{BASE_URL}/api/v1/drives/files").mock(
            return_value=httpx.Response(200, json={"data": [{"extension": _metadata()}]})
        )
        document = await adapter.read_document(DocumentId("DOC-1"))
        assert document.metadata.document_type == "SRS"
        assert len(document.versions) == 1
        assert document.versions[0].version_id == DocumentVersionId("VER-1")
        assert document.current_version_id == DocumentVersionId("VER-1")

    @respx.mock
    async def test_retries_on_503_then_fails(self, adapter: OpenMetadataCatalogAdapter) -> None:
        """503 là lỗi tạm thời: retry rồi báo phụ thuộc không khả dụng."""
        route = respx.put(f"{BASE_URL}/api/v1/drives/files").mock(
            return_value=httpx.Response(503, text="unavailable")
        )
        with pytest.raises(DependencyUnavailableError):
            await adapter.register_version(_version(), _metadata())
        assert route.call_count == 2

    @respx.mock
    async def test_client_error_is_not_retried(self, adapter: OpenMetadataCatalogAdapter) -> None:
        """400 là lỗi phía client: trả ngay, không retry."""
        from document_service.infrastructure.resilience.retry import ClassifiedError

        route = respx.put(f"{BASE_URL}/api/v1/drives/files").mock(
            return_value=httpx.Response(400, text="bad request")
        )
        with pytest.raises(ClassifiedError):
            await adapter.register_version(_version(), _metadata())
        assert route.call_count == 1

    @respx.mock
    async def test_health_probe_checks_pinned_version(
        self, adapter: OpenMetadataCatalogAdapter
    ) -> None:
        """Health của adapter báo DEGRADED khi server lệch bản đã cố định."""
        respx.get(f"{BASE_URL}/api/v1/system/version").mock(
            return_value=httpx.Response(200, json={"version": "1.13.0"})
        )
        result = await adapter.check_health()
        assert result.status.value == "DEGRADED"
        assert "1.12" in result.detail
