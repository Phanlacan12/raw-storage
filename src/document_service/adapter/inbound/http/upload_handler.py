"""D4 Upload Handler và IdempotencyKeyFilter.

`UploadHandler` nhận file từ HTTP, tính checksum **theo luồng** và dựng `UploadRequest`
cùng factory luồng dữ liệu cho saga. Theo mục 2.3 báo cáo, bước này **chỉ** trích xuất
metadata kỹ thuật (định dạng, kích thước, checksum) và không đọc nội dung tài liệu —
không parse MIME từ byte, không giải mã PDF/Office, không extract text. Trích xuất nội
dung thuộc phần tử D23 (ngoài phạm vi lượt này, xem X55 trong c4-08).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from document_service.config import StorageSettings
from document_service.domain.dto import UploadRequest
from document_service.domain.errors import InvalidValueError
from document_service.domain.model import Principal
from document_service.domain.value import Checksum, DocumentId, IdempotencyKey, VersionLabel
from document_service.utils.files import SpooledUploadBody
from document_service.utils.hashing import StreamingHasher
from document_service.utils.ids import UlidGenerator


class UploadSource(Protocol):
    """Phần giao diện của `UploadFile` mà handler cần."""

    filename: str | None
    content_type: str | None

    async def read(self, size: int = -1) -> bytes:
        """Đọc một khối dữ liệu."""

    async def seek(self, offset: int) -> None:
        """Đặt lại con trỏ đọc về đầu file."""


@dataclass(frozen=True, slots=True)
class PreparedUpload:
    """Kết quả chuẩn bị một lượt upload."""

    request: UploadRequest
    body: SpooledUploadBody

    def stream_factory(self) -> AsyncIterator[bytes]:
        """Factory luồng dữ liệu, mở lại body từ đầu cho mỗi lần gọi."""
        return self.body.chunks()

    async def aclose(self) -> None:
        """Đóng body sau khi dùng xong."""
        await self.body.aclose()


class UploadHandler:
    """Nhận file, tính checksum theo luồng và dựng UploadRequest."""

    def __init__(
        self,
        storage: StorageSettings | None = None,
        max_bytes: int | None = None,
        chunk_size: int | None = None,
    ) -> None:
        """Nhận cấu hình storage; fallback về mặc định an toàn khi test gọi tay."""
        resolved = storage or StorageSettings()
        self._max_bytes = max_bytes if max_bytes is not None else resolved.max_upload_bytes
        self._chunk_size = chunk_size if chunk_size is not None else resolved.multipart_part_bytes

    async def prepare(
        self,
        document_id: DocumentId,
        upload: UploadSource,
        principal: Principal,
        idempotency_key: IdempotencyKey,
        version_label: str | None = None,
    ) -> PreparedUpload:
        """Đọc file theo khối, kiểm tra kích thước và dựng yêu cầu tạo phiên bản.

        **Không** gọi thư viện đọc nội dung (PyPDF2, python-magic...): bước này chỉ
        trích xuất metadata kỹ thuật như yêu cầu của D4, phần tử D23 mới chịu
        trách nhiệm parse nội dung.
        """
        hasher = StreamingHasher()
        while True:
            chunk = await upload.read(self._chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
            if hasher.size_bytes > self._max_bytes:
                raise InvalidValueError(f"file exceeds the {self._max_bytes} byte limit")
        if hasher.size_bytes == 0:
            raise InvalidValueError("file is empty")
        await upload.seek(0)
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
        body = SpooledUploadBody(
            upload.file,  # type: ignore[attr-defined]
            size_bytes=hasher.size_bytes,
            chunk_size=self._chunk_size,
        )
        return PreparedUpload(request=request, body=body)


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
