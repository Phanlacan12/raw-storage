"""Dịch lỗi miền sang mã HTTP (mục 12 của docs/c4-04b-code-structure.md).

Quy ước: `409` khi điều kiện tiền đề đã đổi, `503` kèm `Retry-After` khi phụ thuộc
tạm thời không khả dụng hoặc service đang ở chế độ suy giảm — **không** trả `500`, để
client phân biệt được sự cố tạm thời với lỗi dữ liệu.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from document_service.domain.errors import (
    CatalogBypassError,
    ConcurrencyConflictError,
    DependencyUnavailableError,
    DocumentNotFoundError,
    DomainError,
    DuplicateContentError,
    InvalidValueError,
    PolicyDeniedError,
    RelationshipRebindError,
    ServiceDegradedError,
    StatusTransitionError,
    VersionLabelConflictError,
)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    InvalidValueError: 422,
    DocumentNotFoundError: 404,
    PolicyDeniedError: 403,
    CatalogBypassError: 403,
    DuplicateContentError: 200,
    VersionLabelConflictError: 409,
    StatusTransitionError: 409,
    RelationshipRebindError: 409,
    ConcurrencyConflictError: 409,
    DependencyUnavailableError: 503,
    ServiceDegradedError: 503,
}


class DomainErrorTranslator:
    """Chuyển lỗi miền thành JSONResponse."""

    def status_for(self, error: DomainError) -> int:
        """Mã HTTP tương ứng một lỗi miền, mặc định 400."""
        for error_type, status in STATUS_BY_ERROR.items():
            if isinstance(error, error_type):
                return status
        return 400

    def to_response(self, error: DomainError) -> JSONResponse:
        """Response JSON cho một lỗi miền, kèm Retry-After khi cần."""
        status = self.status_for(error)
        payload: dict[str, object] = {
            "error": type(error).__name__,
            "message": str(error),
        }
        headers: dict[str, str] = {}
        if isinstance(error, DependencyUnavailableError):
            payload["dependency"] = error.dependency
            headers["Retry-After"] = str(int(error.retry_after_seconds) or 1)
        if isinstance(error, ServiceDegradedError):
            payload["service_mode"] = error.mode
            headers["Retry-After"] = "5"
        return JSONResponse(status_code=status, content=payload, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    """Gắn handler dịch lỗi miền vào ứng dụng FastAPI."""
    translator = DomainErrorTranslator()

    @app.exception_handler(DomainError)
    async def _handle_domain_error(_: Request, error: Exception) -> JSONResponse:
        """Trả response tương ứng lỗi miền."""
        assert isinstance(error, DomainError)
        return translator.to_response(error)
