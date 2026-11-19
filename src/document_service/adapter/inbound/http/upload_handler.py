"""D4 Upload Handler và IdempotencyKeyFilter.

`UploadHandler` nhận file từ HTTP, tính checksum **theo luồng** và dựng `UploadRequest`
cùng factory luồng dữ liệu cho saga. Theo mục 2.3 báo cáo, bước này **chỉ** trích xuất
metadata kỹ thuật (định dạng, kích thước, checksum) và không đọc nội dung tài liệu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from document_service.domain.dto import UploadRequest
from document_service.domain.errors import InvalidValueError
from document_service.domain.model import Principal
from document_service.domain.value import Checksum, DocumentId, IdempotencyKey, VersionLabel
from document_service.utils.hashing import StreamingHasher
from document_service.utils.ids import UlidGenerator

CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


class UploadSource(Protocol):
    """Phần giao diện của `UploadFile` mà handler cần."""

    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes:
        """Đọc một khối dữ liệu."""


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    """Kết quả chuẩn bị một lượt upload."""

    request: UploadRequest
    payload: bytes

    def stream_factory(self) -> AsyncIterator[bytes]:
        """Factory luồng dữ liệu, chia khối để saga ghi object."""

        async def iterator() -> AsyncIterator[bytes]:
            for index in range(0, len(self.payload), CHUNK_SIZE):
                yield self.payload[index : index + CHUNK_SIZE]

        return iterator()


class UploadHandler:
    """Nhận file, tính checksum theo luồng và dựng UploadRequest."""

    def __init__(self, max_bytes: int = MAX_UPLOAD_BYTES) -> None:
        """Nhận giới hạn kích thước file."""
        self._max_bytes = max_bytes

    async def prepare(
        self,
        document_id: DocumentId,
        upload: UploadSource,
        principal: Principal,
        idempotency_key: IdempotencyKey,
        version_label: str | None = None,
    ) -> PreparedUpload:
        """Đọc file theo khối, kiểm tra kích thước và dựng yêu cầu tạo phiên bản."""
        hasher = StreamingHasher()
        chunks: list[bytes] = []
        while True:
            chunk = await upload.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            if hasher.size_bytes > self._max_bytes:
                raise InvalidValueError(f"file exceeds the {self._max_bytes} byte limit")
            chunks.append(chunk)
        if hasher.size_bytes == 0:
            raise InvalidValueError("file is empty")
        request = UploadRequest(
            document_id=document_id,
            original_file_name=upload.filename or "unnamed",
            content_format=upload.content_type or "application/octet-stream",
            checksum=Checksum(algorithm=hasher.algorithm, hex_digest=hasher.hex_digest()),
            size_bytes=hasher.size_bytes,
            actor=principal.as_actor(),
            idempotency_key=idempotency_key,
            label=VersionLabel(version_label) if version_label else None,
        )
        return PreparedUpload(request=request, payload=b"".join(chunks))


class IdempotencyKeyFilter:
    """Kiểm tra header `Idempotency-Key` của mọi endpoint ghi (bất biến I13)."""

    def __init__(self, required: bool = True) -> None:
        """Nhận cấu hình có bắt buộc hay không."""
        self._required = required

    @property
    def required(self) -> bool:
        """Header có bắt buộc hay không."""
        return self._required

    def resolve(self, raw_value: str | None) -> IdempotencyKey:
        """Trả về khóa hợp lệ, hoặc phát lỗi nếu thiếu mà cấu hình bắt buộc."""
        if raw_value:
            return IdempotencyKey(raw_value)
        if self._required:
            raise InvalidValueError("missing Idempotency-Key header")
        return IdempotencyKey(UlidGenerator().new_id("REQ"))
