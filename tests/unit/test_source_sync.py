"""Test D17 Sync Orchestrator (test case POC-12).

Khẳng định: connector **không** là đường ghi (mọi file đi qua use case), sửa file ở
nguồn tạo phiên bản nội dung mới, file không đổi không sinh phiên bản, và nguồn chưa
ánh xạ được quyền thì tài liệu ở chế độ hạn chế (bất biến I11).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from document_service.adapter.inbound.sync.source_sync import (
    FileSystemSourceConnector,
    SourcePermissionMapper,
    SourceSyncJob,
    SourceSyncScheduler,
)
from document_service.application.context import PolicySet, PortBundle
from document_service.application.metadata_builder import CatalogMetadataBuilder
from document_service.application.usecase.create_version import CreateVersionUseCase
from document_service.application.usecase.register_document import RegisterDocumentUseCase
from document_service.config import SourceSettings, SyncSettings
from document_service.domain.value import DocumentId


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    """Thư mục nguồn mẫu với hai file hợp lệ và một file bị bỏ qua."""
    root = tmp_path / "fileshare"
    (root / "du-an").mkdir(parents=True)
    (root / "du-an" / "srs.pdf").write_bytes(b"noi dung srs")
    (root / "du-an" / "urd.docx").write_bytes(b"noi dung urd")
    (root / "du-an" / "ghi-chu.tmp").write_bytes(b"bo qua")
    return root


def _source(root: Path, groups: list[str] | None = None) -> SourceSettings:
    """Cấu hình một nguồn filesystem."""
    return SourceSettings(
        source_id="file-share",
        source_type="filesystem",
        root_path=str(root),
        collection_id="PROJECT-A",
        document_type="SRS",
        classification="internal",
        allowed_groups=groups or [],
    )


def _job(ports: PortBundle, policies: PolicySet, settings: SyncSettings) -> SourceSyncJob:
    """Dựng job đồng bộ dùng use case thật."""
    builder = CatalogMetadataBuilder()
    return SourceSyncJob(
        RegisterDocumentUseCase(ports, builder),
        CreateVersionUseCase(ports, policies, builder),
        settings,
    )


class TestFileSystemConnector:
    """Quét nguồn dạng thư mục."""

    def test_discovers_allowed_extensions_only(self, source_root: Path) -> None:
        """Chỉ nhận đuôi file được cấu hình."""
        connector = FileSystemSourceConnector(_source(source_root))
        files = list(connector.discover())
        names = sorted(item.file_name for item in files)
        assert names == ["srs.pdf", "urd.docx"]

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        """Nguồn không truy cập được thì trả rỗng, không phát lỗi."""
        connector = FileSystemSourceConnector(_source(tmp_path / "khong-ton-tai"))
        assert list(connector.discover()) == []

    def test_document_key_is_stable(self, source_root: Path) -> None:
        """Khóa tài liệu suy ra từ nguồn và đường dẫn, không đổi giữa hai lượt quét."""
        connector = FileSystemSourceConnector(_source(source_root))
        first = {item.document_key for item in connector.discover()}
        second = {item.document_key for item in connector.discover()}
        assert first == second
        assert all(key.startswith("file-share-") for key in first)


class TestPermissionMapper:
    """Ánh xạ quyền từ nguồn."""

    def test_unmapped_source_is_restricted(self, source_root: Path) -> None:
        """I11: nguồn chưa ánh xạ nhóm thì tài liệu ở chế độ hạn chế."""
        policy = SourcePermissionMapper().map(_source(source_root))
        assert policy.classification == "restricted"
        assert policy.allowed_groups == ()

    def test_mapped_groups_are_applied(self, source_root: Path) -> None:
        """Có cấu hình nhóm thì áp dụng đúng nhóm và mức phân loại."""
        policy = SourcePermissionMapper().map(_source(source_root, ["du-an-a"]))
        assert policy.classification == "internal"
        assert policy.allowed_groups == ("du-an-a",)


class TestSourceSyncJob:
    """Luồng đồng bộ đi qua đường ghi chính."""

    async def test_first_run_creates_documents_and_versions(
        self, ports: PortBundle, policies: PolicySet, source_root: Path
    ) -> None:
        """Lượt đầu đăng ký tài liệu và tạo phiên bản cho mỗi file."""
        settings = SyncSettings(enabled=True, sources=[_source(source_root)])
        report = await _job(ports, policies, settings).run_once()
        assert report.scanned == 2
        assert report.versions_created == 2
        assert report.failed == []

    async def test_unchanged_file_creates_no_new_version(
        self, ports: PortBundle, policies: PolicySet, source_root: Path
    ) -> None:
        """POC-12: file không đổi thì không sinh phiên bản mới."""
        settings = SyncSettings(enabled=True, sources=[_source(source_root)])
        job = _job(ports, policies, settings)
        await job.run_once()
        second = await job.run_once()
        assert second.versions_created == 0
        assert second.unchanged == 2

    async def test_modified_file_creates_new_version(
        self, ports: PortBundle, policies: PolicySet, source_root: Path
    ) -> None:
        """POC-12: sửa file ở nguồn tạo phiên bản nội dung mới."""
        settings = SyncSettings(enabled=True, sources=[_source(source_root)])
        job = _job(ports, policies, settings)
        await job.run_once()
        (source_root / "du-an" / "srs.pdf").write_bytes(b"noi dung srs v2")
        report = await job.run_once()
        assert report.versions_created == 1
        document_id = DocumentId("file-share-du-an-srs-pdf")
        document = await ports.catalog.read_document(document_id)
        assert len(document.versions) == 2

    async def test_sync_goes_through_write_path(
        self, ports: PortBundle, policies: PolicySet, source_root: Path
    ) -> None:
        """Đồng bộ đi qua use case nên có intent và audit như khi người dùng upload."""
        settings = SyncSettings(enabled=True, sources=[_source(source_root)])
        await _job(ports, policies, settings).run_once()
        document_id = DocumentId("file-share-du-an-srs-pdf")
        events = await ports.audit.list_for_document(document_id)
        actions = [event.action for event in events]
        assert "document.registered" in actions
        assert "version.created" in actions

    async def test_batch_size_limits_work(
        self, ports: PortBundle, policies: PolicySet, source_root: Path
    ) -> None:
        """`batch_size` giới hạn số file xử lý mỗi lượt."""
        settings = SyncSettings(enabled=True, batch_size=1, sources=[_source(source_root)])
        report = await _job(ports, policies, settings).run_once()
        assert report.scanned == 1

    async def test_unknown_source_type_is_skipped(
        self, ports: PortBundle, policies: PolicySet, source_root: Path
    ) -> None:
        """Loại nguồn chưa hỗ trợ bị bỏ qua, không làm job chết."""
        source = _source(source_root)
        settings = SyncSettings(
            enabled=True,
            sources=[SourceSettings(**{**source.model_dump(), "source_type": "sharepoint"})],
        )
        report = await _job(ports, policies, settings).run_once()
        assert report.scanned == 0

    def test_scheduler_disabled_by_default(
        self, ports: PortBundle, policies: PolicySet, source_root: Path
    ) -> None:
        """Mặc định đồng bộ tắt, phải bật tường minh trong cấu hình."""
        disabled = SyncSettings(sources=[_source(source_root)])
        scheduler = SourceSyncScheduler(_job(ports, policies, disabled), disabled)
        assert scheduler.enabled is False
        enabled = SyncSettings(enabled=True, sources=[_source(source_root)])
        assert SourceSyncScheduler(_job(ports, policies, enabled), enabled).enabled is True
