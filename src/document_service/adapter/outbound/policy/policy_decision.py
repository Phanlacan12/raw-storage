"""CachingPolicyDecision: quyết định quyền và cache policy của tài liệu.

Hai nguyên tắc của mục 2.6 báo cáo được thực thi ở đây:

- Quyền xem metadata **không** đồng nghĩa quyền tải file: mỗi `Action` được xét riêng.
- Tài liệu chưa ánh xạ được quyền ở chế độ hạn chế, chỉ owner và quản trị viên được
  ủy quyền truy cập (bất biến I11) — mặc định của `AccessPolicy` là `restricted`.

Cache policy có TTL, và TTL này cũng là hạn dùng của chế độ `DOWNLOAD_ONLY` ở mục 10.4:
hết hạn thì service chuyển `NOT_READY` thay vì đoán quyền.
"""

from __future__ import annotations

from asyncio import Lock
from dataclasses import dataclass
from datetime import datetime

from document_service.config import SecuritySettings
from document_service.domain.dto import Decision
from document_service.domain.errors import DocumentNotFoundError, DomainError, PolicyDeniedError
from document_service.domain.model import AccessPolicy, Principal
from document_service.domain.port import MetadataCatalogPort, PolicyDecisionPort
from document_service.domain.value import Action, DocumentId, DocumentVersionId, StorageUri
from document_service.infrastructure.health import DependencyKind, HealthProbeMixin, HealthResult
from document_service.utils.clock import Clock, SystemClock

_READ_ACTIONS = frozenset({Action.VIEW_METADATA, Action.SEARCH, Action.DOWNLOAD})
_WRITE_ACTIONS = frozenset({Action.WRITE})
_APPROVE_ACTIONS = frozenset({Action.TRANSITION_STATUS})
_ADMIN_ACTIONS = frozenset({Action.MANAGE_POLICY})


@dataclass(frozen=True, slots=True)
class CachedPolicy:
    """Policy đã đọc kèm thời điểm đọc, để tính TTL."""

    policy: AccessPolicy
    fetched_at: datetime
    versions: dict[DocumentVersionId, StorageUri]


