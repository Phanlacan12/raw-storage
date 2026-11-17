"""Tên trường metadata dùng chung và danh sách trường bắt buộc lọc được.

Đặt ở `domain` vì đây là khái niệm nghiệp vụ, không phải chi tiết của sản phẩm nào:
mục 2.3 báo cáo quy định bộ metadata, còn POC-19 quy định những trường **phải** lọc
được qua Search API. Cả `config.py` và lớp dựng metadata đều đọc từ đây, nên danh
sách chỉ tồn tại một bản.
"""

from __future__ import annotations

DOCUMENT_ID = "document_id"
DOCUMENT_VERSION_ID = "document_version_id"
DOCUMENT_TYPE = "document_type"
STATUS = "status"
CLASSIFICATION = "classification"
COLLECTION_ID = "collection_id"
VERSION_LABEL = "version_label"

FILTERABLE_FIELDS: tuple[str, ...] = (
    DOCUMENT_TYPE,
    STATUS,
    CLASSIFICATION,
    COLLECTION_ID,
    VERSION_LABEL,
)

DESCRIPTIVE_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    DOCUMENT_TYPE,
    "tags",
    "language",
    "owner",
    "department",
    COLLECTION_ID,
)
