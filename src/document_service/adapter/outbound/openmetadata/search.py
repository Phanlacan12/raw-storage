"""Dựng truy vấn và đọc kết quả Search API của OpenMetadata.

Theo mục 8 của docs/c4-04b-code-structure.md. Lọc tổ hợp thực hiện bằng `query_filter`
trên `extension.<field>`; UI facet cho custom property là **giới hạn đã biết** của sản
phẩm, nên ở đây chỉ cam kết đường API và ghi rõ phần nào phải làm thêm (POC-19).
"""

from __future__ import annotations

from typing import Any

from document_service.adapter.outbound.openmetadata.endpoints import FILE_SEARCH_INDEX
from document_service.adapter.outbound.openmetadata.entity import OmExtensionMapper
from document_service.domain.dto import SearchHit, SearchPage, SearchQuery
from document_service.domain.model import AccessPolicy
from document_service.domain.value import (
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    VersionLabel,
)
from document_service.utils.jsonx import JsonCodec


class OmSearchQueryBuilder:
    """Chuyển SearchQuery nghiệp vụ thành tham số của Search API."""

    def __init__(self, extensions: OmExtensionMapper | None = None) -> None:
        """Nhận mapper extension để biết đường dẫn trường."""
        self._extensions = extensions or OmExtensionMapper()
        self._codec = JsonCodec()

    def build(self, query: SearchQuery) -> dict[str, Any]:
        """Tham số truy vấn gồm chuỗi tìm, filter tổ hợp và phân trang.

        `query_filter` phải là **chuỗi JSON**: nếu truyền dict, client HTTP sẽ nối
        bằng `str(dict)` và server nhận một chuỗi dấu nháy đơn không phải JSON.
        """
        params: dict[str, Any] = {
            "q": query.text or "*",
            "index": FILE_SEARCH_INDEX,
            "size": query.page_size,
            "from": query.offset,
        }
        if query.filters:
            params["query_filter"] = self._codec.dumps(self._query_filter(query))
        return params

    def _query_filter(self, query: SearchQuery) -> dict[str, Any]:
        """Filter dạng bool/must trên các trường extension."""
        clauses = [
            {"term": {self._extensions.extension_field_path(item.field_name): item.value}}
            for item in query.filters
        ]
        return {"query": {"bool": {"must": clauses}}}


class OmSearchResultMapper:
    """Đọc kết quả Search API về SearchPage của kho."""

    def __init__(self, extensions: OmExtensionMapper | None = None) -> None:
        """Nhận mapper extension."""
        self._extensions = extensions or OmExtensionMapper()

    def to_page(self, payload: dict[str, Any], query: SearchQuery) -> SearchPage:
        """Chuyển payload Elasticsearch thành trang kết quả."""
        raw_hits = self._raw_hits(payload)
        hits = tuple(self._to_hit(item) for item in raw_hits if self._usable(item))
        total = self._total(payload)
        offset = query.offset
        next_offset = offset + len(raw_hits)
        next_cursor = str(next_offset) if raw_hits and next_offset < total else None
        return SearchPage(hits=hits, next_cursor=next_cursor, total_hits=total)

    def _raw_hits(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Danh sách `_source` của từng hit."""
        container = payload.get("hits", {})
        items = container.get("hits", []) if isinstance(container, dict) else []
        return [item.get("_source", {}) for item in items if isinstance(item, dict)]

    def _total(self, payload: dict[str, Any]) -> int:
        """Tổng số kết quả."""
        container = payload.get("hits", {})
        total = container.get("total", {}) if isinstance(container, dict) else {}
        if isinstance(total, dict):
            return int(total.get("value", 0) or 0)
        return int(total or 0)

    def _usable(self, source: dict[str, Any]) -> bool:
        """Hit có đủ trường bắt buộc để dựng kết quả hay không."""
        extension = self._extensions.from_extension(source.get("extension", {}))
        return bool(extension.get("document_id") and extension.get("document_version_id"))

    def _to_hit(self, source: dict[str, Any]) -> SearchHit:
        """Dựng một kết quả tìm kiếm từ `_source`."""
        raw_extension = source.get("extension", {})
        extension = self._extensions.from_extension(raw_extension)
        metadata = self._extensions.to_document_metadata(raw_extension)
        return SearchHit(
            version_id=DocumentVersionId(str(extension["document_version_id"])),
            document_id=DocumentId(str(extension["document_id"])),
            status=DocumentStatus(str(extension.get("status", DocumentStatus.DRAFT))),
            metadata=metadata,
            label=VersionLabel(str(extension.get("version_label", "v1"))),
            access_policy=AccessPolicy(
                classification=str(extension.get("classification", "restricted"))
            ),
        )
