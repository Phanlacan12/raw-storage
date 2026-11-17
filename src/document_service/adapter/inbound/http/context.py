"""Context của một request HTTP.

Gom các dependency hay dùng (container, chủ thể, idempotency key, upload handler, tham
số tìm kiếm) thành object để endpoint không nhận hàng loạt tham số rời. Đây cũng là
cách giữ `max-args` của pylint mà không làm hợp đồng API ở mục 12 thay đổi.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Query

from document_service.adapter.inbound.http.dependencies import (
    get_container,
    get_principal,
    get_upload_handler,
    require_idempotency_key,
)
from document_service.adapter.inbound.http.upload_handler import UploadHandler
from document_service.domain.dto import SearchFilter, SearchQuery
from document_service.domain.model import Principal
from document_service.domain.value import DocumentStatus, IdempotencyKey
from document_service.infrastructure.container import ServiceContainer


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Phần context mọi endpoint đều cần."""

    container: ServiceContainer
    principal: Principal


@dataclass(frozen=True, slots=True)
class WriteContext:
    """Context của endpoint ghi: thêm idempotency key."""

    container: ServiceContainer
    principal: Principal
    idempotency_key: IdempotencyKey


@dataclass(frozen=True, slots=True)
class UploadContext:
    """Context của endpoint nhận file: thêm upload handler."""

    container: ServiceContainer
    principal: Principal
    idempotency_key: IdempotencyKey
    handler: UploadHandler


@dataclass(frozen=True, slots=True)
class SearchParams:
    """Tham số tìm kiếm, dịch sang `SearchQuery` của miền nghiệp vụ."""

    text: str = ""
    document_type: str | None = None
    status: DocumentStatus | None = None
    collection_id: str | None = None
    classification: str | None = None
    page_size: int = 20
    cursor: str | None = None

    def to_query(self) -> SearchQuery:
        """Dựng truy vấn với các điều kiện lọc đã khai báo."""
        candidates = (
            ("document_type", self.document_type),
            ("status", str(self.status) if self.status else None),
            ("collection_id", self.collection_id),
            ("classification", self.classification),
        )
        filters = tuple(
            SearchFilter(field_name=name, value=value) for name, value in candidates if value
        )
        return SearchQuery(
            text=self.text,
            filters=filters,
            page_size=self.page_size,
            cursor=self.cursor,
        )


def get_request_context(
    container: ServiceContainer = Depends(get_container),
    principal: Principal = Depends(get_principal),
) -> RequestContext:
    """Context cho endpoint đọc."""
    return RequestContext(container=container, principal=principal)


def get_write_context(
    container: ServiceContainer = Depends(get_container),
    principal: Principal = Depends(get_principal),
    idempotency_key: IdempotencyKey = Depends(require_idempotency_key),
) -> WriteContext:
    """Context cho endpoint ghi."""
    return WriteContext(container=container, principal=principal, idempotency_key=idempotency_key)


def get_upload_context(
    container: ServiceContainer = Depends(get_container),
    principal: Principal = Depends(get_principal),
    idempotency_key: IdempotencyKey = Depends(require_idempotency_key),
    handler: UploadHandler = Depends(get_upload_handler),
) -> UploadContext:
    """Context cho endpoint nhận file."""
    return UploadContext(
        container=container,
        principal=principal,
        idempotency_key=idempotency_key,
        handler=handler,
    )


class SearchParamsProvider:
    """Đọc tham số tìm kiếm từ query string.

    Viết thành lớp callable thay vì hàm nhiều tham số: FastAPI vẫn sinh đúng tài liệu
    OpenAPI, còn chữ ký hàm không vượt giới hạn tham số của pylint.
    """

    async def __call__(
        self,
        text: str = Query(default=""),
        document_type: str | None = Query(default=None),
        status: DocumentStatus | None = Query(default=None),
        collection_id: str | None = Query(default=None),
        classification: str | None = Query(default=None),
    ) -> SearchParams:
        """Dựng SearchParams từ các điều kiện lọc."""
        return SearchParams(
            text=text,
            document_type=document_type,
            status=status,
            collection_id=collection_id,
            classification=classification,
        )


get_search_params = SearchParamsProvider()