class CachingPolicyDecision(PolicyDecisionPort, HealthProbeMixin):
    """Quyết định quyền theo nhóm của chủ thể và policy của tài liệu."""

    def __init__(
        self,
        catalog: MetadataCatalogPort,
        settings: SecuritySettings,
        clock: Clock | None = None,
    ) -> None:
        """Nhận catalog để đọc policy, cấu hình bảo mật và nguồn thời gian."""
        HealthProbeMixin.__init__(self)
        self._catalog = catalog
        self._settings = settings
        self._clock = clock or SystemClock()
        self._refresh_lock = Lock()
        self._cache: dict[str, CachedPolicy] = {}

    @property
    def dependency_name(self) -> str:
        """Tên indicator policy."""
        return "policies"

    @property
    def dependency_kind(self) -> DependencyKind:
        """Cache policy được giữ trong tiến trình, catalog có probe riêng."""
        return DependencyKind.REQUIRED_FOR_READ

    async def _probe_dependency(self) -> HealthResult:
        """Số policy đang được giữ trong cache cục bộ."""
        return self.health_up(f"cached documents={len(self._cache)}")

    async def decide(self, principal: Principal, action: Action, resource: str) -> Decision:
        """Cho phép hay từ chối một hành động trên một tài nguyên."""
        if self._settings.auth_disabled or self._is_admin(principal):
            return Decision.allow()
        if action in _READ_ACTIONS:
            return await self._decide_read(principal, action, resource)
        return self._decide_by_group(principal, self._groups_for(action), action)

    def _is_admin(self, principal: Principal) -> bool:
        """Chủ thể có quyền quản trị kho hay không."""
        return principal.is_admin or self._in_groups(principal, self._settings.admin_groups)

    def _groups_for(self, action: Action) -> list[str]:
        """Nhóm được phép thực hiện một hành động ghi.

        Trả danh sách rỗng cho hành động chưa khai báo, nên mặc định là **từ chối**:
        thêm một `Action` mới mà quên khai báo nhóm sẽ bị chặn, không bị mở nhầm.
        """
        if action in _ADMIN_ACTIONS:
            return self._settings.admin_groups
        if action in _APPROVE_ACTIONS:
            return self._settings.approver_groups
        if action in _WRITE_ACTIONS:
            return self._settings.writer_groups
        return []

    async def effective_policy(self, document_id: DocumentId) -> AccessPolicy:
        """Policy đang hiệu lực của tài liệu, lấy từ cache nếu còn TTL."""
        key = str(document_id)
        cached = self._cache.get(key)
        if cached is not None and self._fresh(cached):
            return cached.policy
        return await self._load_policy(document_id)

    async def _load_policy(self, document_id: DocumentId) -> AccessPolicy:
        """Đọc quyền hiện hành để cấp lượt tải mới kể cả khi một instance khác vừa thu hồi quyền."""
        async with self._refresh_lock:
            try:
                document = await self._catalog.read_document(document_id)
                policy = document.access_policy
            except (DocumentNotFoundError, PolicyDeniedError):
                self._cache.pop(str(document_id), None)
                return AccessPolicy()
            except DomainError:
                return AccessPolicy()
            self._cache[str(document_id)] = CachedPolicy(
                policy=policy,
                fetched_at=self._clock.now(),
                versions={v.version_id: v.storage_uri for v in document.versions},
            )
            return policy

    def has_cached_download(self) -> bool:
        """Có tài liệu thường còn policy và URI phiên bản trong TTL."""
        return any(
            item.versions and not item.policy.require_proxy_download and self._remaining(item) > 0
            for item in self._cache.values()
        )

    def cached_download(
        self, principal: Principal, document_id: DocumentId, version_id: DocumentVersionId
    ) -> tuple[StorageUri, int] | None:
        """Cấp link khi mất catalog chỉ cho tài liệu đã được cache và còn quyền tải."""
        cached = self._cache.get(str(document_id))
        if cached is None or cached.policy.require_proxy_download:
            return None
        remaining = self._remaining(cached)
        uri = cached.versions.get(version_id)
        allowed = (
            self._settings.auth_disabled
            or self._is_admin(principal)
            or cached.policy.permits(principal, Action.DOWNLOAD)
        )
        if uri is None or remaining <= 0 or not allowed:
            return None
        return uri, remaining

    def _remaining(self, cached: CachedPolicy) -> int:
        """Số giây nguyên còn dùng được để ký URL."""
        age = (self._clock.now() - cached.fetched_at).total_seconds()
        return int(self._settings.policy_cache_ttl_seconds - age)

    async def invalidate(self, document_id: DocumentId | None = None) -> None:
        """Bỏ cache policy sau khi thay đổi quyền, hoặc toàn bộ khi cần."""
        async with self._refresh_lock:
            if document_id is None:
                self._cache.clear()
            else:
                self._cache.pop(str(document_id), None)

    async def _decide_read(self, principal: Principal, action: Action, resource: str) -> Decision:
        """Hành động đọc: tra policy của tài liệu nếu tài nguyên là document_id."""
        if action is Action.SEARCH:
            return Decision.allow()
        policy = await self._policy_for_resource(resource, action)
        if policy is None:
            return Decision.deny("cannot determine which document to authorize against")
        if policy.permits(principal, action):
            return Decision.allow()
        return Decision.deny(f"policy {policy.classification} does not allow {action}")

    async def _policy_for_resource(self, resource: str, action: Action) -> AccessPolicy | None:
        """Policy của tài nguyên, None nếu tài nguyên không phải định danh tài liệu."""
        if not resource or resource in ("search", "document", "version"):
            return None
        try:
            document_id = DocumentId(resource)
            if action is Action.DOWNLOAD:
                return await self._load_policy(document_id)
            return await self.effective_policy(document_id)
        except DomainError:
            return None

    def _decide_by_group(self, principal: Principal, groups: list[str], action: Action) -> Decision:
        """Cho phép nếu chủ thể thuộc một trong các nhóm được cấu hình."""
        if not groups:
            return Decision.deny(f"action {action} is not declared in the policy")
        if self._in_groups(principal, groups):
            return Decision.allow()
        return Decision.deny(f"membership in {groups} is required to {action}")

    def _in_groups(self, principal: Principal, groups: list[str]) -> bool:
        """Chủ thể có thuộc một trong các nhóm hay không."""
        return bool(set(principal.groups) & set(groups))

    def _fresh(self, cached: CachedPolicy) -> bool:
        """Bản cache còn trong TTL hay không."""
        age = (self._clock.now() - cached.fetched_at).total_seconds()
        return age < self._settings.policy_cache_ttl_seconds
