"""Test cho 14 bất biến I1–I14 ở docs/c4-04-code-data-model.md mục 4.2.

Mỗi test ghi rõ bất biến và test case PoC tương ứng, để khi một test đỏ thì biết ngay
yêu cầu nào của báo cáo đang bị vi phạm.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from document_service.application.context import PolicySet, PortBundle
from document_service.application.usecase.approve_version import (
    ApproveVersionUseCase,
    TransitionStatusCommand,
)
from document_service.application.usecase.create_version import (
    CreateVersionCommand,
    CreateVersionUseCase,
)
from document_service.application.usecase.register_document import (
    RegisterDocumentCommand,
    RegisterDocumentUseCase,
)
from document_service.application.usecase.relationships import (
    DeclareRelationshipCommand,
    DeclareRelationshipUseCase,
    QueryRelationshipsCommand,
    QueryRelationshipsUseCase,
)
from document_service.config import Settings
from document_service.domain.dto import UploadRequest
from document_service.domain.errors import (
    ConcurrencyConflictError,
    DependencyUnavailableError,
    DocumentNotFoundError,
    PolicyDeniedError,
    RelationshipRebindError,
    StatusTransitionError,
    VersionLabelConflictError,
)
from document_service.domain.metadata_builder import CatalogMetadataBuilder
from document_service.domain.model import Collection, Document, DocumentMetadata, Principal
from document_service.domain.value import (
    Action,
    Checksum,
    Direction,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    IdempotencyKey,
    IntentState,
    RelationType,
    VersionLabel,
)
from document_service.utils.hashing import digest_of
from document_service.worker.reconcile import IntentRecoveryJob

DOCUMENT_TYPE = "SRS"


def _upload(
    document_id: DocumentId, payload: bytes, key: str, label: str | None = None
) -> UploadRequest:
    """Dựng UploadRequest cho test."""
    from document_service.domain.value import Actor

    return UploadRequest(
        document_id=document_id,
        original_file_name="srs.pdf",
        content_format="application/pdf",
        checksum=Checksum(algorithm="sha256", hex_digest=digest_of(payload)),
        size_bytes=len(payload),
        actor=Actor(principal_id="tester"),
        idempotency_key=IdempotencyKey(key),
        label=VersionLabel(label) if label else None,
    )


def _stream(payload: bytes):
    """Factory luồng dữ liệu cho test."""

    def factory():
        async def iterator():
            yield payload

        return iterator()

    return factory


async def _register(ports: PortBundle, principal: Principal) -> Document:
    """Đăng ký một tài liệu mẫu."""
    use_case = RegisterDocumentUseCase(ports, CatalogMetadataBuilder())
    return await use_case.execute(
        RegisterDocumentCommand(
            principal=principal,
            metadata=DocumentMetadata(
                title="SRS", document_type=DOCUMENT_TYPE, collection_id="PROJECT-A"
            ),
        )
    )


async def _create_version(
    ports: PortBundle,
    policies: PolicySet,
    principal: Principal,
    document_id: DocumentId,
    payload: bytes,
    key: str,
    label: str | None = None,
):
    """Tạo một phiên bản qua use case."""
    use_case = CreateVersionUseCase(ports, policies, CatalogMetadataBuilder())
    command = CreateVersionCommand(
        request=_upload(document_id, payload, key, label),
        principal=principal,
        stream_factory=_stream(payload),
    )
    return await use_case.execute(command)


class TestVersionInvariants:
    """I1, I2, I3, I8, I9, I13 — định danh, nhãn và chống trùng nội dung."""

    async def test_version_id_independent_of_label(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I1: document_version_id không chứa và không phụ thuộc version_label."""
        document = await _register(ports, principal)
        result = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        assert str(result.version.label) == "1.0"
        assert "1.0" not in str(result.version.version_id)

    async def test_duplicate_label_rejected(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I2: version_label phải duy nhất trong một tài liệu."""
        document = await _register(ports, principal)
        await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        with pytest.raises(VersionLabelConflictError):
            await _create_version(
                ports, policies, principal, document.document_id, b"v2", "key-00000002", "1.0"
            )

    async def test_old_version_content_preserved(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I3: phát hành bản mới không ghi đè nội dung bản cũ."""
        document = await _register(ports, principal)
        first = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        second = await _create_version(
            ports, policies, principal, document.document_id, b"v2", "key-00000002", "2.0"
        )
        assert first.version.storage_uri != second.version.storage_uri
        info = await ports.objects.head(first.version.storage_uri)
        assert info.size_bytes == len(b"v1")

    async def test_same_content_does_not_create_version(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I8, POC-13: upload lại cùng nội dung vào cùng tài liệu không tạo bản mới."""
        document = await _register(ports, principal)
        first = await _create_version(
            ports, policies, principal, document.document_id, b"same", "key-00000001"
        )
        again = await _create_version(
            ports, policies, principal, document.document_id, b"same", "key-00000002"
        )
        assert again.created is False
        assert again.duplicate is True
        assert again.version.version_id == first.version.version_id

    async def test_same_checksum_different_documents(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I9: hai tài liệu khác nhau cùng checksum vẫn giữ document_id riêng."""
        first_doc = await _register(ports, principal)
        second_doc = await _register(ports, principal)
        first = await _create_version(
            ports, policies, principal, first_doc.document_id, b"same", "key-00000001"
        )
        second = await _create_version(
            ports, policies, principal, second_doc.document_id, b"same", "key-00000002"
        )
        assert first.version.checksum == second.version.checksum
        assert first.version.document_id != second.version.document_id
        assert second.created is True

    async def test_replay_same_idempotency_key(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I13, POC-21: retry cùng Idempotency-Key trả lại phiên bản cũ."""
        document = await _register(ports, principal)
        first = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        replay = await _create_version(
            ports, policies, principal, document.document_id, b"khac", "key-00000001", "9.0"
        )
        assert replay.replayed is True
        assert replay.version.version_id == first.version.version_id

    @pytest.mark.parametrize("state", [IntentState.COMPLETED, IntentState.FAILED])
    async def test_unauthorized_replay_is_denied_and_audited(
        self, ports: PortBundle, policies: PolicySet, principal: Principal, state: IntentState
    ) -> None:
        """I12/I13: quyền ghi phải được kiểm trước mọi kết quả tra khóa."""
        from document_service.adapter.outbound.fake.in_memory import AllowAllPolicyDecision

        document = await _register(ports, principal)
        key = "replay-denied-0001"
        await _create_version(ports, policies, principal, document.document_id, b"data", key)
        intent = await ports.intents.find_by_idempotency_key(IdempotencyKey(key))
        assert intent is not None
        intent.state = state
        await ports.intents.save(intent)
        if state is IntentState.FAILED:
            with pytest.raises(ConcurrencyConflictError, match="failed"):
                await _create_version(
                    ports, policies, principal, document.document_id, b"data", key
                )
        assert isinstance(ports.policies, AllowAllPolicyDecision)
        ports.policies.denied_actions.add(Action.WRITE)
        with pytest.raises(PolicyDeniedError):
            await _create_version(
                ports, policies, Principal("reader"), document.document_id, b"data", key
            )
        events = await ports.audit.list_for_document(document.document_id)
        assert any(e.actor.principal_id == "reader" and e.result == "denied" for e in events)


class TestLifecycleInvariants:
    """I4, I5, I12, I14 — trạng thái, bản hiện hành và audit."""

    async def test_single_approved_version(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I4, I5, POC-10: duyệt bản mới làm bản trước đó thành Obsolete."""
        document = await _register(ports, principal)
        first = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        second = await _create_version(
            ports, policies, principal, document.document_id, b"v2", "key-00000002", "2.0"
        )
        use_case = ApproveVersionUseCase(ports, policies, CatalogMetadataBuilder())
        await use_case.execute(
            TransitionStatusCommand(
                document_id=document.document_id,
                version_id=first.version.version_id,
                idempotency_key=IdempotencyKey(f"status-{first.version.version_id}"),
                target_status=DocumentStatus.APPROVED,
                principal=principal,
            )
        )
        result = await use_case.execute(
            TransitionStatusCommand(
                document_id=document.document_id,
                version_id=second.version.version_id,
                idempotency_key=IdempotencyKey(f"status-{second.version.version_id}"),
                target_status=DocumentStatus.APPROVED,
                principal=principal,
            )
        )
        assert result.changed.version_id == second.version.version_id
        assert result.changed_from is DocumentStatus.DRAFT
        assert result.obsoleted_from is DocumentStatus.APPROVED
        assert result.obsoleted is not None
        assert result.obsoleted.version_id == first.version.version_id
        stored = await ports.catalog.read_document(document.document_id)
        approved = [item for item in stored.versions if item.is_approved]
        events = await ports.audit.list_for_document(document.document_id)
        assert any(
            e.target_id == str(first.version.version_id) and e.detail == "Approved -> Obsolete"
            for e in events
        )
        assert len(approved) == 1
        assert stored.current_version_id == second.version.version_id

    async def test_concurrent_approval_keeps_one_approved(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """POC-22: hai request duyệt đồng thời vẫn chỉ còn một bản Approved."""
        document = await _register(ports, principal)
        first = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        second = await _create_version(
            ports, policies, principal, document.document_id, b"v2", "key-00000002", "2.0"
        )
        use_case = ApproveVersionUseCase(ports, policies, CatalogMetadataBuilder())
        commands = [
            TransitionStatusCommand(
                document_id=document.document_id,
                version_id=version_id,
                idempotency_key=IdempotencyKey(f"status-{version_id}"),
                target_status=DocumentStatus.APPROVED,
                principal=principal,
            )
            for version_id in (first.version.version_id, second.version.version_id)
        ]
        results = await asyncio.gather(
            *(use_case.execute(command) for command in commands), return_exceptions=True
        )
        assert any(not isinstance(item, Exception) for item in results)
        stored = await ports.catalog.read_document(document.document_id)
        approved = [item for item in stored.versions if item.is_approved]
        assert len(approved) == 1

    async def test_audit_records_status_change(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I12, POC-14: mọi thay đổi trạng thái đều có audit kèm actor."""
        document = await _register(ports, principal)
        version = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        use_case = ApproveVersionUseCase(ports, policies, CatalogMetadataBuilder())
        await use_case.execute(
            TransitionStatusCommand(
                document_id=document.document_id,
                version_id=version.version.version_id,
                idempotency_key=IdempotencyKey(f"status-{version.version.version_id}"),
                target_status=DocumentStatus.APPROVED,
                principal=principal,
            )
        )
        events = await ports.audit.list_for_document(document.document_id)
        actions = [event.action for event in events]
        assert "version.status_changed" in actions
        assert any(e.detail == "Draft -> Approved" for e in events)
        assert all(event.actor.principal_id == "tester" for event in events)

    async def test_obsoleting_draft_keeps_approval_metadata_empty(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """Loại bỏ Draft chỉ ghi dấu loại bỏ, kể cả khi đọc lại từ catalog."""
        document = await _register(ports, principal)
        upload = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        version_id = upload.version.version_id
        command = TransitionStatusCommand(
            document.document_id,
            version_id,
            DocumentStatus.OBSOLETE,
            principal,
            IdempotencyKey("obsolete-test"),
        )
        result = await ApproveVersionUseCase(ports, policies).execute(command)
        assert result.changed.version_id == version_id
        assert result.changed_from is DocumentStatus.DRAFT
        assert result.obsoleted is None and result.obsoleted_from is None
        stored = (await ports.catalog.read_document(document.document_id)).find_version(version_id)
        assert stored.approved_by is None and stored.approved_at is None
        assert stored.obsoleted_by == principal.principal_id
        assert stored.obsoleted_at is not None
        events = await ports.audit.list_for_document(document.document_id)
        assert any(
            e.target_id == str(version_id) and e.detail == "Draft -> Obsolete" for e in events
        )

    async def test_latest_differs_from_current_approved(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I14: bản mới nhất khác bản Approved hiện hành."""
        document = await _register(ports, principal)
        first = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        use_case = ApproveVersionUseCase(ports, policies, CatalogMetadataBuilder())
        await use_case.execute(
            TransitionStatusCommand(
                document_id=document.document_id,
                version_id=first.version.version_id,
                idempotency_key=IdempotencyKey(f"status-{first.version.version_id}"),
                target_status=DocumentStatus.APPROVED,
                principal=principal,
            )
        )
        await _create_version(
            ports, policies, principal, document.document_id, b"v2", "key-00000002", "2.0"
        )
        stored = await ports.catalog.read_document(document.document_id)
        latest = stored.latest_version()
        assert latest is not None
        assert stored.current_version_id == first.version.version_id
        assert latest.version_id != stored.current_version_id

    async def test_recovery_finishes_second_patch_under_document_lock(
        self,
        ports: PortBundle,
        policies: PolicySet,
        principal: Principal,
        monkeypatch: pytest.MonkeyPatch,
        settings: Settings,
    ) -> None:
        """Hai Approved sau khi patch thứ hai lỗi phải còn một khi đối soát."""
        document = await _register(ports, principal)
        commands = []
        for label in ("1.0", "2.0", "3.0"):
            version = await _create_version(
                ports,
                policies,
                principal,
                document.document_id,
                label.encode(),
                f"upload-key-{label}",
                label,
            )
            commands.append(
                TransitionStatusCommand(
                    document.document_id,
                    version.version.version_id,
                    DocumentStatus.APPROVED,
                    principal,
                    IdempotencyKey(f"status-key-{label}"),
                )
            )
        use_case = ApproveVersionUseCase(ports, policies)
        first, second, third = commands
        original = await use_case.execute(first)
        patch = ports.catalog.patch_controlled_fields

        async def flaky_patch(*args):
            if args[1] == first.version_id:
                raise DependencyUnavailableError("catalog", "second patch interrupted")
            await patch(*args)

        monkeypatch.setattr(ports.catalog, "patch_controlled_fields", flaky_patch)
        with pytest.raises(DependencyUnavailableError):
            await use_case.execute(second)
        versions = await ports.catalog.list_versions(document.document_id)
        assert sum(version.is_approved for version in versions) == 2
        with pytest.raises(ConcurrencyConflictError):
            await use_case.execute(third)
        monkeypatch.setattr(ports.catalog, "patch_controlled_fields", patch)
        lock = AsyncMock(wraps=ports.locks.with_lock)
        monkeypatch.setattr(ports.locks, "with_lock", lock)
        settings.intent.stale_after_seconds = 0
        job = IntentRecoveryJob(ports, settings)
        touched: set[DocumentId] = set()
        record = ports.audit.record

        async def record_then_fail(event):
            await record(event)
            raise DependencyUnavailableError("audit", "reply lost after commit")

        monkeypatch.setattr(ports.audit, "record", record_then_fail)
        assert (await job.run_once(touched)).failed == 1
        monkeypatch.setattr(ports.audit, "record", record)
        assert (await job.run_once(touched)).recovered == 1
        audit = await ports.audit.list_for_document(document.document_id)
        assert [
            row.detail
            for row in audit
            if row.target_id == str(second.version_id) and row.action == "version.status_changed"
        ] == ["Draft -> Approved"]
        assert (
            len(
                [
                    event
                    for event in ports.events.events
                    if event.version_id == second.version_id
                    and event.event_type == "version.approved"
                ]
            )
            == 1
        )
        assert lock.await_count == 2
        assert lock.await_args.args[0] == document.document_id
        assert touched == {document.document_id}
        versions = await ports.catalog.list_versions(document.document_id)
        assert [v.version_id for v in versions if v.is_approved] == [second.version_id]
        await use_case.execute(third)
        assert await use_case.execute(first) == original
        assert (
            await ports.catalog.read_document(document.document_id)
        ).current_version_id == third.version_id

    async def test_cannot_approve_twice(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I4: duyệt lại đúng bản đang hiện hành bị từ chối."""
        document = await _register(ports, principal)
        version = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        use_case = ApproveVersionUseCase(ports, policies, CatalogMetadataBuilder())
        command = TransitionStatusCommand(
            document_id=document.document_id,
            version_id=version.version.version_id,
            idempotency_key=IdempotencyKey(f"status-{version.version.version_id}"),
            target_status=DocumentStatus.APPROVED,
            principal=principal,
        )
        await use_case.execute(command)
        assert (await use_case.execute(command)).changed.status is DocumentStatus.APPROVED
        with pytest.raises(StatusTransitionError):
            await use_case.execute(
                replace(command, idempotency_key=IdempotencyKey("second-approval"))
            )


class TestRelationshipInvariants:
    """I6, I7 — quan hệ gắn đúng phiên bản và truy vấn được hai chiều."""

    async def test_relationship_is_bidirectional(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I7, POC-06: truy vấn ngược trả đúng relation_type."""
        document = await _register(ports, principal)
        source = await _create_version(
            ports, policies, principal, document.document_id, b"srs", "key-00000001", "2.0"
        )
        target = await _create_version(
            ports, policies, principal, document.document_id, b"urd", "key-00000002", "1.2"
        )
        declare = DeclareRelationshipUseCase(ports, policies)
        await declare.execute(
            DeclareRelationshipCommand(
                relation_type=RelationType.DERIVED_FROM,
                source_version_id=source.version.version_id,
                target_version_id=target.version.version_id,
                principal=principal,
            )
        )
        query = QueryRelationshipsUseCase(ports)
        incoming = await query.execute(
            QueryRelationshipsCommand(
                version_id=target.version.version_id,
                principal=principal,
                direction=Direction.INCOMING,
            )
        )
        assert len(incoming) == 1
        assert incoming[0].relationship.relation_type is RelationType.DERIVED_FROM
        assert incoming[0].relationship.source_version_id == source.version.version_id

    async def test_relationship_target_not_rebound(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I6, POC-09: không được đổi đích của quan hệ đã khai báo."""
        document = await _register(ports, principal)
        source = await _create_version(
            ports, policies, principal, document.document_id, b"srs", "key-00000001", "2.0"
        )
        first_target = await _create_version(
            ports, policies, principal, document.document_id, b"urd", "key-00000002", "1.2"
        )
        second_target = await _create_version(
            ports, policies, principal, document.document_id, b"urd2", "key-00000003", "1.3"
        )
        declare = DeclareRelationshipUseCase(ports, policies)
        await declare.execute(
            DeclareRelationshipCommand(
                relation_type=RelationType.DERIVED_FROM,
                source_version_id=source.version.version_id,
                target_version_id=first_target.version.version_id,
                principal=principal,
            )
        )
        with pytest.raises(RelationshipRebindError):
            await declare.execute(
                DeclareRelationshipCommand(
                    relation_type=RelationType.DERIVED_FROM,
                    source_version_id=source.version.version_id,
                    target_version_id=second_target.version.version_id,
                    principal=principal,
                )
            )

    async def test_relationship_survives_new_version(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I6, POC-09: tạo phiên bản mới không làm mất quan hệ cũ."""
        document = await _register(ports, principal)
        source = await _create_version(
            ports, policies, principal, document.document_id, b"srs20", "key-00000001", "2.0"
        )
        target = await _create_version(
            ports, policies, principal, document.document_id, b"urd12", "key-00000002", "1.2"
        )
        declare = DeclareRelationshipUseCase(ports, policies)
        await declare.execute(
            DeclareRelationshipCommand(
                relation_type=RelationType.DERIVED_FROM,
                source_version_id=source.version.version_id,
                target_version_id=target.version.version_id,
                principal=principal,
            )
        )
        await _create_version(
            ports, policies, principal, document.document_id, b"srs21", "key-00000003", "2.1"
        )
        query = QueryRelationshipsUseCase(ports)
        outgoing = await query.execute(
            QueryRelationshipsCommand(
                version_id=source.version.version_id,
                principal=principal,
                direction=Direction.OUTGOING,
            )
        )
        assert len(outgoing) == 1
        assert outgoing[0].relationship.target_version_id == target.version.version_id


class TestStorageInvariants:
    """I10, I11 — object bất biến và mặc định hạn chế quyền."""

    async def test_storage_uri_matches_version(
        self, ports: PortBundle, policies: PolicySet, principal: Principal
    ) -> None:
        """I10: storage_uri trỏ tới object của đúng phiên bản."""
        document = await _register(ports, principal)
        result = await _create_version(
            ports, policies, principal, document.document_id, b"v1", "key-00000001", "1.0"
        )
        uri = result.version.storage_uri
        assert str(result.version.version_id) in uri.key
        assert str(document.document_id) in uri.key
        assert uri.key.endswith("/source")

    def test_restricted_by_default(self) -> None:
        """I11: tài liệu chưa ánh xạ quyền thì chỉ admin được truy cập."""
        document = Document(document_id=DocumentId("DOC-1"))
        outsider = Principal(principal_id="someone", groups=("other",))
        admin = Principal(principal_id="admin", groups=("document-admins",), is_admin=True)
        from document_service.domain.value import Action

        assert document.access_policy.classification == "restricted"
        assert document.access_policy.permits(outsider, Action.DOWNLOAD) is False
        assert document.access_policy.permits(admin, Action.DOWNLOAD) is True

    def test_version_id_is_immutable_value(self) -> None:
        """I1: value object của định danh là bất biến."""
        version_id = DocumentVersionId("VER-1")
        with pytest.raises(Exception):
            version_id.value = "VER-2"  # type: ignore[misc]


async def test_register_checks_collection_when_enabled(
    ports: PortBundle, principal: Principal
) -> None:
    """Chỉ cho đăng ký vào collection đã cấp khi triển khai bật cờ B13."""
    command = RegisterDocumentCommand(principal, DocumentMetadata(collection_id="project"))
    strict = RegisterDocumentUseCase(ports, require_existing_collection=True)
    with pytest.raises(DocumentNotFoundError):
        await strict.execute(command)
    await ports.catalog.ensure_collection(Collection("project", "Example"))
    assert (await strict.execute(command)).metadata.collection_id == "project"
