"""Mapper giữa mô hình nghiệp vụ và entity của OpenMetadata.

Ánh xạ cố định theo bảng mục 5 của docs/c4-04b-code-structure.md:
`Document → Directory`, `DocumentVersion → File`, metadata mở rộng → `extension`.
Đây là **lớp duy nhất** biết các khái niệm `fullyQualifiedName`, `extension`,
`directory` của OpenMetadata.
"""

from __future__ import annotations

import json
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

# `fileType` của File entity là ENUM của OpenMetadata, không phải MIME type. Đẩy
# thẳng `application/pdf` vào đây thì server trả 400 `Cannot construct instance of
# FileType`. MIME thật vẫn được giữ nguyên ở trường `format` trong `extension`, nên
# không mất thông tin; ánh xạ này chỉ để chọn đúng nhãn mà OpenMetadata hiểu.
_FILE_TYPE_ENUM = (
    "Document",
    "Spreadsheet",
    "Presentation",
    "Image",
    "Video",
    "Audio",
    "PDF",
    "Archive",
    "Code",
    "Data",
    "CSV",
    "Text",
    "Other",
)

_MIME_EXACT: dict[str, str] = {
    "application/pdf": "PDF",
    "text/csv": "CSV",
    "application/json": "Data",
    "application/xml": "Data",
    "text/xml": "Data",
    "application/yaml": "Data",
    "application/zip": "Archive",
    "application/gzip": "Archive",
    "application/x-tar": "Archive",
    "application/x-7z-compressed": "Archive",
    "application/vnd.rar": "Archive",
    "application/msword": "Document",
    "application/rtf": "Document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Document",
    "application/vnd.oasis.opendocument.text": "Document",
    "application/vnd.ms-excel": "Spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet": "Spreadsheet",
    "application/vnd.ms-powerpoint": "Presentation",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "Presentation",
    "application/vnd.oasis.opendocument.presentation": "Presentation",
}

_MIME_PREFIX: tuple[tuple[str, str], ...] = (
    ("image/", "Image"),
    ("video/", "Video"),
    ("audio/", "Audio"),
    ("text/", "Text"),
)


def _as_file_type(content_format: str | None) -> str:
    """Ánh xạ MIME type sang enum `fileType` của OpenMetadata."""
    if not content_format:
        return "Other"
    mime = content_format.split(";", 1)[0].strip().lower()
    if mime in _MIME_EXACT:
        return _MIME_EXACT[mime]
    for prefix, file_type in _MIME_PREFIX:
        if mime.startswith(prefix):
            return file_type
    return "Other"


class OmExtensionMapper:
    """Chuyển dict metadata của kho thành `extension` và ngược lại."""

    def to_extension(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Chuẩn hoá giá trị để OpenMetadata lưu được trong custom property."""
        extension: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if key == "access_policy":
                extension[key] = json.dumps(value, ensure_ascii=False)
                continue
            extension[key] = (
                ",".join(str(item) for item in value) if isinstance(value, (list, tuple)) else value
            )
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
                "parent_collection_id": collection.parent_collection_id or "",
                "owner": collection.owner,
                "department": collection.department,
            },
        }

    def document_payload(self, document: Document, metadata: dict[str, Any]) -> dict[str, Any]:
        """Payload tạo Directory đại diện tài liệu.

        Directory của tài liệu nằm **trực tiếp dưới thư mục gốc**, không nằm trong
        Directory của collection: FQN phải ổn định khi tài liệu chuyển collection, và
        `read_document(document_id)` phải tra được mà không cần biết collection. Quan
        hệ với collection giữ ở `extension.collection_id`.
        """
        parent = self._fqn.root_fqn
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
        acl = json.loads(extension.get("access_policy") or "{}")
        return Document(
            document_id=document_id,
            metadata=metadata,
            access_policy=AccessPolicy(
                classification=str(extension.get("classification", "restricted")),
                allowed_groups=tuple(acl.get("allowed_groups", ())),
                allowed_principals=tuple(acl.get("allowed_principals", ())),
                require_proxy_download=bool(acl.get("require_proxy_download", False)),
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

    def to_file_payload(self, version: DocumentVersion, metadata: dict[str, Any]) -> dict[str, Any]:
        """Payload tạo File entity cho một phiên bản nội dung."""
        return {
            "name": self._fqn.version_name(version.version_id),
            "displayName": f"{version.original_file_name} ({version.label})",
            "service": self._fqn.service_fqn,
            "directory": self._fqn.document_fqn(version.document_id),
            "fileType": _as_file_type(version.content_format),
            "size": version.size_bytes,
            "checksum": str(version.checksum),
            "path": str(version.storage_uri),
            # `columns` phải có mặt, kể cả rỗng. File tạo thiếu trường này thì mọi
            # lệnh PATCH sau đó đều trả 500 `Cannot invoke "java.util.List.iterator()"
            # because "updatedColumns" is null` — server duyệt danh sách columns khi
            # so sánh phiên bản cũ/mới. Kho raw data không có khái niệm cột, nên để
            # rỗng; đã đo: thiếu -> 500, có -> 200.
            "columns": [],
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
            approved_by=extension.get("approved_by") or None,
            obsoleted_by=extension.get("obsoleted_by") or None,
            approved_at=self._optional_time(extension.get("approved_at")),
            obsoleted_at=self._optional_time(extension.get("obsoleted_at")),
            created_by=str(extension.get("created_by", "")),
            created_at=self._optional_time(extension.get("created_at")) or utc_now(),
        )

    def _optional_time(self, raw: Any) -> datetime | None:
        """Đọc thời điểm ISO nếu catalog đã lưu."""
        if isinstance(raw, str) and raw:
            try:
                return datetime.fromisoformat(raw)
            except ValueError:
                return None
        return None


class OmJsonPatchBuilder:
    """Dựng JSON Patch trên các thuộc tính có tên cố định của object extension."""

    def __init__(self) -> None:
        """Khởi tạo danh sách phép rỗng."""
        self._operations: list[dict[str, Any]] = []

    def set_extension(self, field_name: str, value: Any, exists: bool) -> OmJsonPatchBuilder:
        """Thay giá trị một trường trong `extension`."""
        self._operations.append(
            {
                "op": "replace" if exists else "add",
                "path": f"/extension/{field_name}",
                "value": value,
            }
        )
        return self

    def build(self) -> list[dict[str, Any]]:
        """Danh sách phép đã dựng."""
        return list(self._operations)

    @classmethod
    def from_fields(cls, fields: dict[str, Any], existing: dict[str, Any]) -> list[dict[str, Any]]:
        """Dựng patch từ một dict trường cần cập nhật."""
        builder = cls()
        for key, value in fields.items():
            builder.set_extension(key, value, key in existing)
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
        """So sánh hai version quan sát được; một lượt PATCH cũng có thể tăng version."""
        current = float(payload.get("version", 0.0) or 0.0)
        return current != captured
