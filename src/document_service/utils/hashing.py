"""Tính checksum theo luồng, không nạp toàn bộ file vào bộ nhớ.

Dùng cho D4 Upload Handler và D5 Checksum & Dedup, và cho job đối soát toàn vẹn.
"""

from __future__ import annotations

import hashlib
from typing import AsyncIterator, Iterable

DEFAULT_ALGORITHM = "sha256"
DEFAULT_CHUNK_SIZE = 1024 * 1024


class StreamingHasher:
    """Tính checksum và đếm kích thước trong khi dữ liệu đi qua."""

    def __init__(self, algorithm: str = DEFAULT_ALGORITHM) -> None:
        """Khởi tạo với thuật toán băm cho trước."""
        self._algorithm = algorithm
        self._digest = hashlib.new(algorithm)
        self._size = 0

    @property
    def algorithm(self) -> str:
        """Thuật toán đang dùng."""
        return self._algorithm

    @property
    def size_bytes(self) -> int:
        """Tổng số byte đã đi qua."""
        return self._size

    def update(self, chunk: bytes) -> None:
        """Nạp thêm một khối dữ liệu."""
        self._digest.update(chunk)
        self._size += len(chunk)

    def hex_digest(self) -> str:
        """Chuỗi hex của checksum."""
        return self._digest.hexdigest()

    def consume(self, chunks: Iterable[bytes]) -> StreamingHasher:
        """Nạp toàn bộ dữ liệu từ một iterable đồng bộ."""
        for chunk in chunks:
            self.update(chunk)
        return self

    async def consume_async(self, chunks: AsyncIterator[bytes]) -> StreamingHasher:
        """Nạp toàn bộ dữ liệu từ một iterator bất đồng bộ."""
        async for chunk in chunks:
            self.update(chunk)
        return self


def digest_of(data: bytes, algorithm: str = DEFAULT_ALGORITHM) -> str:
    """Checksum của một khối dữ liệu đã nằm trong bộ nhớ."""
    hasher = StreamingHasher(algorithm)
    hasher.update(data)
    return hasher.hex_digest()
