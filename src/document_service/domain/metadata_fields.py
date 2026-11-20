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
    "owner",
    "title",
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

# Mọi key được ghi vào `extension`. Khác với FILTERABLE_FIELDS: đó là tập con *phải
# lọc được* (POC-19), còn đây là tập *phải đăng ký trước*. OpenMetadata từ chối ghi
# một key chưa đăng ký với `400 Unknown custom field <tên>`, nên thiếu một tên ở đây
# là hỏng ngay lệnh ghi đầu tiên. `tests/unit/test_metadata_fields.py` so hai tuple
# này với output thật của CatalogMetadataBuilder để chúng không trôi khỏi nhau.
VERSION_FIELDS: tuple[str, ...] = DESCRIPTIVE_FIELDS + (
    DOCUMENT_ID,
    DOCUMENT_VERSION_ID,
    "original_file_name",
    "approved_at",
    "approved_by",
    "obsoleted_at",
    "obsoleted_by",
    VERSION_LABEL,
    STATUS,
    CLASSIFICATION,
    "format",
    "size",
    "checksum",
    "storage_uri",
)

DOCUMENT_FIELDS: tuple[str, ...] = DESCRIPTIVE_FIELDS + (
    "collection_type",
    "parent_collection_id",
    DOCUMENT_ID,
    CLASSIFICATION,
    "retention_policy",
    "current_version_id",
    "access_policy",
)

# `size` là số byte, gửi dạng int. Các trường còn lại là chuỗi (list được
# `OmExtensionMapper.to_extension` nối bằng dấu phẩy trước khi gửi đi).
INTEGER_FIELDS: frozenset[str] = frozenset({"size"})
