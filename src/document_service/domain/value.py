"""Value object và enum của miền nghiệp vụ.

Tham chiếu docs/c4-04-code-data-model.md mục 4.1 và docs/c4-04b-code-structure.md mục 3.
Mọi value object là bất biến và tự kiểm tra tính hợp lệ khi khởi tạo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from document_service.domain.errors import InvalidValueError

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CHECKSUM_PATTERN = re.compile(r"^[0-9a-f]{32,128}$")


class DocumentStatus(StrEnum):
    """Trạng thái của một phiên bản nội dung (bất biến I4, I5)."""

    DRAFT = "Draft"
    APPROVED = "Approved"
    OBSOLETE = "Obsolete"


class RelationType(StrEnum):
    """Ba kiểu quan hệ tối thiểu theo mục 2.4 của báo cáo."""

    REFERENCES = "references"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"


class Direction(StrEnum):
    """Chiều truy vấn quan hệ (bất biến I7)."""

    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class IntentState(StrEnum):
    """Chuỗi trạng thái của một upload intent, mục 3.5 báo cáo."""

    RECEIVED = "Received"
    OBJECT_STORED = "ObjectStored"
    CATALOG_REGISTERED = "CatalogRegistered"
    STATUS_CHANGE_PENDING = "StatusChangePending"
    COMPLETED = "Completed"
    RETRY_PENDING = "RetryPending"
    FAILED = "Failed"

    @property
    def is_terminal(self) -> bool:
        """Trạng thái kết thúc, không cần phục hồi thêm."""
        return self in (IntentState.COMPLETED, IntentState.FAILED)


class Action(StrEnum):
    """Hành động được phân quyền, mục 2.6 báo cáo."""

    VIEW_METADATA = "view_metadata"
    SEARCH = "search"
    DOWNLOAD = "download"
    WRITE = "write"
    TRANSITION_STATUS = "transition_status"
    MANAGE_POLICY = "manage_policy"


@dataclass(frozen=True, slots=True)
class DocumentId:
    """Định danh tài liệu, cố định suốt vòng đời (bất biến I1)."""

    value: str

    def __post_init__(self) -> None:
        """Kiểm tra định dạng ID."""
        self.validate()

    def validate(self) -> None:
        """Bảo đảm ID không rỗng và chỉ gồm ký tự an toàn cho khóa lưu trữ."""
        if not _ID_PATTERN.match(self.value):
            raise InvalidValueError(f"invalid document_id: {self.value!r}")

    def __str__(self) -> str:
        """Dạng chuỗi dùng trong URI và log."""
        return self.value


@dataclass(frozen=True, slots=True)
class DocumentVersionId:
    """Định danh phiên bản nội dung, bất biến và không phụ thuộc version_label."""

    value: str

    def __post_init__(self) -> None:
        """Kiểm tra định dạng ID."""
        self.validate()

    def validate(self) -> None:
        """Bảo đảm ID không rỗng và chỉ gồm ký tự an toàn cho khóa lưu trữ."""
        if not _ID_PATTERN.match(self.value):
            raise InvalidValueError(f"invalid document_version_id: {self.value!r}")

    def __str__(self) -> str:
        """Dạng chuỗi dùng trong URI và log."""
        return self.value


@dataclass(frozen=True, slots=True)
class VersionLabel:
    """Nhãn phiên bản do người dùng đặt, duy nhất trong một tài liệu (bất biến I2)."""

    value: str

    def __post_init__(self) -> None:
        """Kiểm tra định dạng nhãn."""
        self.validate()

    def validate(self) -> None:
        """Bảo đảm nhãn ngắn gọn, không chứa ký tự gây nhầm với đường dẫn."""
        if not _LABEL_PATTERN.match(self.value):
            raise InvalidValueError(f"invalid version_label: {self.value!r}")

    def __str__(self) -> str:
        """Dạng chuỗi của nhãn."""
        return self.value


@dataclass(frozen=True, slots=True)
class Checksum:
    """Checksum nội dung file, dùng cho dedup và đối soát toàn vẹn."""

    algorithm: str
    hex_digest: str

    def __post_init__(self) -> None:
        """Kiểm tra thuật toán và chuỗi hex."""
        self.validate()

    def validate(self) -> None:
        """Chỉ nhận thuật toán đã biết và chuỗi hex đúng định dạng."""
        if self.algorithm not in ("sha256", "sha512", "md5"):
            raise InvalidValueError(f"unsupported checksum algorithm: {self.algorithm}")
        if not _CHECKSUM_PATTERN.match(self.hex_digest):
            raise InvalidValueError("invalid checksum hex_digest")

    @classmethod
    def parse(cls, raw: str) -> Checksum:
        """Đọc checksum dạng `sha256:<hex>`."""
        if ":" not in raw:
            raise InvalidValueError("checksum must have the form <algorithm>:<hex>")
        algorithm, _, digest = raw.partition(":")
        return cls(algorithm=algorithm.strip().lower(), hex_digest=digest.strip().lower())

    def __str__(self) -> str:
        """Dạng chuỗi `sha256:<hex>` dùng trong metadata."""
        return f"{self.algorithm}:{self.hex_digest}"


@dataclass(frozen=True, slots=True)
class StorageUri:
    """Vị trí object bất biến trên Object Storage (bất biến I10)."""

    bucket: str
    key: str

    def __post_init__(self) -> None:
        """Kiểm tra bucket và key."""
        self.validate()

    def validate(self) -> None:
        """Bảo đảm bucket và key không rỗng."""
        if not self.bucket or not self.key:
            raise InvalidValueError("storage_uri must have both bucket and key")

    @classmethod
    def for_version(
        cls, bucket: str, document_id: DocumentId, version_id: DocumentVersionId
    ) -> StorageUri:
        """Dựng URI theo quy ước object key ở mục 4.6 của tài liệu thiết kế."""
        return cls(bucket=bucket, key=f"objects/{document_id}/{version_id}/source")

    @classmethod
    def parse(cls, raw: str) -> StorageUri:
        """Đọc URI dạng `s3://bucket/key`."""
        if not raw.startswith("s3://"):
            raise InvalidValueError("storage_uri must start with s3://")
        remainder = raw[len("s3://") :]
        bucket, _, key = remainder.partition("/")
        return cls(bucket=bucket, key=key)

    def __str__(self) -> str:
        """Dạng chuỗi `s3://bucket/key`."""
        return f"s3://{self.bucket}/{self.key}"


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """Khóa chống lặp cho mọi API ghi (bất biến I13)."""

    value: str

    def __post_init__(self) -> None:
        """Kiểm tra khóa."""
        self.validate()

    def validate(self) -> None:
        """Khóa phải đủ dài để không trùng do ngẫu nhiên."""
        if len(self.value) < 8 or len(self.value) > 200:
            raise InvalidValueError("idempotency_key must be 8..200 characters long")

    def __str__(self) -> str:
        """Dạng chuỗi của khóa."""
        return self.value


@dataclass(frozen=True, slots=True)
class RequestId:
    """Định danh một lượt xử lý, gắn với intent bền vững."""

    value: str

    def __post_init__(self) -> None:
        """Kiểm tra định danh."""
        self.validate()

    def validate(self) -> None:
        """Bảo đảm định danh không rỗng."""
        if not _ID_PATTERN.match(self.value):
            raise InvalidValueError(f"invalid request_id: {self.value!r}")

    def __str__(self) -> str:
        """Dạng chuỗi của định danh."""
        return self.value


@dataclass(frozen=True, slots=True)
class Actor:
    """Người hoặc service account thực hiện một thao tác, dùng cho audit."""

    principal_id: str
    display_name: str = ""

    def __post_init__(self) -> None:
        """Kiểm tra định danh chủ thể."""
        self.validate()

    def validate(self) -> None:
        """Chủ thể phải có định danh."""
        if not self.principal_id:
            raise InvalidValueError("actor must have a principal_id")

    def __str__(self) -> str:
        """Dạng chuỗi dùng trong log."""
        return self.principal_id
