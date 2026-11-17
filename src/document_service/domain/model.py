"""Thực thể nghiệp vụ: Collection, Document, DocumentVersion, Relationship, intent, audit.

Tham chiếu docs/c4-04-code-data-model.md mục 4.1 và 4.2. Hành vi giữ bất biến nằm
ngay trong thực thể, không nằm ở adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from document_service.domain.errors import (
    DocumentNotFoundError,
    RelationshipRebindError,
    StatusTransitionError,
    VersionLabelConflictError,
)
from document_service.domain.value import (
    Action,
    Actor,
    Checksum,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    IdempotencyKey,
    IntentState,
    RelationType,
    RequestId,
    StorageUri,
    VersionLabel,
)
from document_service.utils.clock import utc_now


def _now() -> datetime:
    """Thời điểm hiện tại theo UTC, lấy từ utils.clock để test thay thế được."""
    return utc_now()


@dataclass(frozen=True, slots=True)
class Principal:
    """Chủ thể gọi API: người dùng hoặc service account từ IdP."""

    principal_id: str
    groups: tuple[str, ...] = ()
    is_admin: bool = False

    def as_actor(self) -> Actor:
        """Chuyển sang Actor để ghi audit."""
        return Actor(principal_id=self.principal_id)


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """Chính sách truy cập gắn với tài liệu (mục 2.6 báo cáo)."""

    classification: str = "restricted"
    allowed_groups: tuple[str, ...] = ()
    allowed_principals: tuple[str, ...] = ()
    require_proxy_download: bool = False

    def permits(self, principal: Principal, action: Action) -> bool:
        """Cho biết chủ thể có được thực hiện hành động hay không.

        Mặc định là hạn chế: tài liệu chưa ánh xạ được quyền thì chỉ owner và
        quản trị viên được ủy quyền truy cập (bất biến I11).
        """
        if principal.is_admin:
            return True
        if principal.principal_id in self.allowed_principals:
            return True
        if set(principal.groups) & set(self.allowed_groups):
            return True
        return action is Action.VIEW_METADATA and self.classification == "public"


@dataclass(frozen=True, slots=True)
class DocumentMetadata:
    """Metadata mô tả và tổ chức, gắn với Document."""

    title: str = ""
    description: str = ""
    document_type: str = ""
    tags: tuple[str, ...] = ()
    language: str = ""
    owner: str = ""
    department: str = ""
    collection_id: str = ""


@dataclass(slots=True)
class Collection:
    """Nhóm quản lý tài liệu theo dự án, bộ phận hoặc domain."""

    collection_id: str
    name: str
    collection_type: str = "project"
    parent_collection_id: str | None = None
    owner: str = ""
    department: str = ""


@dataclass(slots=True)
class DocumentVersion:
    """Một phiên bản nội dung bất biến của tài liệu."""

    version_id: DocumentVersionId
    document_id: DocumentId
    label: VersionLabel
    checksum: Checksum
    storage_uri: StorageUri
    original_file_name: str
    content_format: str
    size_bytes: int
    status: DocumentStatus = DocumentStatus.DRAFT
    created_at: datetime = field(default_factory=_now)
    created_by: str = ""
    approved_at: datetime | None = None
    approved_by: str | None = None

    @property
    def is_approved(self) -> bool:
        """Phiên bản đang là bản được duyệt."""
        return self.status is DocumentStatus.APPROVED

    def mark_approved(self, actor: Actor, when: datetime | None = None) -> None:
        """Chuyển sang Approved, chỉ hợp lệ từ Draft (bất biến I4)."""
        if self.status is not DocumentStatus.DRAFT:
            raise StatusTransitionError(
                f"only Draft versions can be approved, version {self.version_id} is {self.status}"
            )
        self.status = DocumentStatus.APPROVED
        self.approved_at = when or _now()
        self.approved_by = actor.principal_id

    def mark_obsolete(self, actor: Actor, when: datetime | None = None) -> None:
        """Chuyển sang Obsolete từ Draft hoặc Approved."""
        if self.status is DocumentStatus.OBSOLETE:
            raise StatusTransitionError(f"version {self.version_id} is already Obsolete")
        self.status = DocumentStatus.OBSOLETE
        self.approved_by = self.approved_by or actor.principal_id
        self.approved_at = self.approved_at or when


@dataclass(slots=True)
class ApprovalResult:
    """Kết quả một lượt duyệt phiên bản."""

    approved: DocumentVersion
    obsoleted: DocumentVersion | None = None


@dataclass(slots=True)
class Document:
    """Tài liệu logic, tập hợp các phiên bản nội dung."""

    document_id: DocumentId
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    access_policy: AccessPolicy = field(default_factory=AccessPolicy)
    retention_policy: str = ""
    versions: list[DocumentVersion] = field(default_factory=list)
    current_version_id: DocumentVersionId | None = None
    created_at: datetime = field(default_factory=_now)

    def assert_label_unique(self, label: VersionLabel) -> None:
        """Bảo đảm version_label chưa tồn tại trong tài liệu (bất biến I2)."""
        if any(version.label == label for version in self.versions):
            raise VersionLabelConflictError(
                f"version_label {label} already exists in {self.document_id}"
            )

    def add_version(self, version: DocumentVersion) -> DocumentVersion:
        """Thêm một phiên bản nội dung mới vào tài liệu."""
        if version.document_id != self.document_id:
            raise StatusTransitionError("version does not belong to this document")
        self.assert_label_unique(version.label)
        self.versions.append(version)
        return version

    def find_version(self, version_id: DocumentVersionId) -> DocumentVersion:
        """Lấy phiên bản theo ID, lỗi nếu không có."""
        for version in self.versions:
            if version.version_id == version_id:
                return version
        raise DocumentNotFoundError(f"no version {version_id} in {self.document_id}")

    def current_approved(self) -> DocumentVersion | None:
        """Phiên bản Approved hiện hành, hoặc None nếu chưa có bản nào được duyệt."""
        approved = [version for version in self.versions if version.is_approved]
        if not approved:
            return None
        if len(approved) > 1:
            raise StatusTransitionError(
                f"document {self.document_id} has {len(approved)} Approved versions"
            )
        return approved[0]

    def latest_version(self) -> DocumentVersion | None:
        """Phiên bản mới nhất theo thời điểm tạo, khác với bản Approved hiện hành."""
        if not self.versions:
            return None
        return max(self.versions, key=lambda version: version.created_at)

    def version_with_checksum(self, checksum: Checksum) -> DocumentVersion | None:
        """Phiên bản có cùng checksum trong chính tài liệu này (bất biến I8, I9)."""
        for version in self.versions:
            if version.checksum == checksum:
                return version
        return None

    def approve(self, version_id: DocumentVersionId, actor: Actor) -> ApprovalResult:
        """Duyệt một phiên bản và hạ bản Approved trước đó xuống Obsolete.

        Thực thi bất biến I4, I5 và I14 trong một thao tác logic duy nhất.
        """
        target = self.find_version(version_id)
        previous = self.current_approved()
        if previous is not None and previous.version_id == version_id:
            raise StatusTransitionError(f"version {version_id} is already the current one")
        target.mark_approved(actor)
        if previous is not None:
            previous.mark_obsolete(actor)
        self.current_version_id = target.version_id
        return ApprovalResult(approved=target, obsoleted=previous)

    def obsolete(self, version_id: DocumentVersionId, actor: Actor) -> DocumentVersion:
        """Chuyển một phiên bản sang Obsolete và cập nhật bản hiện hành nếu cần."""
        target = self.find_version(version_id)
        target.mark_obsolete(actor)
        if self.current_version_id == version_id:
            self.current_version_id = None
        return target


@dataclass(frozen=True, slots=True)
class Relationship:
    """Quan hệ giữa hai phiên bản nội dung (bất biến I6, I7)."""

    relation_type: RelationType
    source_version_id: DocumentVersionId
    target_version_id: DocumentVersionId
    created_at: datetime = field(default_factory=_now)
    created_by: str = ""

    def assert_both_ends_are_versions(self) -> None:
        """Hai đầu quan hệ phải là phiên bản khác nhau."""
        if self.source_version_id == self.target_version_id:
            raise RelationshipRebindError("a relationship cannot point back to the same version")

    def reversed_direction(self) -> Relationship:
        """Bản ghi quan hệ theo chiều ngược, dùng khi trả kết quả hai chiều."""
        return Relationship(
            relation_type=self.relation_type,
            source_version_id=self.target_version_id,
            target_version_id=self.source_version_id,
            created_at=self.created_at,
            created_by=self.created_by,
        )


@dataclass(slots=True)
class UploadIntent:
    """Ý định xử lý bền vững của một lượt ghi (mục 3.5 báo cáo)."""

    request_id: RequestId
    idempotency_key: IdempotencyKey
    document_id: DocumentId
    version_id: DocumentVersionId
    expected_checksum: Checksum
    state: IntentState = IntentState.RECEIVED
    retry_count: int = 0
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    last_error: str = ""
    payload: dict[str, str] = field(default_factory=dict)

    def advance(self, state: IntentState, when: datetime | None = None) -> None:
        """Cập nhật trạng thái xử lý, không cho quay lại từ trạng thái kết thúc."""
        if self.state.is_terminal and state is not self.state:
            raise StatusTransitionError(
                f"intent {self.request_id} is already in terminal state {self.state}"
            )
        self.state = state
        self.updated_at = when or _now()

    def register_retry(self, error: str = "") -> None:
        """Ghi nhận một lần thử lại."""
        self.retry_count += 1
        self.last_error = error
        self.state = IntentState.RETRY_PENDING
        self.updated_at = _now()


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Bản ghi audit cho một thao tác (bất biến I12).

    `document_id` được ghi riêng để tra được toàn bộ audit của một tài liệu, kể cả
    những thao tác có `target_id` là phiên bản (test case POC-14).
    """

    actor: Actor
    action: str
    target_id: str
    result: str
    document_id: str = ""
    occurred_at: datetime = field(default_factory=_now)
    detail: str = ""


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Sự kiện phát ra cho downstream (mục 2.5 báo cáo)."""

    event_type: str
    document_id: DocumentId
    version_id: DocumentVersionId | None = None
    occurred_at: datetime = field(default_factory=_now)
    payload: dict[str, str] = field(default_factory=dict)
