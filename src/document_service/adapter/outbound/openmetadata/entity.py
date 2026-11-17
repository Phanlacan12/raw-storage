"""Mapper giữa mô hình nghiệp vụ và entity của OpenMetadata.

Ánh xạ cố định theo bảng mục 5 của docs/c4-04b-code-structure.md:
`Document → Directory`, `DocumentVersion → File`, metadata mở rộng → `extension`.
Đây là **lớp duy nhất** biết các khái niệm `fullyQualifiedName`, `extension`,
`directory` của OpenMetadata.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from document_service.adapter.outbound.openmetadata.endpoints import OmFqnBuilder
from document_service.domain.model import (
    AccessPolicy,
    Collection,
    Document,
    DocumentMetadata,
    DocumentVersion,
)
from document_service.domain.value import (
    Checksum,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    StorageUri,
    VersionLabel,
)
from document_service.utils.clock import utc_now


class OmExtensionMapper:
    """Chuyển dict metadata của kho thành `extension` và ngược lại."""

    def to_extension(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Chuẩn hoá giá trị để OpenMetadata lưu được trong custom property."""
        extension: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            extension[key] = ",".join(str(item) for item in value) if isinstance(
                value, (list, tuple)
            ) else value
        return extension

    def from_extension(self, extension: dict[str, Any]) -> dict[str, Any]:
        """Đọc `extension` về dict metadata của kho."""
        metadata = dict(extension or {})
        tags = metadata.get("tags")
        if isinstance(tags, str):
            metadata["tags"] = [item for item in tags.split(",") if item]
        return metadata

    def extension_field_path(self, field_name: str) -> str:
        """Đường dẫn trường dùng khi lọc qua Search API."""
        return f"extension.{field_name}"

    def to_document_metadata(self, extension: dict[str, Any]) -> DocumentMetadata:
        """Dựng metadata mô tả từ `extension`, dùng chung cho entity và search."""
        metadata = self.from_extension(extension)
        return DocumentMetadata(
            title=str(metadata.get("title", "")),
            description=str(metadata.get("description", "")),
            document_type=str(metadata.get("document_type", "")),
            tags=tuple(metadata.get("tags", []) or ()),
            language=str(metadata.get("language", "")),
            owner=str(metadata.get("owner", "")),
            department=str(metadata.get("department", "")),
            collection_id=str(metadata.get("collection_id", "")),
        )


class OmDirectoryMapper:
    """Chuyển Collection và Document thành payload Directory."""

    def __init__(self, fqn: OmFqnBuilder, extensions: OmExtensionMapper | None = None) -> None:
        """Nhận bộ dựng FQN và mapper extension."""
        self._fqn = fqn
        self._extensions = extensions or OmExtensionMapper()

    def collection_payload(self, collection: Collection) -> dict[str, Any]:
        """Payload tạo Directory cho một collection."""
        return {
            "name": collection.collection_id,
            "displayName": collection.name,
            "service": self._fqn.service_fqn,
            "parent": self._fqn.root_fqn,
            "extension": {
                "collection_id": collection.collection_id,
                "collection_type": collection.collection_type,
                "owner": collection.owner,
                "department": collection.department,
            },
        }

    def document_payload(self, document: Document, metadata: dict[str, Any]) -> dict[str, Any]:
        """Payload tạo Directory đại diện tài liệu."""
        parent = (
            self._fqn.collection_fqn(document.metadata.collection_id)
            if document.metadata.collection_id
            else self._fqn.root_fqn
        )
        return {
            "name": self._fqn.document_name(document.document_id),
            "displayName": document.metadata.title or str(document.document_id),
            "description": document.metadata.description,
            "service": self._fqn.service_fqn,
            "parent": parent,
            "extension": self._extensions.to_extension(metadata),
        }

    def to_document(self, payload: dict[str, Any]) -> Document:
        """Dựng Document từ payload Directory đã đọc về."""
        raw_extension = payload.get("extension", {})
        extension = self._extensions.from_extension(raw_extension)
        document_id = DocumentId(str(extension.get("document_id") or payload.get("name", "")))
        metadata = self._extensions.to_document_metadata(raw_extension)
        if not metadata.title:
            metadata = replace(metadata, title=str(payload.get("displayName", "")))
        current = extension.get("current_version_id") or ""
        return Document(
            document_id=document_id,
            metadata=metadata,
            access_policy=AccessPolicy(
                classification=str(extension.get("classification", "restricted"))
            ),
            retention_policy=str(extension.get("retention_policy", "")),
            current_version_id=DocumentVersionId(str(current)) if current else None,
        )


