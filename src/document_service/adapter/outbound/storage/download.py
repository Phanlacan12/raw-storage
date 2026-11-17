"""Hai đường cấp file: link có thời hạn và proxy qua dịch vụ (D10).

Theo mục 2.6 báo cáo và test case POC-23. Tách thành hai lớp để chỗ nào trong hệ
thống cũng thấy rõ **chúng không tương đương nhau**:

- `PresignedUrlIssuer`: rẻ, không chiếm băng thông của service, nhưng link đã phát
  hành **không** mất hiệu lực khi quyền thay đổi; cửa sổ rủi ro bằng TTL.
- `ProxyStreamer`: tốn băng thông của service, nhưng mỗi byte đi qua điểm kiểm tra
  quyền, nên thu hồi có hiệu lực ngay. Dùng cho tài liệu yêu cầu thu hồi tức thời.
"""

from __future__ import annotations

from datetime import timedelta
from typing import AsyncIterator

from document_service.domain.port import ObjectStorePort
from document_service.domain.value import StorageUri


class PresignedUrlIssuer:
    """Cấp link tải có thời hạn cho tài liệu thông thường."""

    def __init__(self, objects: ObjectStorePort, default_ttl_seconds: int = 300) -> None:
        """Nhận object store và thời hạn mặc định."""
        self._objects = objects
        self._default_ttl = default_ttl_seconds

    @property
    def default_ttl_seconds(self) -> int:
        """Thời hạn mặc định của link."""
        return self._default_ttl

    async def issue(self, uri: StorageUri, ttl_seconds: int | None = None) -> str:
        """Cấp link tải; TTL là cửa sổ rủi ro khi quyền bị thu hồi (POC-23)."""
        seconds = ttl_seconds or self._default_ttl
        return await self._objects.presign(uri, timedelta(seconds=seconds))


class ProxyStreamer:
    """Đẩy nội dung file qua dịch vụ để thu hồi quyền có hiệu lực ngay."""

    def __init__(self, objects: ObjectStorePort) -> None:
        """Nhận object store."""
        self._objects = objects

    def stream(self, uri: StorageUri) -> AsyncIterator[bytes]:
        """Luồng đọc object, dùng cho tài liệu cần thu hồi tức thời."""
        return self._objects.open_stream(uri)
