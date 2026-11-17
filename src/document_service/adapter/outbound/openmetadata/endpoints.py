"""Đường dẫn API của OpenMetadata và bộ dựng FQN.

Tập trung ở một chỗ để đối chiếu với OpenAPI của **phiên bản được cố định** trước khi
chạy thật, theo cảnh báo ở đầu docs/c4-04b-code-structure.md và bảng mục 5. Không
rải chuỗi URL trong các lớp khác.
"""

from __future__ import annotations

from document_service.domain.value import DocumentId, DocumentVersionId

API_PREFIX = "/api/v1"

SYSTEM_VERSION = f"{API_PREFIX}/system/version"
DRIVE_SERVICES = f"{API_PREFIX}/services/driveServices"
DIRECTORIES = f"{API_PREFIX}/drives/directories"
DIRECTORY_BY_NAME = f"{DIRECTORIES}/name"
FILES = f"{API_PREFIX}/drives/files"
FILE_BY_NAME = f"{FILES}/name"
LINEAGE = f"{API_PREFIX}/lineage"
LINEAGE_GET = f"{API_PREFIX}/lineage/getLineage"
SEARCH_QUERY = f"{API_PREFIX}/search/query"
METADATA_TYPES = f"{API_PREFIX}/metadata/types"

JSON_PATCH_CONTENT_TYPE = "application/json-patch+json"
FILE_SEARCH_INDEX = "file_search_index"


class OmFqnBuilder:
    """Dựng fullyQualifiedName theo quy ước của kho.

    FQN là khóa định danh ổn định phía OpenMetadata, và luôn dựng từ `document_id`
    và `document_version_id` — không dùng tên file hay version_label, để đổi tên tài
    liệu không làm đổi vị trí entity (bất biến I1).
    """

    def __init__(self, service_name: str, root_directory: str) -> None:
        """Nhận tên drive service và thư mục gốc của kho."""
        self._service = service_name
        self._root = root_directory

    @property
    def service_fqn(self) -> str:
        """FQN của drive service."""
        return self._service

    @property
    def root_fqn(self) -> str:
        """FQN của thư mục gốc."""
        return f"{self._service}.{self._root}"

    def collection_fqn(self, collection_id: str) -> str:
        """FQN của một collection."""
        return f"{self.root_fqn}.{collection_id}"

    def document_fqn(self, document_id: DocumentId) -> str:
        """FQN của directory đại diện tài liệu."""
        return f"{self.root_fqn}.{document_id}"

    def version_fqn(self, document_id: DocumentId, version_id: DocumentVersionId) -> str:
        """FQN của File entity đại diện một phiên bản nội dung."""
        return f"{self.document_fqn(document_id)}.{version_id}"

    def document_name(self, document_id: DocumentId) -> str:
        """Tên entity của tài liệu."""
        return str(document_id)

    def version_name(self, version_id: DocumentVersionId) -> str:
        """Tên entity của phiên bản."""
        return str(version_id)
