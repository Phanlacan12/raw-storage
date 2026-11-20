"""IssueDownloadUseCase: cấp file theo quyền (bất biến I11, test case POC-04, POC-23).

Hai đường cấp file theo mục 2.6 báo cáo: link có thời hạn cho tài liệu thông thường,
và proxy qua dịch vụ cho tài liệu cần thu hồi ngay. Policy được kiểm tra **ngay tại
thời điểm gọi**, không dựa vào kết quả kiểm tra trước đó.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from document_service.application.context import PortBundle
from document_service.application.usecase.base import AuditOutcome, AuditTarget, ReadUseCase
from document_service.domain.dto import DownloadGrant
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import Principal
from document_service.domain.value import Action, DocumentId, DocumentVersionId


@dataclass(frozen=True, slots=True)
class IssueDownloadCommand:
    """Yêu cầu tải một phiên bản."""

    document_id: DocumentId
    version_id: DocumentVersionId
    principal: Principal
    cached_only: bool = False


class IssueDownloadUseCase(ReadUseCase[IssueDownloadCommand, DownloadGrant]):
    """Quyết định quyền rồi cấp link hoặc đánh dấu phải proxy."""

    def __init__(self, ports: PortBundle, presign_ttl_seconds: int = 300) -> None:
        """Nhận bundle port và thời hạn link tải."""
        super().__init__(ports)
        self._ttl_seconds = presign_ttl_seconds

    async def execute(self, command: IssueDownloadCommand) -> DownloadGrant:
        """Cấp quyền tải, ghi audit cho cả trường hợp bị từ chối."""
        try:
            if command.cached_only:
                return await self._issue_cached(command)
            await self._authorize(command.principal, Action.DOWNLOAD, str(command.document_id))
        except PolicyDeniedError as error:
            await self._audit(command, AuditOutcome.denied(str(error)))
            raise
        document = await self.ports.catalog.read_document(command.document_id)
        version = document.find_version(command.version_id)
        policy = await self.ports.policies.effective_policy(command.document_id)
        if document.access_policy.require_proxy_download or policy.require_proxy_download:
            await self._audit(command, AuditOutcome(result="proxy"))
            return DownloadGrant(version_id=version.version_id, proxied=True)
        url = await self.ports.objects.presign(
            version.storage_uri, timedelta(seconds=self._ttl_seconds)
        )
        await self._audit(
            command, AuditOutcome(result="presigned", detail=f"ttl={self._ttl_seconds}s")
        )
        return DownloadGrant(
            version_id=version.version_id,
            url=url,
            expires_in_seconds=self._ttl_seconds,
        )

    async def _issue_cached(self, command: IssueDownloadCommand) -> DownloadGrant:
        """Cấp link từ cache xác thực, không gọi catalog khi đang suy giảm."""
        cached = self.ports.policies.cached_download(
            command.principal, command.document_id, command.version_id
        )
        if cached is None:
            raise PolicyDeniedError("no current cached download authorization for this version")
        uri, remaining = cached
        ttl = min(self._ttl_seconds, remaining)
        url = await self.ports.objects.presign(uri, timedelta(seconds=ttl))
        await self._audit(
            command, AuditOutcome(result="presigned", detail=f"cached policy ttl={ttl}s")
        )
        return DownloadGrant(version_id=command.version_id, url=url, expires_in_seconds=ttl)

    async def _audit(self, command: IssueDownloadCommand, outcome: AuditOutcome) -> None:
        """Ghi audit mỗi lần cấp hoặc từ chối cấp file."""
        await self._record(
            command.principal,
            "version.download",
            AuditTarget.of_version(command.document_id, command.version_id),
            outcome,
        )
