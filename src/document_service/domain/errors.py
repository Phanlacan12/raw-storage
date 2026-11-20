"""Lỗi nghiệp vụ và lỗi phụ thuộc, dùng thay cho mã HTTP trong lõi.

Lớp inbound chịu trách nhiệm dịch sang mã HTTP (xem adapter/inbound/http).
"""

from __future__ import annotations


class DomainError(Exception):
    """Lỗi gốc của miền nghiệp vụ."""


class SchemaNotReadyError(DomainError):
    """Schema của catalog chưa đủ điều kiện để service nhận việc."""


class InvalidValueError(DomainError):
    """Giá trị đầu vào không hợp lệ."""


class DocumentNotFoundError(DomainError):
    """Không tìm thấy tài liệu hoặc phiên bản được yêu cầu."""


class ChecksumMismatchError(DomainError):
    """Dữ liệu trong kho object khác checksum của intent."""


class DuplicateContentError(DomainError):
    """Nội dung trùng với một phiên bản đã có của cùng tài liệu (bất biến I8)."""


class VersionLabelConflictError(DomainError):
    """Nhãn phiên bản đã tồn tại trong tài liệu (bất biến I2)."""


class StatusTransitionError(DomainError):
    """Chuyển trạng thái không được phép (bất biến I4, I5)."""


class RelationshipRebindError(DomainError):
    """Quan hệ bị đổi đích sang phiên bản khác (bất biến I6)."""


class PolicyDeniedError(DomainError):
    """Chủ thể không có quyền thực hiện hành động."""


class ConcurrencyConflictError(DomainError):
    """Điều kiện tiền đề đã thay đổi, người gọi phải đọc lại và thử lại."""


class DependencyUnavailableError(DomainError):
    """Phụ thuộc ngoài không khả dụng sau khi đã retry trong hạn deadline."""

    def __init__(
        self, dependency: str, message: str = "", retry_after_seconds: float = 1.0
    ) -> None:
        """Ghi lại tên phụ thuộc và khoảng thời gian nên thử lại."""
        super().__init__(message or f"dependency {dependency} is unavailable")
        self.dependency = dependency
        self.retry_after_seconds = retry_after_seconds


class ServiceDegradedError(DomainError):
    """Hành động bị chặn vì service đang ở chế độ suy giảm (mục 10.4)."""

    def __init__(self, mode: str, action: str) -> None:
        """Ghi lại chế độ hiện tại và hành động bị chặn."""
        super().__init__(f"action {action} is unavailable in {mode} mode")
        self.mode = mode
        self.action = action


class CatalogBypassError(DomainError):
    """Phát hiện ghi trường kiểm soát không đi qua Document Service (POC-20)."""
