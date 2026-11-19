"""RegisterDocumentUseCase: đăng ký một tài liệu logic mới."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from document_service.application.context import PortBundle
from document_service.application.orchestration.command_receipt import command_receipt
from document_service.application.usecase.base import AuditOutcome, AuditTarget, WriteUseCase
from document_service.domain.errors import DocumentNotFoundError
from document_service.domain.metadata_builder import CatalogMetadataBuilder
from document_service.domain.model import (
    AccessPolicy,
    Document,
    DocumentMetadata,
    DomainEvent,
    Principal,
)
from document_service.domain.value import DocumentId, IdempotencyKey
from document_service.utils.ids import IdGenerator, UlidGenerator


@dataclass(frozen=True, slots=True)
class RegisterDocumentCommand:
    """Yêu cầu đăng ký tài liệu."""

    principal: Principal
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    access_policy: AccessPolicy = field(default_factory=AccessPolicy)
    document_id: DocumentId | None = None
    retention_policy: str = ""
    idempotency_key: IdempotencyKey | None = None


class RegisterDocumentUseCase(WriteUseCase[RegisterDocumentCommand, Document]):
    """Tạo định danh tài liệu và đăng ký vào catalog."""

    def __init__(
        self,
        ports: PortBundle,
        builder: CatalogMetadataBuilder | None = None,
        ids: IdGenerator | None = None,
        require_existing_collection: bool = False,
    ) -> None:
        """Nhận bundle port, bộ dựng metadata và bộ sinh ID."""
        super().__init__(ports)
        self._builder = builder or CatalogMetadataBuilder()
        self._require_collection = require_existing_collection
        self._ids = ids or UlidGenerator()

    async def execute(self, command: RegisterDocumentCommand) -> Document:
        """Đăng ký tài liệu mới và ghi audit."""
        await self._authorize_write(command.principal, "document")
        async with command_receipt(
            self.ports.intents,
            "document.register",
            asdict(command),
            command.idempotency_key,
            command.document_id or DocumentId(self._ids.new_id(prefix="DOC")),
        ) as receipt:
            document = Document(
                document_id=receipt.document_id,
                metadata=command.metadata,
                access_policy=command.access_policy,
                retention_policy=command.retention_policy,
            )
            if receipt.replayed:
                return document
            if self._require_collection:
                collection_id = document.metadata.collection_id
                if (
                    not collection_id
                    or await self.ports.catalog.find_collection(collection_id) is None
                ):
                    raise DocumentNotFoundError(f"collection {collection_id!r} is not registered")
            await self.ports.catalog.register_document(document)
            await self._publish(DomainEvent("document.created", document.document_id))
            await self._record(
                command.principal,
                "document.registered",
                AuditTarget.of_document(document.document_id),
                AuditOutcome.ok(document.metadata.document_type),
            )
            return document
