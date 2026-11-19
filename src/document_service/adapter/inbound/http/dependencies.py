"""Dependency của FastAPI: container, chủ thể, idempotency key, cổng suy giảm.

Container là điểm wiring duy nhất (quy tắc R2), nên route không tự khởi tạo adapter
hay use case: nó lấy qua các hàm ở đây.
"""

from __future__ import annotations

from fastapi import Header, Request

from document_service.adapter.inbound.http.upload_handler import IdempotencyKeyFilter, UploadHandler
from document_service.domain.model import Principal
from document_service.domain.value import Action, IdempotencyKey
from document_service.infrastructure.container import ServiceContainer


def get_container() -> ServiceContainer:
    """Container đang chạy."""
    return ServiceContainer()


def get_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Principal:
    """Chủ thể gọi API, xác thực theo cấu hình bảo mật."""
    container = get_container()
    resolver = container.resolver
    return resolver.resolve(authorization, dict(request.headers))


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IdempotencyKey:
    """Bắt buộc `Idempotency-Key` cho mọi endpoint ghi (bất biến I13)."""
    container = get_container()
    filter_ = IdempotencyKeyFilter(container.settings.security.require_idempotency_key)
    return filter_.resolve(idempotency_key)


def get_upload_handler() -> UploadHandler:
    """Handler nhận file upload (D4)."""
    return UploadHandler()


def require_write_mode() -> None:
    """Chặn hành động ghi khi service đang ở chế độ suy giảm (mục 10.4)."""
    get_container().gate.assert_allowed(Action.WRITE)


def require_read_mode() -> None:
    """Chặn đọc metadata khi chỉ còn khả năng cấp file từ cache."""
    get_container().gate.assert_allowed(Action.VIEW_METADATA)


def require_download_mode() -> None:
    """Chặn tải file khi chế độ hiện tại không cho phép."""
    get_container().gate.assert_allowed(Action.DOWNLOAD)
