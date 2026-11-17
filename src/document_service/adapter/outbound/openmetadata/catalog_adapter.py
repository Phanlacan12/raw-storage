"""OpenMetadataCatalogAdapter: hiện thực MetadataCatalogPort trên OpenMetadata.

Theo mục 4, 5, 6 và 7 của docs/c4-04b-code-structure.md. Adapter này là **lớp duy
nhất** trong service biết tới Directory, File và `extension`; API công khai của
Document Service không phơi bày các khái niệm đó (mục 12).
"""

from __future__ import annotations

from typing import Any

from document_service.adapter.outbound.base import OutboundAdapter
from document_service.adapter.outbound.openmetadata import endpoints
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.adapter.outbound.openmetadata.endpoints import OmFqnBuilder
from document_service.adapter.outbound.openmetadata.entity import (
    OmDirectoryMapper,
    OmEntityVersionGuard,
    OmExtensionMapper,
    OmFileEntityMapper,
    OmJsonPatchBuilder,
)
from document_service.adapter.outbound.openmetadata.search import (
    OmSearchQueryBuilder,
    OmSearchResultMapper,
)
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.config import CatalogSettings
from document_service.domain.dto import EntityRef, SearchFilter, SearchPage, SearchQuery
from document_service.domain.errors import DocumentNotFoundError
from document_service.domain.model import Collection, Document, DocumentVersion
from document_service.domain.port import MetadataCatalogPort
from document_service.domain.value import DocumentId, DocumentVersionId
from document_service.infrastructure.health import DependencyKind, HealthResult
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.infrastructure.resilience.retry import ClassifiedError, ErrorClass


