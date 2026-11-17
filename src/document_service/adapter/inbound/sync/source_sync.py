"""D17 Sync Orchestrator: đồng bộ tài liệu từ nguồn hiện có.

Theo mục 2.1, 3.4 và 6.4 của báo cáo, cộng luồng 6 ở docs/c4-05-dynamic-views.md.
Hai nguyên tắc quan trọng:

1. **Connector không phải đường ghi.** Mọi file đi qua `CreateVersionUseCase`, nên
   quy tắc phiên bản, chống trùng nội dung, intent bền vững và audit đều được áp dụng
   như khi người dùng tự upload.
2. **Quyền chưa ánh xạ được thì hạn chế.** `SourcePermissionMapper` chỉ mở quyền khi
   cấu hình nói rõ nhóm nào được xem; để trống thì tài liệu ở chế độ `restricted`
   (bất biến I11), không bao giờ tự công khai.

Sửa file ở nguồn tạo **phiên bản nội dung mới**, còn file không đổi thì bị chặn bởi
`DedupPolicy` nên không sinh phiên bản rác (test case POC-12).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Iterable

from document_service.application.usecase.create_version import (
    CreateVersionCommand,
    CreateVersionUseCase,
)
from document_service.application.usecase.register_document import (
    RegisterDocumentCommand,
    RegisterDocumentUseCase,
)
from document_service.config import SourceSettings, SyncSettings
from document_service.domain.dto import UploadRequest
from document_service.domain.errors import DomainError
from document_service.domain.model import AccessPolicy, DocumentMetadata, Principal
from document_service.domain.value import Checksum, DocumentId, IdempotencyKey
from document_service.utils.hashing import StreamingHasher
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class SourceFile:
    """Một file phát hiện được ở nguồn."""

    source_id: str
    relative_path: str
    file_name: str
    content_format: str
    payload: bytes

    @property
    def checksum(self) -> Checksum:
        """Checksum nội dung file."""
        hasher = StreamingHasher()
        hasher.update(self.payload)
        return Checksum(algorithm=hasher.algorithm, hex_digest=hasher.hex_digest())

    @property
    def document_key(self) -> str:
        """Khóa định danh tài liệu suy ra từ nguồn và đường dẫn tương đối."""
        safe = self.relative_path.replace("/", "-").replace(" ", "_").replace(".", "-")
        return f"{self.source_id}-{safe}"


@dataclass(slots=True)
class SyncReport:
    """Kết quả một lượt đồng bộ."""

    scanned: int = 0
    documents_registered: int = 0
    versions_created: int = 0
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)

    def as_payload(self) -> dict[str, object]:
        """Dạng dict để log."""
        return {
            "scanned": self.scanned,
            "documents_registered": self.documents_registered,
            "versions_created": self.versions_created,
            "unchanged": self.unchanged,
            "failed": len(self.failed),
        }


class SourceConnector(ABC):
    """Base class của connector đọc nguồn tài liệu hiện có."""

    def __init__(self, settings: SourceSettings) -> None:
        """Nhận cấu hình của một nguồn."""
        self._settings = settings

    @property
    def source_id(self) -> str:
        """Định danh nguồn."""
        return self._settings.source_id

    @property
    def settings(self) -> SourceSettings:
        """Cấu hình của nguồn."""
        return self._settings

    @abstractmethod
    def discover(self) -> Iterable[SourceFile]:
        """Liệt kê các file cần đồng bộ."""


class FileSystemSourceConnector(SourceConnector):
    """Đọc nguồn dạng thư mục: file share đã mount, bản sao Drive, thư mục dự án."""

    _FORMATS = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }

    def discover(self) -> Iterable[SourceFile]:
        """Quét thư mục gốc, chỉ nhận các đuôi file được cấu hình."""
        root = Path(self._settings.root_path).expanduser()
        if not root.is_dir():
            _LOGGER.warning(
                "nguồn không truy cập được",
                extra={"source_id": self.source_id, "root_path": str(root)},
            )
            return []
        allowed = {item.lower() for item in self._settings.file_extensions}
        files: list[SourceFile] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed:
                continue
            files.append(
                SourceFile(
                    source_id=self.source_id,
                    relative_path=str(path.relative_to(root)),
                    file_name=path.name,
                    content_format=self._FORMATS.get(
                        path.suffix.lower(), "application/octet-stream"
                    ),
                    payload=path.read_bytes(),
                )
            )
        return files


class SourcePermissionMapper:
    """Ánh xạ quyền từ nguồn sang `AccessPolicy` của kho."""

    def map(self, settings: SourceSettings) -> AccessPolicy:
        """Policy cho tài liệu đến từ một nguồn.

        Không ánh xạ được nhóm nào thì giữ `restricted`: chỉ owner và quản trị viên
        được ủy quyền truy cập (bất biến I11, mục 2.6 báo cáo).
        """
        if not settings.allowed_groups:
            return AccessPolicy(classification="restricted")
        return AccessPolicy(
            classification=settings.classification,
            allowed_groups=tuple(settings.allowed_groups),
        )


class SourceSyncJob:
    """Đồng bộ một lượt từ các nguồn đã cấu hình qua đường ghi chính."""

    def __init__(
        self,
        register_document: RegisterDocumentUseCase,
        create_version: CreateVersionUseCase,
        settings: SyncSettings,
        principal: Principal | None = None,
    ) -> None:
        """Nhận hai use case ghi, cấu hình đồng bộ và chủ thể chạy job."""
        self._register_document = register_document
        self._create_version = create_version
        self._settings = settings
        self._known_documents: set[str] = set()
        self._principal = principal or Principal(
            principal_id="source-sync", groups=("document-admins",), is_admin=True
        )
        self._permissions = SourcePermissionMapper()

    def connectors(self) -> list[SourceConnector]:
        """Dựng connector cho từng nguồn trong cấu hình."""
        built: list[SourceConnector] = []
        for source in self._settings.sources:
            if source.source_type == "filesystem":
                built.append(FileSystemSourceConnector(source))
            else:
                _LOGGER.warning(
                    "chưa hỗ trợ loại nguồn này",
                    extra={"source_id": source.source_id, "source_type": source.source_type},
                )
        return built

    async def run_once(self) -> SyncReport:
        """Quét mọi nguồn và đăng ký tài liệu, phiên bản còn thiếu."""
        report = SyncReport()
        for connector in self.connectors():
            files = list(connector.discover())[: self._settings.batch_size]
            for source_file in files:
                report.scanned += 1
                await self._sync_file(connector, source_file, report)
        _LOGGER.info("đồng bộ nguồn xong", extra=report.as_payload())
        return report

    async def _sync_file(
        self, connector: SourceConnector, source_file: SourceFile, report: SyncReport
    ) -> None:
        """Đăng ký tài liệu nếu chưa có, rồi tạo phiên bản nếu nội dung đổi."""
        document_id = DocumentId(source_file.document_key)
        try:
            await self._ensure_document(connector, source_file, document_id, report)
            result = await self._create_version.execute(
                self._version_command(source_file, document_id)
            )
            if result.created:
                report.versions_created += 1
            else:
                report.unchanged += 1
        except DomainError as error:
            report.failed.append(f"{source_file.relative_path}: {error}")
            _LOGGER.warning(
                "đồng bộ một file thất bại",
                extra={"source_id": connector.source_id, "error": str(error)},
            )

    async def _ensure_document(
        self,
        connector: SourceConnector,
        source_file: SourceFile,
        document_id: DocumentId,
        report: SyncReport,
    ) -> None:
        """Đăng ký tài liệu; bỏ qua nếu lượt đồng bộ trước đã đăng ký.

        Không gọi lại đường ghi khi không cần: mỗi lần đăng ký đều sinh audit, nên
        đăng ký lại mỗi lượt quét sẽ làm audit đầy bản ghi vô nghĩa.
        """
        if str(document_id) in self._known_documents:
            return
        settings = connector.settings
        command = RegisterDocumentCommand(
            principal=self._principal,
            metadata=DocumentMetadata(
                title=source_file.file_name,
                document_type=settings.document_type,
                owner=f"source:{settings.source_id}",
                collection_id=settings.collection_id,
            ),
            access_policy=self._permissions.map(settings),
            document_id=document_id,
        )
        await self._register_document.execute(command)
        self._known_documents.add(str(document_id))
        report.documents_registered += 1

    def _version_command(
        self, source_file: SourceFile, document_id: DocumentId
    ) -> CreateVersionCommand:
        """Dựng command tạo phiên bản từ một file ở nguồn."""
        checksum = source_file.checksum
        payload = source_file.payload
        request = UploadRequest(
            document_id=document_id,
            original_file_name=source_file.file_name,
            content_format=source_file.content_format,
            checksum=checksum,
            size_bytes=len(payload),
            actor=self._principal.as_actor(),
            idempotency_key=IdempotencyKey(f"sync-{checksum.hex_digest[:24]}"),
            label=None,
        )

        def stream_factory() -> AsyncIterator[bytes]:
            async def iterator() -> AsyncIterator[bytes]:
                for index in range(0, len(payload), _CHUNK_SIZE):
                    yield payload[index : index + _CHUNK_SIZE]

            return iterator()

        return CreateVersionCommand(
            request=request, principal=self._principal, stream_factory=stream_factory
        )


class SourceSyncScheduler:
    """Chạy `SourceSyncJob` theo chu kỳ trong cấu hình."""

    def __init__(self, job: SourceSyncJob, settings: SyncSettings) -> None:
        """Nhận job và cấu hình chu kỳ."""
        self._job = job
        self._settings = settings

    @property
    def enabled(self) -> bool:
        """Đồng bộ có được bật hay không."""
        return self._settings.enabled and bool(self._settings.sources)

    async def run_forever(self) -> None:
        """Lặp vô hạn, nghỉ giữa hai lượt theo `interval_seconds`."""
        if not self.enabled:
            _LOGGER.info("đồng bộ nguồn đang tắt trong cấu hình")
            return
        while True:
            await self._job.run_once()
            await asyncio.sleep(self._settings.interval_seconds)
