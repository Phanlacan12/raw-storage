"""ApproveVersionUseCase: duyệt phiên bản, giữ bất biến I4, I5, I12, I14.

Thứ tự bước theo sequence ở mục 7 của docs/c4-04b-code-structure.md: toàn bộ khối
nằm trong khóa theo document_id, vì ba lệnh ghi xuống catalog không nằm trong một
giao dịch của sản phẩm.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from document_service.application.context import PolicySet, PortBundle
from document_service.application.orchestration.status_change_saga import (
    StatusChangePlan,
    StatusChangeSaga,
    StatusChangeSnapshot,
)
from document_service.application.usecase.base import AuditOutcome, AuditTarget, WriteUseCase
from document_service.domain.errors import (
    ConcurrencyConflictError,
    DependencyUnavailableError,
    PolicyDeniedError,
)
from document_service.domain.metadata_builder import CatalogMetadataBuilder
from document_service.domain.model import Principal, ProcessingIntent, TransitionResult
from document_service.domain.value import (
    Action,
    DocumentId,
    DocumentStatus,
    DocumentVersionId,
    IdempotencyKey,
    IntentKind,
    IntentState,
    RequestId,
)
from document_service.utils.ids import UlidGenerator


@dataclass(frozen=True, slots=True)
class TransitionStatusCommand:
    """Yêu cầu chuyển trạng thái một phiên bản."""

    document_id: DocumentId
    version_id: DocumentVersionId
    target_status: DocumentStatus
    principal: Principal
    idempotency_key: IdempotencyKey


class ApproveVersionUseCase(WriteUseCase[TransitionStatusCommand, TransitionResult]):
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
        self._saga = StatusChangeSaga(ports, builder or CatalogMetadataBuilder())
        self._snapshot = StatusChangeSnapshot()

    async def execute(self, command: TransitionStatusCommand) -> TransitionResult:
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

    async def _transition(self, command: TransitionStatusCommand) -> TransitionResult:
        """Phần chạy trong khóa: đọc lại tài liệu, chuyển trạng thái, ghi catalog."""
        previous = await self.ports.intents.find_by_idempotency_key(command.idempotency_key)
        if previous is not None:
            return self._replay(command, previous)
        pending = await self.ports.intents.find_unfinished(timedelta(0), IntentKind.STATUS_CHANGE)
        if any(intent.document_id == command.document_id for intent in pending):
            raise ConcurrencyConflictError("another status change is awaiting recovery")
        document = await self.ports.catalog.read_document(command.document_id)
        result = self._policies.lifecycle.transition(
            document, command.version_id, command.target_status, command.principal.as_actor()
        )
        plan = StatusChangePlan(
            result, str(document.current_version_id or ""), command.principal.principal_id
        )
        intent = ProcessingIntent(
            request_id=RequestId(UlidGenerator().new_id("REQ")),
            idempotency_key=command.idempotency_key,
            document_id=command.document_id,
            version_id=command.version_id,
            expected_checksum=None,
            kind=IntentKind.STATUS_CHANGE,
            state=IntentState.STATUS_CHANGE_PENDING,
            payload=self._snapshot.to_payload(plan),
        )
        await self.ports.intents.create(intent)
        try:
            await self._saga.resume(intent)
        except DependencyUnavailableError as error:
            intent.register_retry(str(error))
            await self.ports.intents.save(intent)
            raise
        return result

    def _replay(
        self, command: TransitionStatusCommand, intent: ProcessingIntent
    ) -> TransitionResult:
        """Chỉ phát lại kết quả khi cùng tài liệu, phiên bản, người gọi và lệnh."""
        if (
            intent.kind is not IntentKind.STATUS_CHANGE
            or intent.state is not IntentState.COMPLETED
            or intent.document_id != command.document_id
            or intent.version_id != command.version_id
        ):
            raise ConcurrencyConflictError("idempotency key conflicts with an existing operation")
        plan = self._snapshot.from_payload(intent.payload)
        if (
            plan.result.changed.status != command.target_status
            or plan.actor != command.principal.principal_id
        ):
            raise ConcurrencyConflictError("idempotency key belongs to another status change")
        return plan.result
