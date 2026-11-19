"""Bộ test hợp đồng của PolicyDecisionPort (plan B9).

Hai nhóm khẳng định, tách riêng vì hành vi **khác nhau có chủ ý**:

- `TestEnforcingPolicyDecision`: đường chạy thật (`auth_disabled = false`). Quyền xem
  metadata **không** đồng nghĩa quyền tải; tài liệu chưa ánh xạ quyền ở chế độ hạn chế
  (bất biến I11); chỉ quản trị viên đổi được chính sách truy cập.
- `TestDevPolicyDecision`: profile phát triển cho qua mọi hành động — ghi thành test để
  ai đọc cũng thấy đây là lựa chọn tường minh, không phải lỗ hổng bỏ sót.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from document_service.adapter.outbound.fake.in_memory import (
    AllowAllPolicyDecision,
    InMemoryCatalog,
    InMemoryEventPublisher,
)
from document_service.adapter.outbound.policy.policy_decision import CachingPolicyDecision
from document_service.application.context import PortBundle
from document_service.application.usecase.access_policy import (
    UpdateAccessPolicyCommand,
    UpdateAccessPolicyUseCase,
)
from document_service.application.usecase.issue_download import (
    IssueDownloadCommand,
    IssueDownloadUseCase,
)
from document_service.application.usecase.register_document import (
    RegisterDocumentCommand,
    RegisterDocumentUseCase,
)
from document_service.config import SecuritySettings
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import AccessPolicy, Document, DocumentVersion, Principal
from document_service.domain.port import PolicyDecisionPort
from document_service.domain.value import (
    Action,
    Checksum,
    DocumentId,
    DocumentVersionId,
    IdempotencyKey,
    StorageUri,
    VersionLabel,
)
from document_service.utils.clock import FixedClock

DOCUMENT_ID = DocumentId("DOC-POLICY-0001")
RESTRICTED_ID = DocumentId("DOC-POLICY-0002")


@pytest.fixture
def catalog() -> InMemoryCatalog:
    """Catalog chứa một tài liệu internal và một tài liệu chưa ánh xạ quyền."""
    return InMemoryCatalog()


@pytest.fixture
async def prepared_catalog(catalog: InMemoryCatalog) -> InMemoryCatalog:
    """Đăng ký hai tài liệu mẫu."""
    await catalog.register_document(
        Document(
            document_id=DOCUMENT_ID,
            access_policy=AccessPolicy(classification="internal", allowed_groups=("du-an-a",)),
        )
    )
    await catalog.register_document(Document(document_id=RESTRICTED_ID))
    return catalog


@pytest.fixture
def enforcing(prepared_catalog: InMemoryCatalog) -> CachingPolicyDecision:
    """Policy decision ở chế độ thực thi quyền."""
    settings = SecuritySettings(
        auth_disabled=False,
        admin_groups=["document-admins"],
        writer_groups=["document-writers"],
        approver_groups=["document-approvers"],
        policy_cache_ttl_seconds=60,
    )
    return CachingPolicyDecision(prepared_catalog, settings)


class TestEnforcingPolicyDecision:
    """Hợp đồng của đường chạy thật."""

    async def test_admin_allowed_everything(self, enforcing: PolicyDecisionPort) -> None:
        """Quản trị viên kho được mọi hành động."""
        admin = Principal(principal_id="ad", groups=("document-admins",))
        for action in Action:
            decision = await enforcing.decide(admin, action, str(DOCUMENT_ID))
            assert decision.allowed is True

    async def test_writer_can_write_but_not_manage_policy(
        self, enforcing: PolicyDecisionPort
    ) -> None:
        """Nhóm ghi không được đổi chính sách truy cập."""
        writer = Principal(principal_id="w", groups=("document-writers",))
        assert (await enforcing.decide(writer, Action.WRITE, "version")).allowed is True
        denied = await enforcing.decide(writer, Action.MANAGE_POLICY, str(DOCUMENT_ID))
        assert denied.allowed is False
        assert denied.reason

    async def test_approver_can_transition_only(self, enforcing: PolicyDecisionPort) -> None:
        """Nhóm phê duyệt được chuyển trạng thái, không được tạo phiên bản."""
        approver = Principal(principal_id="a", groups=("document-approvers",))
        allowed = await enforcing.decide(approver, Action.TRANSITION_STATUS, "v")
        assert allowed.allowed is True
        assert (await enforcing.decide(approver, Action.WRITE, "v")).allowed is False

    async def test_metadata_permission_is_not_download_permission(
        self, enforcing: PolicyDecisionPort
    ) -> None:
        """Mục 2.6: xem metadata khác tải file — hai hành động xét riêng."""
        member = Principal(principal_id="m", groups=("du-an-a",))
        assert (
            await enforcing.decide(member, Action.VIEW_METADATA, str(DOCUMENT_ID))
        ).allowed is True
        outsider = Principal(principal_id="o", groups=("khac",))
        assert (
            await enforcing.decide(outsider, Action.VIEW_METADATA, str(DOCUMENT_ID))
        ).allowed is False
        assert (
            await enforcing.decide(outsider, Action.DOWNLOAD, str(DOCUMENT_ID))
        ).allowed is False

    async def test_unmapped_document_is_restricted(self, enforcing: PolicyDecisionPort) -> None:
        """I11: tài liệu chưa ánh xạ quyền thì người ngoài không xem được."""
        member = Principal(principal_id="m", groups=("du-an-a",))
        decision = await enforcing.decide(member, Action.DOWNLOAD, str(RESTRICTED_ID))
        assert decision.allowed is False
        policy = await enforcing.effective_policy(RESTRICTED_ID)
        assert policy.classification == "restricted"

    async def test_unknown_document_denies_read(self, enforcing: PolicyDecisionPort) -> None:
        """Không đọc được tài liệu thì từ chối, không mặc định cho phép."""
        member = Principal(principal_id="m", groups=("du-an-a",))
        decision = await enforcing.decide(member, Action.DOWNLOAD, "DOC-KHONG-CO")
        assert decision.allowed is False
        policy = await enforcing.effective_policy(DocumentId("DOC-KHONG-CO"))
        assert policy.classification == "restricted"

    async def test_search_is_allowed_then_filtered_later(
        self, enforcing: PolicyDecisionPort
    ) -> None:
        """Hành động tìm kiếm được phép; lọc quyền làm ở bước trả kết quả."""
        member = Principal(principal_id="m", groups=("du-an-a",))
        assert (await enforcing.decide(member, Action.SEARCH, "search")).allowed is True

    async def test_policy_cache_has_ttl(self, prepared_catalog: InMemoryCatalog) -> None:
        """Policy được cache trong TTL rồi đọc lại từ catalog."""
        clock = FixedClock()
        settings = SecuritySettings(auth_disabled=False, policy_cache_ttl_seconds=30)
        decision = CachingPolicyDecision(prepared_catalog, settings, clock)
        first = await decision.effective_policy(DOCUMENT_ID)
        await prepared_catalog.patch_document_fields(
            DOCUMENT_ID, {"classification": "confidential"}
        )
        cached = await decision.effective_policy(DOCUMENT_ID)
        assert cached.classification == first.classification
        clock.advance(31)
        refreshed = await decision.effective_policy(DOCUMENT_ID)
        assert refreshed.classification == "confidential"

    async def test_invalidate_clears_cache(self, prepared_catalog: InMemoryCatalog) -> None:
        """Thu hồi quyền làm mất cache ngay, không chờ TTL."""
        settings = SecuritySettings(auth_disabled=False, policy_cache_ttl_seconds=600)
        decision = CachingPolicyDecision(prepared_catalog, settings)
        await decision.effective_policy(DOCUMENT_ID)
        await prepared_catalog.patch_document_fields(
            DOCUMENT_ID, {"classification": "confidential"}
        )
        await decision.invalidate(DOCUMENT_ID)
        assert (await decision.effective_policy(DOCUMENT_ID)).classification == "confidential"


class TestDevPolicyDecision:
    """Hành vi của profile phát triển, ghi rõ để không bị dùng nhầm khi chạy thật."""

    async def test_fake_allows_everything(self) -> None:
        """Adapter fake cho qua mọi hành động."""
        fake = AllowAllPolicyDecision()
        user = Principal(principal_id="dev")
        for action in Action:
            assert (await fake.decide(user, action, "x")).allowed is True

    async def test_fake_can_simulate_denial(self) -> None:
        """Fake vẫn mô phỏng được từ chối quyền để test POC-04."""
        fake = AllowAllPolicyDecision()
        fake.denied_actions.add(Action.DOWNLOAD)
        user = Principal(principal_id="dev")
        assert (await fake.decide(user, Action.DOWNLOAD, "x")).allowed is False
        admin = Principal(principal_id="ad", is_admin=True)
        assert (await fake.decide(admin, Action.DOWNLOAD, "x")).allowed is True

    async def test_auth_disabled_allows_everything(self, prepared_catalog: InMemoryCatalog) -> None:
        """`auth_disabled = true` cho qua mọi hành động, kể cả với adapter thật."""
        settings = SecuritySettings(auth_disabled=True)
        decision = CachingPolicyDecision(prepared_catalog, settings)
        user = Principal(principal_id="dev")
        assert (await decision.decide(user, Action.MANAGE_POLICY, "x")).allowed is True


async def test_revoke_stops_new_downloads_before_ttl(ports: PortBundle) -> None:
    """POC-11/23: cấp link, thu hồi rồi thử lại ngay qua use case thật."""
    settings = SecuritySettings(auth_disabled=False, policy_cache_ttl_seconds=600)
    ports = replace(ports, policies=CachingPolicyDecision(ports.catalog, settings))
    admin = Principal("admin", is_admin=True)
    member = Principal("reader")
    policy = AccessPolicy(allowed_principals=("reader",))
    register = RegisterDocumentUseCase(ports)
    registration = RegisterDocumentCommand(
        admin,
        document_id=DOCUMENT_ID,
        access_policy=policy,
        idempotency_key=IdempotencyKey("doc-register-key"),
    )
    await register.execute(registration)
    await register.execute(registration)
    version = DocumentVersion(
        DocumentVersionId("VER-1"),
        DOCUMENT_ID,
        VersionLabel("1.0"),
        Checksum.parse("sha256:" + "a" * 64),
        StorageUri("bucket", "file"),
        "input.pdf",
        "application/pdf",
        10,
    )
    await ports.catalog.register_version(version, {})
    download = IssueDownloadUseCase(ports)
    command = IssueDownloadCommand(DOCUMENT_ID, version.version_id, member)
    assert (await download.execute(command)).url
    remote = IssueDownloadUseCase(
        replace(ports, policies=CachingPolicyDecision(ports.catalog, settings))
    )
    assert (await remote.execute(command)).url
    revoke = UpdateAccessPolicyUseCase(ports)
    update = UpdateAccessPolicyCommand(
        DOCUMENT_ID,
        admin,
        AccessPolicy(require_proxy_download=True),
        IdempotencyKey("policy-revoke-key"),
    )
    await revoke.execute(update)
    await revoke.execute(update)
    assert await ports.policies.effective_policy(DOCUMENT_ID) == update.access_policy
    with pytest.raises(PolicyDeniedError):
        await download.execute(command)
    with pytest.raises(PolicyDeniedError):
        await remote.execute(command)
    assert isinstance(ports.events, InMemoryEventPublisher)
    assert [(e.event_type, e.document_id) for e in ports.events.events] == [
        ("document.created", DOCUMENT_ID),
        ("access.changed", DOCUMENT_ID),
    ]
