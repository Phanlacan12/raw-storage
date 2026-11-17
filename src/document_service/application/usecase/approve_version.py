"""ApproveVersionUseCase: duyệt phiên bản, giữ bất biến I4, I5, I12, I14.

Thứ tự bước theo sequence ở mục 7 của docs/c4-04b-code-structure.md: toàn bộ khối
nằm trong khóa theo document_id, vì ba lệnh ghi xuống catalog không nằm trong một
giao dịch của sản phẩm.
"""

from __future__ import annotations

from dataclasses import dataclass

from document_service.application.context import PolicySet, PortBundle
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.application.usecase.base import AuditOutcome, AuditTarget, WriteUseCase
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import ApprovalResult, DomainEvent, Principal
from document_service.domain.value import Action, DocumentId, DocumentStatus, DocumentVersionId


@dataclass(frozen=True, slots=True)
class TransitionStatusCommand:
    """Yêu cầu chuyển trạng thái một phiên bản."""

    document_id: DocumentId
    version_id: DocumentVersionId
    target_status: DocumentStatus
    principal: Principal


class ApproveVersionUseCase(WriteUseCase[TransitionStatusCommand, ApprovalResult]):
    """Chuyển trạng thái phiên bản và cập nhật bản hiện hành."""

    def __init__(
        self,
        ports: PortBundle,
        policies: PolicySet,
        builder: CatalogMetadataBuilder | None = None,
    ) -> None:
        """Dựng use case từ bundle port và tập policy."""
        super().__init__(ports)
        self._policies = policies
        self._builder = builder or CatalogMetadataBuilder()

    async def execute(self, command: TransitionStatusCommand) -> ApprovalResult:
        """Kiểm tra quyền rồi chạy phần chuyển trạng thái trong khóa."""
        try:
            await self._authorize(
                command.principal, Action.TRANSITION_STATUS, str(command.version_id)
            )
        except PolicyDeniedError as error:
            await self._record(
                command.principal,
                "version.status_changed",
                AuditTarget.of_version(command.document_id, command.version_id),
                AuditOutcome.denied(str(error)),
            )
            raise
        return await self._run_exclusive(command.document_id, lambda: self._transition(command))

    async def _transition(self, command: TransitionStatusCommand) -> ApprovalResult:
        """Phần chạy trong khóa: đọc lại tài liệu, chuyển trạng thái, ghi catalog."""
        document = await self.ports.catalog.read_document(command.document_id)
        result = self._policies.lifecycle.transition(
            document, command.version_id, command.target_status, command.principal.as_actor()
        )
        await self.ports.catalog.patch_controlled_fields(
            result.approved.version_id, {"status": str(result.approved.status)}
        )
        if result.obsoleted is not None:
            await self.ports.catalog.patch_controlled_fields(
                result.obsoleted.version_id, {"status": str(result.obsoleted.status)}
            )
        await self.ports.catalog.patch_document_fields(
            document.document_id, self._builder.document_fields(document)
        )
        await self._publish_transition(command, result)
        return result

    async def _publish_transition(
        self, command: TransitionStatusCommand, result: ApprovalResult
    ) -> None:
        """Phát sự kiện và ghi audit cho lượt chuyển trạng thái."""
        await self._publish(
            DomainEvent(
                event_type=f"version.{str(result.approved.status).lower()}",
                document_id=command.document_id,
                version_id=result.approved.version_id,
                payload={"actor": command.principal.principal_id},
            )
        )
        await self._record(
            command.principal,
            "version.status_changed",
            AuditTarget.of_version(command.document_id, result.approved.version_id),
            AuditOutcome.ok(f"-> {result.approved.status}"),
        )
        if result.obsoleted is not None:
            await self._record(
                command.principal,
                "version.status_changed",
                AuditTarget.of_version(command.document_id, result.obsoleted.version_id),
                AuditOutcome.ok("-> Obsolete"),
            )
