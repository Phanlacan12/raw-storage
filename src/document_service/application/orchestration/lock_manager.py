"""DocumentLockManager: tuần tự hoá thao tác trên cùng một tài liệu.

Nguyên tắc ở mục 11.3 của docs/c4-04b-code-structure.md: **không retry khi đang giữ
khóa**. Khóa chỉ bọc các lời gọi ngắn; lỗi bên trong làm nhả khóa ngay để thao tác
khác trên cùng tài liệu không bị chặn, phần phục hồi do IntentRecoveryJob lo.
"""

from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

from document_service.domain.port import DocumentLockPort
from document_service.domain.value import DocumentId

T = TypeVar("T")


class DocumentLockManager:
    """Lớp mỏng trên DocumentLockPort, thêm log và một điểm vào duy nhất."""

    def __init__(self, locks: DocumentLockPort) -> None:
        """Nhận port khóa đang được cấu hình."""
        self._locks = locks

    async def run_exclusive(
        self, document_id: DocumentId, operation: Callable[[], Awaitable[T]]
    ) -> T:
        """Chạy thao tác trong khóa của một tài liệu."""
        return await self._locks.with_lock(document_id, operation)
