"""Test D4 UploadHandler sau B16.

Khẳng định sau refactor:

- Không gom cả file vào RAM (X7). `PreparedUpload` không có thuộc tính `payload`.
- `stream_factory` đọc lại được nhiều lần cho retry của executor.
- `aclose()` đóng file-like nền.
- **X55:** handler không trích xuất nội dung — không có trường metadata nào
  đến từ parse PDF/MIME, kể cả khi bytes bắt đầu bằng `%PDF-`.
"""

from __future__ import annotations

import io

import pytest

from document_service.adapter.inbound.http.upload_handler import PreparedUpload, UploadHandler
from document_service.config import StorageSettings
from document_service.domain.errors import InvalidValueError
from document_service.domain.model import Principal
from document_service.domain.value import DocumentId, IdempotencyKey


class _SpooledLike:
    """Giả `UploadFile` của Starlette: có `read`, `seek`, `file`, `filename`, `content_type`."""

    def __init__(self, data: bytes, filename: str, content_type: str) -> None:
        """Nhận dữ liệu, tên và kiểu MIME khai báo."""
        self.file = io.BytesIO(data)
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        """Đọc tối đa `size` byte."""
        return self.file.read(size)

    async def seek(self, offset: int) -> None:
        """Đặt lại con trỏ."""
        self.file.seek(offset)


@pytest.fixture
def principal() -> Principal:
    """Chủ thể giả cho upload."""
    return Principal(principal_id="user-1", groups=("g1",), is_admin=False)


@pytest.fixture
def handler() -> UploadHandler:
    """UploadHandler với giới hạn mặc định."""
    return UploadHandler(StorageSettings(multipart_part_bytes=16, max_upload_bytes=1024))


async def test_prepare_does_not_buffer_payload_field(
    handler: UploadHandler, principal: Principal
) -> None:
    """`PreparedUpload` không có field `payload` bytes nữa (X7)."""
    data = b"hello world " * 10
    upload = _SpooledLike(data, "a.bin", "application/octet-stream")
    prepared: PreparedUpload = await handler.prepare(
        DocumentId("DOC-1"), upload, principal, IdempotencyKey("key-upload-1")
    )
    assert not hasattr(prepared, "payload")
    assert prepared.body.size_bytes == len(data)


async def test_stream_factory_replayable_across_retries(
    handler: UploadHandler, principal: Principal
) -> None:
    """Factory phải đọc lại được — executor retry gọi lại nó."""
    data = b"abcdefg" * 20
    upload = _SpooledLike(data, "a.bin", "application/octet-stream")
    prepared = await handler.prepare(
        DocumentId("DOC-1"), upload, principal, IdempotencyKey("key-upload-2")
    )

    async def collect() -> bytes:
        return b"".join([chunk async for chunk in prepared.stream_factory()])

    first = await collect()
    second = await collect()
    assert first == data
    assert second == data
    await prepared.aclose()


async def test_prepare_does_not_parse_content(handler: UploadHandler, principal: Principal) -> None:
    """X55: handler không đọc nội dung — chỉ metadata kỹ thuật.

    Bytes bắt đầu bằng magic PDF nhưng là rác; metadata chỉ gồm tên/định dạng
    client khai, size, checksum. Không có trường `pages`, `author`, `title`,
    hay bất kỳ dữ liệu trích xuất từ nội dung nào.
    """
    body = b"%PDF-1.4\nnhung day la rac, khong phai PDF that\n%%EOF"
    upload = _SpooledLike(body, "fake.pdf", "application/octet-stream")
    prepared = await handler.prepare(
        DocumentId("DOC-55"), upload, principal, IdempotencyKey("key-upload-55")
    )
    request = prepared.request
    assert request.original_file_name == "fake.pdf"
    assert request.content_format == "application/octet-stream"
    assert request.size_bytes == len(body)
    # Nếu D23 nào đó lén thêm trường trích xuất nội dung, assert dưới đỏ.
    forbidden = {"pages", "author", "title_from_content", "text", "extracted_text"}
    present = (
        set(request.__dataclass_fields__.keys())
        if hasattr(request, "__dataclass_fields__")
        else set(vars(request))
    )
    assert forbidden.isdisjoint(
        present
    ), f"UploadRequest leaked content fields: {forbidden & present}"
    await prepared.aclose()


async def test_prepare_rejects_oversize(principal: Principal) -> None:
    """Giới hạn kích thước vẫn được áp qua StreamingHasher, không chờ đủ file."""
    tiny = UploadHandler(StorageSettings(max_upload_bytes=8, multipart_part_bytes=4))
    upload = _SpooledLike(b"x" * 100, "big.bin", "application/octet-stream")
    with pytest.raises(InvalidValueError):
        await tiny.prepare(DocumentId("DOC-X"), upload, principal, IdempotencyKey("key-upload-xx"))
