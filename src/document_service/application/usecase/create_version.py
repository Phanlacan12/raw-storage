"""CreateVersionUseCase: tạo một phiên bản nội dung mới.

Thứ tự bước theo sequence ở mục 6 của docs/c4-04b-code-structure.md và luồng 1 ở
docs/c4-05-dynamic-views.md: kiểm tra idempotency → khóa tài liệu → chống trùng nội
dung → sinh phiên bản → ghi intent → ghi object → đăng ký catalog → phát sự kiện.
"""

from __future__ import annotations

from dataclasses import dataclass

from document_service.application.context import PolicySet, PortBundle
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.application.orchestration.idempotency import IdempotencyGuard
from document_service.application.orchestration.snapshot import VersionSnapshot
from document_service.application.orchestration.upload_saga import StreamFactory, UploadSaga
from document_service.application.usecase.base import AuditOutcome, AuditTarget, WriteUseCase
from document_service.domain.dto import UploadRequest
from document_service.domain.errors import DependencyUnavailableError
from document_service.domain.model import (
    Document,
    DocumentVersion,
    DomainEvent,
    Principal,
    UploadIntent,
)
from document_service.domain.value import RequestId
from document_service.utils.ids import IdGenerator, UlidGenerator
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CreateVersionCommand:
    """Yêu cầu tạo phiên bản mới cho một tài liệu."""

    request: UploadRequest
    principal: Principal
    stream_factory: StreamFactory


@dataclass(frozen=True, slots=True)
class CreateVersionResult:
    """Kết quả tạo phiên bản."""

    version: DocumentVersion
    created: bool
    replayed: bool = False
    duplicate: bool = False


class CreateVersionUseCase(WriteUseCase[CreateVersionCommand, CreateVersionResult]):
    """Tạo phiên bản nội dung mới, giữ bất biến I1, I2, I3, I8, I13."""

    def __init__(
        self,
        ports: PortBundle,
        policies: PolicySet,
        builder: CatalogMetadataBuilder | None = None,
        ids: IdGenerator | None = None,
    ) -> None:
        """Dựng use case từ bundle port và tập policy."""
        super().__init__(ports)
        self._policies = policies
        self._builder = builder or CatalogMetadataBuilder()
        self._ids = ids or UlidGenerator()
        self._guard = IdempotencyGuard(ports.intents)
        self._saga = UploadSaga(ports.objects, ports.catalog, ports.intents)
        self._snapshot = VersionSnapshot()

    async def execute(self, command: CreateVersionCommand) -> CreateVersionResult:
        """Thực hiện toàn bộ luồng tạo phiên bản."""
        replay = await self._guard.inspect(command.request.idempotency_key)
        if replay.is_replay and replay.intent is not None:
            version = self._snapshot.from_payload(replay.intent.payload)
            return CreateVersionResult(version=version, created=False, replayed=True)
        await self._authorize_write(command.principal, "version")
        document_id = command.request.document_id
        return await self._run_exclusive(document_id, lambda: self._create(command))

    async def _create(self, command: CreateVersionCommand) -> CreateVersionResult:
        """Phần chạy trong khóa của tài liệu."""
        request = command.request
        document = await self.ports.catalog.read_document(request.document_id)
        duplicate = self._policies.dedup.duplicate_of(document, request.checksum)
        if duplicate is not None:
            await self._record(
                command.principal,
                "version.duplicate_skipped",
                AuditTarget.of_version(document.document_id, duplicate.version_id),
                AuditOutcome(result="skipped", detail=str(duplicate.checksum)),
            )
            return CreateVersionResult(version=duplicate, created=False, duplicate=True)
        version = self._policies.version.next_version(document, request)
        document.add_version(version)
        intent = self._new_intent(request, version)
        await self.ports.intents.create(intent)
        await self._run_saga(intent, document, version, command.stream_factory)
        await self._publish_created(command.principal, version)
        return CreateVersionResult(version=version, created=True)

    def _new_intent(self, request: UploadRequest, version: DocumentVersion) -> UploadIntent:
        """Dựng intent bền vững kèm snapshot phiên bản."""
        return UploadIntent(
            request_id=RequestId(self._ids.new_id(prefix="REQ")),
            idempotency_key=request.idempotency_key,
            document_id=request.document_id,
            version_id=version.version_id,
            expected_checksum=request.checksum,
            payload=self._snapshot.to_payload(version),
        )

    async def _run_saga(
        self,
        intent: UploadIntent,
        document: Document,
        version: DocumentVersion,
        stream_factory: StreamFactory,
    ) -> None:
        """Chạy saga ghi object và đăng ký catalog, ghi RetryPending khi lỗi."""
        metadata = self._builder.build(document, version)
        try:
            await self._saga.run(intent, version, metadata, stream_factory)
        except DependencyUnavailableError as error:
            intent.register_retry(str(error))
            await self.ports.intents.save(intent)
            _LOGGER.warning(
                "upload moved to RetryPending",
                extra={
                    "request_id": str(intent.request_id),
                    "version_id": str(version.version_id),
                    "dependency": error.dependency,
                },
            )
            raise

    async def _publish_created(self, principal: Principal, version: DocumentVersion) -> None:
        """Phát sự kiện và ghi audit sau khi tạo phiên bản thành công."""
        await self._publish(
            DomainEvent(
                event_type="version.created",
                document_id=version.document_id,
                version_id=version.version_id,
                payload={"version_label": str(version.label)},
            )
        )
        await self._record(
            principal,
            "version.created",
            AuditTarget.of_version(version.document_id, version.version_id),
            AuditOutcome.ok(str(version.checksum)),
        )
