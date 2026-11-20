"""Phân trang sau khi lọc quyền xem metadata."""

from dataclasses import replace

from document_service.adapter.inbound.http.schemas import SearchResponse
from document_service.domain.dto import SearchHit, SearchPage
from document_service.domain.model import AccessPolicy, DocumentMetadata, Principal
from document_service.domain.value import DocumentId, DocumentStatus, DocumentVersionId


def test_search_page_preserves_cursor_and_catalog_total_after_filtering() -> None:
    """Một trang rỗng hoặc chỉ hiện một phần vẫn giữ con trỏ trang kế tiếp."""
    restricted = SearchHit(
        DocumentVersionId("version-01"),
        DocumentId("document-01"),
        DocumentStatus.DRAFT,
        DocumentMetadata(),
    )
    public = replace(restricted, access_policy=AccessPolicy(classification="public"))
    for hits, expected in [((restricted,), 0), ((restricted, public), 1)]:
        page = SearchPage(hits=hits, next_cursor="page-2", total_hits=17)
        response = SearchResponse.from_domain(page.filtered(Principal("reader")))
        assert response.total_hits == 17
        assert response.visible_hits == len(response.hits) == expected
        assert response.next_cursor == "page-2"
