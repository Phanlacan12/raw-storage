"""Tiện ích thao tác đường dẫn cục bộ và body upload đọc lại được."""

from __future__ import annotations

from pathlib import Path
from typing import IO, AsyncIterator

_DEFAULT_CHUNK_SIZE = 1024 * 1024


class SpooledUploadBody:
    """Body đọc lại được: bọc một file nhị phân seekable + kích thước đã đo.

    Dùng cho đường upload HTTP (B16): `UploadFile` của Starlette đã là một
    `SpooledTemporaryFile`, nên sau khi đọc để tính checksum chỉ cần `seek(0)`
    và bọc lại ở đây, không nhân đôi dữ liệu vào RAM. `chunks()` phải đọc lại
    được nhiều lần vì `ResilientCallExecutor` retry bên trong `put_immutable`.
    """

    def __init__(
        self,
        file: IO[bytes],
        size_bytes: int,
        chunk_size: int = _DEFAULT_CHUNK_SIZE,
    ) -> None:
        """Nhận file-like seekable, kích thước đã đo và độ lớn mỗi chunk."""
        self._file = file
        self._size_bytes = size_bytes
        self._chunk_size = chunk_size
        self._closed = False

    @property
    def size_bytes(self) -> int:
        """Kích thước nội dung đã đo trước đó."""
        return self._size_bytes

    def chunks(self) -> AsyncIterator[bytes]:
        """Trả về iterator bất đồng bộ đọc lại nội dung từ đầu file."""
        chunk_size = self._chunk_size
        file = self._file

        async def iterator() -> AsyncIterator[bytes]:
            if self._closed:
                return
            file.seek(0)
            while True:
                data = file.read(chunk_size)
                if not data:
                    return
                yield data

        return iterator()

    async def aclose(self) -> None:
        """Đóng file-like gốc, bỏ qua lỗi lặp lại."""
        if self._closed:
            return
        self._closed = True
        try:
            self._file.close()
        except Exception:  # pylint: disable=broad-exception-caught
            pass


class LocalPaths:
    """Chuẩn bị đường dẫn cục bộ trước khi mở file."""

    def ensure_parent(self, path: str | Path) -> Path:
        """Tạo thư mục cha nếu chưa có và trả về đường dẫn đầy đủ."""
        resolved = Path(path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def ensure_dir(self, path: str | Path) -> Path:
        """Tạo thư mục nếu chưa có và trả về đường dẫn."""
        resolved = Path(path).expanduser()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