class OpenMetadataCatalogAdapter(MetadataCatalogPort, OutboundAdapter):
    """Đọc và ghi metadata trên OpenMetadata."""

    def __init__(
        self,
        client: OmHttpClient,
        settings: CatalogSettings,
        executor: ResilientCallExecutor,
    ) -> None:
        """Nhận client HTTP, cấu hình catalog và executor của phụ thuộc."""
        OutboundAdapter.__init__(self, executor, DependencyKind.REQUIRED_FOR_READ)
        self._client = client
        self._settings = settings
        self._fqn = OmFqnBuilder(settings.drive_service_name, settings.root_directory)
        extensions = OmExtensionMapper()
        self._extensions = extensions
        self._directories = OmDirectoryMapper(self._fqn, extensions)
        self._files = OmFileEntityMapper(self._fqn, extensions)
        self._metadata_builder = CatalogMetadataBuilder()
        self._queries = OmSearchQueryBuilder(extensions)
        self._results = OmSearchResultMapper(extensions)
        self._guard = OmEntityVersionGuard()

    async def ensure_collection(self, collection: Collection) -> EntityRef:
        """Tạo hoặc cập nhật Directory của collection, idempotent theo FQN."""
        payload = await self._client.put(
            endpoints.DIRECTORIES, self._directories.collection_payload(collection)
        )
        return self._as_ref(payload, "directory")

    async def register_document(self, document: Document) -> EntityRef:
        """Tạo hoặc cập nhật Directory đại diện tài liệu."""
        metadata = self._document_extension(document)
        payload = await self._client.put(
            endpoints.DIRECTORIES, self._directories.document_payload(document, metadata)
        )
        return self._as_ref(payload, "directory")

    async def register_version(
        self, version: DocumentVersion, metadata: dict[str, Any]
    ) -> EntityRef:
        """Tạo File entity cho một phiên bản, retry an toàn vì PUT theo FQN."""
        payload = await self._client.put(
            endpoints.FILES, self._files.to_file_payload(version, metadata)
        )
        return self._as_ref(payload, "file")

    async def patch_controlled_fields(
        self, version_id: DocumentVersionId, fields: dict[str, Any]
    ) -> None:
        """Cập nhật trường kiểm soát của một phiên bản bằng JSON Patch."""
        entity = await self._find_file(version_id)
        captured = self._guard.capture(entity)
        updated = await self._client.patch(
            f"{endpoints.FILES}/{entity['id']}", OmJsonPatchBuilder.from_fields(fields)
        )
        if self._guard.changed_unexpectedly(captured, updated):
            self._logger.warning(
                "entity version mismatch after patch",
                extra={"version_id": str(version_id), "captured": captured},
            )

    async def patch_document_fields(self, document_id: DocumentId, fields: dict[str, Any]) -> None:
        """Cập nhật trường kiểm soát ở mức tài liệu."""
        entity = await self._get_directory(document_id)
        await self._client.patch(
            f"{endpoints.DIRECTORIES}/{entity['id']}", OmJsonPatchBuilder.from_fields(fields)
        )

    async def read_document(self, document_id: DocumentId) -> Document:
        """Đọc Directory của tài liệu kèm toàn bộ File entity con."""
        entity = await self._get_directory(document_id)
        document = self._directories.to_document(entity)
        document.versions.extend(await self.list_versions(document_id))
        return document

    async def list_versions(self, document_id: DocumentId) -> list[DocumentVersion]:
        """Danh sách phiên bản, đọc từ các File entity trong Directory."""
        payload = await self._client.get(
            endpoints.FILES,
            {
                "directory": self._fqn.document_fqn(document_id),
                "fields": "extension",
                "limit": 1000,
            },
        )
        items = payload.get("data", [])
        versions: list[DocumentVersion] = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("extension"):
                versions.append(self._files.to_version(item))
        return sorted(versions, key=lambda version: version.created_at)

    async def search(self, query: SearchQuery) -> SearchPage:
        """Tìm kiếm qua Search API với filter tổ hợp trên `extension`."""
        payload = await self._client.get(endpoints.SEARCH_QUERY, self._queries.build(query))
        return self._results.to_page(payload, query)

    async def _probe_dependency(self) -> HealthResult:
        """Gọi `/system/version` và so với phiên bản đã cố định."""
        version = await self._client.server_version()
        if not self._client.pin.matches(version):
            return self.health_degraded(
                f"server {version} differs from pinned version "
                f"{self._client.pin.pinned_version}"
            )
        return self.health_up(f"version={version}")

    async def _get_directory(self, document_id: DocumentId) -> dict[str, Any]:
        """Đọc Directory theo FQN, lỗi rõ ràng nếu chưa đăng ký.

        404 của catalog được dịch sang `DocumentNotFoundError` để lớp HTTP trả 404,
        thay vì để lỗi hạ tầng rò lên thành 400 hoặc 500.
        """
        fqn = self._fqn.document_fqn(document_id)
        try:
            payload = await self._client.get(
                f"{endpoints.DIRECTORY_BY_NAME}/{fqn}", {"fields": "extension"}
            )
        except ClassifiedError as error:
            if error.error_class is ErrorClass.NON_RETRYABLE_CLIENT:
                raise DocumentNotFoundError(f"document {document_id} is not registered") from error
            raise
        if not payload.get("id"):
            raise DocumentNotFoundError(f"document {document_id} is not registered")
        return payload

    async def _find_file(self, version_id: DocumentVersionId) -> dict[str, Any]:
        """Tìm File entity của một phiên bản qua Search API rồi đọc lại theo id."""
        filters = (SearchFilter(field_name="document_version_id", value=str(version_id)),)
        query = SearchQuery(filters=filters, page_size=1)
        page = await self.search(query)
        if not page.hits:
            raise DocumentNotFoundError(f"version {version_id} not found")
        hit = page.hits[0]
        fqn = self._fqn.version_fqn(hit.document_id, hit.version_id)
        try:
            payload = await self._client.get(
                f"{endpoints.FILE_BY_NAME}/{fqn}", {"fields": "extension"}
            )
        except ClassifiedError as error:
            if error.error_class is ErrorClass.NON_RETRYABLE_CLIENT:
                raise DocumentNotFoundError(f"cannot read version {version_id}") from error
            raise
        if not payload.get("id"):
            raise DocumentNotFoundError(f"cannot read version {version_id}")
        return payload

    def _document_extension(self, document: Document) -> dict[str, Any]:
        """Metadata mức tài liệu ghi vào `extension` của Directory."""
        current = document.current_version_id
        return {
            **self._metadata_builder.descriptive_fields(document.metadata),
            "document_id": str(document.document_id),
            "classification": document.access_policy.classification,
            "retention_policy": document.retention_policy,
            "current_version_id": str(current) if current is not None else "",
        }

    def _as_ref(self, payload: dict[str, Any], entity_type: str) -> EntityRef:
        """Chuyển payload entity thành EntityRef trung tính sản phẩm."""
        return EntityRef(
            entity_id=str(payload.get("id", "")),
            entity_type=entity_type,
            fully_qualified_name=str(payload.get("fullyQualifiedName", "")),
            entity_version=payload.get("version"),
        )
