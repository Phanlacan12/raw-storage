"""Ví dụ 5 — Đồng bộ từ nguồn hiện có (D17, POC-12).

Chạy: uv run python examples/05_source_sync.py

Tạo một thư mục giả làm file share, chạy `SourceSyncJob`, rồi chứng minh:

- connector **không** là đường ghi: mọi file đi qua use case nên có intent và audit;
- file không đổi thì không sinh phiên bản mới;
- sửa file ở nguồn tạo **phiên bản nội dung mới**;
- nguồn chưa ánh xạ quyền thì tài liệu ở chế độ hạn chế (bất biến I11).
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from _common import check, heading, line, reset_container, use_fake_profile


async def main() -> None:
    """Chạy kịch bản đồng bộ nguồn."""
    use_fake_profile()
    reset_container()

    from document_service.adapter.inbound.sync.source_sync import (
        SourcePermissionMapper,
        SourceSyncJob,
    )
    from document_service.config import SourceSettings, SyncSettings
    from document_service.domain.value import DocumentId
    from document_service.infrastructure.container import ServiceContainer

    with tempfile.TemporaryDirectory(prefix="raw-storage-example-") as temp_dir:
        root = Path(temp_dir) / "fileshare" / "du-an-a"
        root.mkdir(parents=True)
        (root / "urd.pdf").write_bytes(b"URD ban dau")
        (root / "srs.docx").write_bytes(b"SRS ban dau")
        (root / "ghi-chu.tmp").write_bytes(b"file tam, phai bo qua")

        heading("1. The source to sync")
        for path in sorted(root.iterdir()):
            line(path.name, f"{path.stat().st_size} byte")

        source = SourceSettings(
            source_id="file-share",
            source_type="filesystem",
            root_path=str(root),
            collection_id="PROJECT-A",
            document_type="SRS",
            classification="internal",
        )
        settings = SyncSettings(enabled=True, interval_seconds=60.0, sources=[source])
        container = ServiceContainer()
        job = SourceSyncJob(
            container.use_cases.register_document(),
            container.use_cases.create_version(),
            settings,
        )

        heading("2. First sync run")
        first = await job.run_once()
        line("files scanned", first.scanned)
        line("documents registered", first.documents_registered)
        line("versions created", first.versions_created)
        check("skips .tmp files", first.scanned == 2)
        check("both versions created", first.versions_created == 2)

        heading("3. Second run, source unchanged")
        second = await job.run_once()
        line("versions created", second.versions_created)
        line("files unchanged", second.unchanged)
        check("no junk version created", second.versions_created == 0)

        heading("4. Modify one file at the source")
        (root / "srs.docx").write_bytes(b"SRS cap nhat lan 1")
        third = await job.run_once()
        line("versions created", third.versions_created)
        document_id = DocumentId("file-share-srs-docx")
        document = await container.ports.catalog.read_document(document_id)
        for version in document.versions:
            line(f"  {version.label}", f"{version.size_bytes} byte · {version.status}")
        check("exactly one new version", third.versions_created == 1)
        check("keeps both versions", len(document.versions) == 2)

        heading("5. Document permissions come from the source")
        line("classification", document.access_policy.classification)
        unmapped = SourcePermissionMapper().map(
            SourceSettings(source_id="chua-anh-xa", root_path=str(root))
        )
        line("source without permission mapping", unmapped.classification)
        check("unmapped source falls back to restricted", unmapped.classification == "restricted")

        heading("6. Sync goes through the main write path")
        audit = await container.ports.audit.list_for_document(document_id)
        for event in audit:
            line(event.action, f"{event.result} · {event.actor.principal_id}")
        actions = [event.action for event in audit]
        check("audit has document registration", "document.registered" in actions)
        check("audit has version creation", actions.count("version.created") == 2)

        print("\nExample 5 complete.")


if __name__ == "__main__":
    asyncio.run(main())