class OmFileEntityMapper:
    """Chuyển DocumentVersion thành payload File và ngược lại."""

    def __init__(self, fqn: OmFqnBuilder, extensions: OmExtensionMapper | None = None) -> None:
        """Nhận bộ dựng FQN và mapper extension."""
        self._fqn = fqn
        self._extensions = extensions or OmExtensionMapper()

    def to_file_payload(
        self, version: DocumentVersion, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Payload tạo File entity cho một phiên bản nội dung."""
        return {
            "name": self._fqn.version_name(version.version_id),
            "displayName": f"{version.original_file_name} ({version.label})",
            "service": self._fqn.service_fqn,
            "directory": self._fqn.document_fqn(version.document_id),
            "fileType": version.content_format or "Unknown",
            "size": version.size_bytes,
            "checksum": str(version.checksum),
            "path": str(version.storage_uri),
            "extension": self._extensions.to_extension(metadata),
        }

    def to_version(self, payload: dict[str, Any]) -> DocumentVersion:
        """Dựng DocumentVersion từ payload File đã đọc về."""
        extension = self._extensions.from_extension(payload.get("extension", {}))
        document_id = DocumentId(str(extension["document_id"]))
        version_id = DocumentVersionId(str(extension["document_version_id"]))
        return DocumentVersion(
            version_id=version_id,
            document_id=document_id,
            label=VersionLabel(str(extension.get("version_label", "v1"))),
            checksum=Checksum.parse(str(extension["checksum"])),
            storage_uri=StorageUri.parse(str(extension["storage_uri"])),
            original_file_name=str(extension.get("original_file_name", "")),
            content_format=str(extension.get("format", "")),
            size_bytes=int(extension.get("size", 0) or 0),
            status=DocumentStatus(str(extension.get("status", DocumentStatus.DRAFT))),
            created_by=str(extension.get("created_by", "")),
            created_at=self._parse_time(extension.get("created_at")),
        )

    def _parse_time(self, raw: Any) -> datetime:
        """Đọc thời điểm tạo, mặc định là hiện tại nếu thiếu."""
        if isinstance(raw, str) and raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                return utc_now()
        return utc_now()


class OmJsonPatchBuilder:
    """Dựng JSON Patch chỉ gồm phép `replace` trên đường dẫn cố định.

    Chỉ dùng `replace` vì theo bảng mục 11.2, `add` vào mảng **không** idempotent nên
    không retry an toàn được.
    """

    def __init__(self) -> None:
        """Khởi tạo danh sách phép rỗng."""
        self._operations: list[dict[str, Any]] = []

    def replace_extension(self, field_name: str, value: Any) -> OmJsonPatchBuilder:
        """Thay giá trị một trường trong `extension`."""
        self._operations.append(
            {"op": "replace", "path": f"/extension/{field_name}", "value": value}
        )
        return self

    def build(self) -> list[dict[str, Any]]:
        """Danh sách phép đã dựng."""
        return list(self._operations)

    @classmethod
    def from_fields(cls, fields: dict[str, Any]) -> list[dict[str, Any]]:
        """Dựng patch từ một dict trường cần cập nhật."""
        builder = cls()
        for key, value in fields.items():
            builder.replace_extension(key, value)
        return builder.build()


class OmEntityVersionGuard:
    """Phát hiện ghi đè đồng thời qua trường `version` của entity.

    OpenMetadata **không** có If-Match/ETag, nên lớp này chỉ là lớp phát hiện thứ hai;
    việc tuần tự hoá thật do `DocumentLockPort` đảm nhiệm (mục 5, điểm 2).
    """

    def capture(self, payload: dict[str, Any]) -> float:
        """Ghi lại version hiện tại của entity."""
        return float(payload.get("version", 0.0) or 0.0)

    def changed_unexpectedly(self, captured: float, payload: dict[str, Any]) -> bool:
        """Entity đã bị người khác sửa giữa lúc đọc và lúc ghi hay chưa."""
        current = float(payload.get("version", 0.0) or 0.0)
        return current < captured
