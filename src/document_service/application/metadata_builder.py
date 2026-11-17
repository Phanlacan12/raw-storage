"""Dựng payload metadata gửi sang catalog.

Các trường ở đây đúng với bảng nhóm metadata ở mục 2.3 báo cáo và danh sách custom
property bắt buộc phải lọc được (POC-19): document_type, status, classification,
collection_id, version_label.
"""

from __future__ import annotations

from typing import Any

from document_service.domain.metadata_fields import FILTERABLE_FIELDS
from document_service.domain.model import Document, DocumentMetadata, DocumentVersion


class CatalogMetadataBuilder:
    """Chuyển thực thể nghiệp vụ thành dict metadata trung tính sản phẩm."""

    def descriptive_fields(self, metadata: DocumentMetadata) -> dict[str, Any]:
        """Phần metadata mô tả, dùng chung cho mức tài liệu và mức phiên bản.

        Một nơi duy nhất serialize `DocumentMetadata`, để mức tài liệu và mức phiên
        bản không lệch nhau khi thêm trường mới.
        """
        return {
            "title": metadata.title,
            "description": metadata.description,
            "document_type": metadata.document_type,
            "tags": list(metadata.tags),
            "language": metadata.language,
            "owner": metadata.owner,
            "department": metadata.department,
            "collection_id": metadata.collection_id,
        }

    def build(self, document: Document, version: DocumentVersion) -> dict[str, Any]:
        """Metadata đầy đủ của một phiên bản, không chứa khái niệm của catalog."""
        return {
            **self.descriptive_fields(document.metadata),
            "document_id": str(document.document_id),
            "document_version_id": str(version.version_id),
            "original_file_name": version.original_file_name,
            "version_label": str(version.label),
            "status": str(version.status),
            "classification": document.access_policy.classification,
            "format": version.content_format,
            "size": version.size_bytes,
            "checksum": str(version.checksum),
            "storage_uri": str(version.storage_uri),
        }

    def document_fields(self, document: Document) -> dict[str, Any]:
        """Trường kiểm soát ở mức tài liệu, chỉ Document Service được ghi."""
        current = document.current_version_id
        return {
            "current_version_id": str(current) if current is not None else "",
            "classification": document.access_policy.classification,
            "retention_policy": document.retention_policy,
        }

    def filterable_subset(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Phần metadata bắt buộc phải lọc được qua Search API."""
        return {key: metadata.get(key, "") for key in FILTERABLE_FIELDS}
