"""Domain service giữ các bất biến I1–I9 và I14.

Tham chiếu docs/c4-04b-code-structure.md mục 3 và docs/c4-04-code-data-model.md
mục 4.2. Đây là nơi duy nhất quyết định một phiên bản mới có được tạo không, một
chuyển trạng thái có hợp lệ không và một quan hệ có được phép ghi không.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from document_service.domain.dto import UploadRequest
from document_service.domain.errors import (
    DomainError,
    DuplicateContentError,
    RelationshipRebindError,
    StatusTransitionError,
)
from document_service.domain.model import (
    ApprovalResult,
    Document,
    DocumentVersion,
    Relationship,
)
from document_service.domain.value import (
    Actor,
    Checksum,
    DocumentStatus,
    DocumentVersionId,
    StorageUri,
    VersionLabel,
)
from document_service.utils.ids import IdGenerator, UlidGenerator


class DomainPolicy(ABC):
    """Base class của mọi domain service giữ bất biến.

    Base chịu hai việc dùng chung: đặt tên policy cho log/audit, và phát lỗi miền
    đúng loại qua `_require`, để lớp con không lặp lại mẫu `if ...: raise ...`.
    """

    @abstractmethod
    def policy_name(self) -> str:
        """Tên policy, dùng trong log và thông điệp lỗi."""

    def _require(self, condition: bool, error: DomainError) -> None:
        """Phát lỗi miền nếu điều kiện không thoả."""
        if not condition:
            raise error


class DedupPolicy(DomainPolicy):
    """Phát hiện nội dung trùng trong phạm vi một tài liệu (bất biến I8, I9)."""

    def policy_name(self) -> str:
        """Tên policy."""
        return "dedup"

    def duplicate_of(self, document: Document, checksum: Checksum) -> DocumentVersion | None:
        """Phiên bản đã có cùng checksum trong chính tài liệu này.

        Hai tài liệu khác nhau có thể cùng checksum mà vẫn giữ document_id riêng,
        nên phép so sánh chỉ xét trong một tài liệu.
        """
        return document.version_with_checksum(checksum)

    def assert_not_duplicate(self, document: Document, checksum: Checksum) -> None:
        """Báo lỗi nếu nội dung đã tồn tại trong tài liệu."""
        existing = self.duplicate_of(document, checksum)
        self._require(
            existing is None,
            DuplicateContentError(
                f"nội dung đã có trong tài liệu {document.document_id}"
            ),
        )


class VersionPolicy(DomainPolicy):
    """Sinh phiên bản nội dung mới (bất biến I1, I2, I3, I8)."""

    def __init__(
        self,
        bucket: str,
        id_generator: IdGenerator | None = None,
        dedup: DedupPolicy | None = None,
    ) -> None:
        """Nhận bucket lưu object, bộ sinh ID và policy chống trùng."""
        self._bucket = bucket
        self._ids = id_generator or UlidGenerator()
        self._dedup = dedup or DedupPolicy()

    def policy_name(self) -> str:
        """Tên policy."""
        return "version"

    def reject_if_duplicate_content(self, document: Document, checksum: Checksum) -> None:
        """Chặn upload lại cùng nội dung vào cùng tài liệu."""
        self._dedup.assert_not_duplicate(document, checksum)

    def next_version(self, document: Document, request: UploadRequest) -> DocumentVersion:
        """Dựng phiên bản mới ở trạng thái Draft, chưa gắn vào tài liệu.

        ID phiên bản không phụ thuộc version_label, tên file hay collection; nhãn
        được sinh tự động nếu người gọi không truyền.
        """
        label = request.label or self._next_label(document)
        document.assert_label_unique(label)
        version_id = DocumentVersionId(self._ids.new_id(prefix="VER"))
        return DocumentVersion(
            version_id=version_id,
            document_id=document.document_id,
            label=label,
            checksum=request.checksum,
            storage_uri=StorageUri.for_version(self._bucket, document.document_id, version_id),
            original_file_name=request.original_file_name,
            content_format=request.content_format,
            size_bytes=request.size_bytes,
            status=DocumentStatus.DRAFT,
            created_by=request.actor.principal_id,
        )

    def _next_label(self, document: Document) -> VersionLabel:
        """Sinh nhãn kế tiếp dạng v1, v2, ... khi người gọi không chỉ định."""
        index = len(document.versions) + 1
        label = VersionLabel(f"v{index}")
        while any(version.label == label for version in document.versions):
            index += 1
            label = VersionLabel(f"v{index}")
        return label


class LifecyclePolicy(DomainPolicy):
    """Thực thi máy trạng thái Draft → Approved → Obsolete (bất biến I4, I5, I14)."""

    def policy_name(self) -> str:
        """Tên policy."""
        return "lifecycle"

    def assert_at_most_one_approved(self, document: Document) -> None:
        """Báo lỗi nếu tài liệu có nhiều hơn một bản Approved."""
        approved = [version for version in document.versions if version.is_approved]
        self._require(
            len(approved) <= 1,
            StatusTransitionError(
                f"tài liệu {document.document_id} có {len(approved)} bản Approved"
            ),
        )

    def approve(
        self, document: Document, version_id: DocumentVersionId, actor: Actor
    ) -> ApprovalResult:
        """Duyệt một phiên bản và hạ bản trước đó xuống Obsolete."""
        self.assert_at_most_one_approved(document)
        result = document.approve(version_id, actor)
        self.assert_at_most_one_approved(document)
        return result

    def transition(
        self,
        document: Document,
        version_id: DocumentVersionId,
        target: DocumentStatus,
        actor: Actor,
    ) -> ApprovalResult:
        """Chuyển trạng thái một phiên bản theo yêu cầu đã được phân quyền."""
        if target is DocumentStatus.APPROVED:
            return self.approve(document, version_id, actor)
        if target is DocumentStatus.OBSOLETE:
            return ApprovalResult(approved=document.obsolete(version_id, actor))
        raise StatusTransitionError(f"không hỗ trợ chuyển về trạng thái {target}")

    def current_version_fields(self, document: Document) -> dict[str, str]:
        """Trường bản hiện hành cần ghi vào catalog sau khi duyệt (bất biến I14)."""
        current = document.current_version_id
        return {"current_version_id": str(current) if current is not None else ""}


class RelationshipPolicy(DomainPolicy):
    """Kiểm tra quan hệ giữa hai phiên bản (bất biến I6, I7)."""

    def policy_name(self) -> str:
        """Tên policy."""
        return "relationship"

    def validate(self, relationship: Relationship) -> None:
        """Hai đầu phải là phiên bản khác nhau và loại quan hệ phải hợp lệ."""
        relationship.assert_both_ends_are_versions()

    def assert_target_not_rebound(
        self, relationship: Relationship, existing: list[Relationship]
    ) -> None:
        """Chặn việc đổi đích của một quan hệ đã khai báo.

        Quan hệ gắn đúng phiên bản ở cả hai đầu và không tự chuyển sang phiên bản
        mới; muốn trỏ tới phiên bản khác thì phải khai báo một quan hệ mới.
        """
        for item in existing:
            same_edge = (
                item.relation_type == relationship.relation_type
                and item.source_version_id == relationship.source_version_id
            )
            if same_edge and item.target_version_id != relationship.target_version_id:
                raise RelationshipRebindError(
                    f"quan hệ {relationship.relation_type} từ {relationship.source_version_id} "
                    f"đã trỏ tới {item.target_version_id}"
                )
