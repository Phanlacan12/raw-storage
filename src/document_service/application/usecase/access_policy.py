"""Use case cập nhật chính sách truy cập của tài liệu (D9).

Quyền được ghi qua Document Service chứ không qua UI của catalog, để mọi lượt đổi
quyền đều đi qua audit — yêu cầu mục 2.6 báo cáo và bất biến I11.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from document_service.application.context import PortBundle
from document_service.application.orchestration.command_receipt import command_receipt
from document_service.application.usecase.base import AuditOutcome, AuditTarget, WriteUseCase
from document_service.domain.metadata_builder import CatalogMetadataBuilder
from document_service.domain.model import AccessPolicy, DomainEvent, Principal
from document_service.domain.value import Action, DocumentId, IdempotencyKey


@dataclass(frozen=True, slots=True)
class UpdateAccessPolicyCommand:
    """Yêu cầu cập nhật chính sách truy cập của tài liệu."""

    document_id: DocumentId
    principal: Principal
    access_policy: AccessPolicy = field(default_factory=AccessPolicy)
    idempotency_key: IdempotencyKey | None = None


class UpdateAccessPolicyUseCase(WriteUseCase[UpdateAccessPolicyCommand, AccessPolicy]):
    """Cập nhật access_policy và ghi audit để downstream đồng bộ."""

    def __init__(self, ports: PortBundle, builder: CatalogMetadataBuilder | None = None) -> None:
        """Nhận bundle port và bộ dựng metadata."""
        super().__init__(ports)
        self._builder = builder or CatalogMetadataBuilder()

    async def execute(self, command: UpdateAccessPolicyCommand) -> AccessPolicy:
        """Ghi policy mới qua Document Service, không qua catalog UI."""
        await self._authorize(command.principal, Action.MANAGE_POLICY, str(command.document_id))
        async with command_receipt(
            self.ports.intents,
            "access.update",
            asdict(command),
            command.idempotency_key,
            command.document_id,
        ) as receipt:
            if receipt.replayed:
                return command.access_policy
            document = await self.ports.catalog.read_document(command.document_id)
            document.access_policy = command.access_policy
            await self.ports.catalog.patch_document_fields(
                command.document_id, self._builder.policy_fields(document.access_policy)
            )
            await self.ports.policies.invalidate(command.document_id)
            await self._publish(
                DomainEvent(
                    "access.changed",
                    command.document_id,
                    payload={
                        "actor": command.principal.principal_id,
                        "classification": command.access_policy.classification,
                    },
                )
            )
            await self._record(
                command.principal,
                "document.access_policy_changed",
                AuditTarget.of_document(command.document_id),
                AuditOutcome.ok(command.access_policy.classification),
            )
            return command.access_policy
