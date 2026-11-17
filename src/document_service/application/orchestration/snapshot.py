"""Ảnh chụp phiên bản lưu trong intent, để job phục hồi đăng ký lại được.

Khi Document Service bị kill giữa luồng upload, bytes của file đã nằm trên Object
Storage nhưng thông tin phiên bản không còn trong RAM. Intent vì vậy mang theo một
snapshot đủ để `IntentRecoveryJob` dựng lại entity mà không cần người dùng gửi lại.
"""

from __future__ import annotations

from document_service.domain.model import DocumentVersion
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    StorageUri,
    VersionLabel,
)


class VersionSnapshot:
    """Chuyển DocumentVersion sang dict chuỗi và ngược lại."""

    def to_payload(self, version: DocumentVersion) -> dict[str, str]:
        """Serialize phiên bản thành dict chuỗi để lưu cùng intent."""
        return {
            "version_id": str(version.version_id),
            "document_id": str(version.document_id),
            "label": str(version.label),
            "checksum": str(version.checksum),
            "storage_uri": str(version.storage_uri),
            "original_file_name": version.original_file_name,
            "content_format": version.content_format,
            "size_bytes": str(version.size_bytes),
            "status": str(version.status),
            "created_by": version.created_by,
        }

    def from_payload(self, payload: dict[str, str]) -> DocumentVersion:
        """Dựng lại phiên bản từ snapshot đã lưu."""
        return DocumentVersion(
            version_id=DocumentVersionId(payload["version_id"]),
            document_id=DocumentId(payload["document_id"]),
            label=VersionLabel(payload["label"]),
            checksum=Checksum.parse(payload["checksum"]),
            storage_uri=StorageUri.parse(payload["storage_uri"]),
            original_file_name=payload.get("original_file_name", ""),
            content_format=payload.get("content_format", ""),
            size_bytes=int(payload.get("size_bytes", "0")),
            status=DocumentStatus(payload.get("status", DocumentStatus.DRAFT)),
            created_by=payload.get("created_by", ""),
        )
