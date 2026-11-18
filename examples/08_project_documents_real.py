"""Ví dụ 8 — Use case URD–SRS–SAD của Project A trên hạ tầng **thật**, với PDF **thật**.

Chạy:

    docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
    set -a && source deploy/.env && set +a
    uv run python examples/08_project_documents_real.py

Đây là ví dụ 02 chạy lại trên OpenMetadata và Object Storage thật, upload file PDF thật
trong `examples/fixtures/` thay vì vài chục byte giả. Ví dụ 02 chứng minh **logic đúng**;
ví dụ này chứng minh **hệ thống thật làm được**, gồm cả những thứ mock không trả lời
được: file nhị phân đi trọn vòng lên S3 rồi về, và quan hệ theo phiên bản sống sót qua
một catalog thật.

Ba điều cần chứng minh, giống POC-05, POC-06, POC-09:

- tra cứu được toàn bộ tài liệu của dự án qua một đầu mối;
- từ SRS v2.0 tìm được URD v1.2, và truy vấn ngược cũng đúng;
- tạo SRS v2.1 **không** làm mất quan hệ cũ và không tự đổi đích sang bản mới.

Khác ví dụ 02: gọi thẳng use case trong container chứ không qua HTTP, và bước tra cứu
cuối dùng `list_versions` chứ **không** dùng Search API — OpenMetadata 1.12.0 không
index nổi File entity có custom property, xem ví dụ 07 để biết chi tiết đã đo.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from _common import check, heading, line

REQUIRED_ENV = ("DS_CATALOG__BASE_URL", "DS_STORAGE__ENDPOINT", "DS_STORAGE__BUCKET")
FIXTURES = Path(__file__).resolve().parent / "fixtures"
COLLECTION = "PROJECT-A"
PDF = "application/pdf"


def _missing_env() -> list[str]:
    """Danh sách biến môi trường còn thiếu."""
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def _print_instructions(missing: list[str]) -> None:
    """In hướng dẫn dựng hạ tầng."""
    print("This example needs real infrastructure, these env vars are missing:")
    for name in missing:
        print(f"  - {name}")
    print("\nHow to run:")
    print("  make compose-up && make compose-ready")
    print("  set -a && source deploy/.env && set +a")
    print("  uv run python examples/08_project_documents_real.py")
    print("\nDetails: deploy/README.md")


def _read_fixture(file_name: str) -> bytes:
    """Đọc một PDF mẫu, báo lỗi rõ nếu chưa sinh."""
    path = FIXTURES / file_name
    if not path.is_file():
        print(f"Missing fixture: {path}")
        print("Generate them with: uv run python examples/fixtures/generate_pdfs.py")
        sys.exit(1)
    return path.read_bytes()


async def main() -> None:  # noqa: C901 - kịch bản tuyến tính, tách nhỏ sẽ khó đọc hơn
    """Chạy kịch bản dự án trên hạ tầng thật."""
    missing = _missing_env()
    if missing:
        _print_instructions(missing)
        return

    # Đặt profile TRƯỚC khi import document_service: config đọc biến môi trường ngay
    # lúc import. Đó là lý do mọi import bên dưới nằm trong hàm.
    os.environ["DS_APP__PROFILE"] = "openmetadata"
    from document_service.adapter.outbound.openmetadata.bootstrap import OmSchemaMigration
    from document_service.adapter.outbound.openmetadata.client import OmHttpClient
    from document_service.application.usecase.approve_version import TransitionStatusCommand
    from document_service.application.usecase.create_version import CreateVersionCommand
    from document_service.application.usecase.register_document import RegisterDocumentCommand
    from document_service.application.usecase.relationships import (
        DeclareRelationshipCommand,
        QueryRelationshipsCommand,
    )
    from document_service.config import SettingsProvider
    from document_service.domain.dto import UploadRequest
    from document_service.domain.model import DocumentMetadata, Principal
    from document_service.domain.value import (
        Checksum,
        Direction,
        DocumentStatus,
        IdempotencyKey,
        RelationType,
        VersionLabel,
    )
    from document_service.infrastructure.container import ServiceContainer
    from document_service.utils.hashing import digest_of
    from document_service.utils.singleton import SingletonMeta

    SingletonMeta.clear()
    settings = SettingsProvider().reload()
    container = ServiceContainer(settings)
    principal = Principal(principal_id="example", groups=("document-admins",), is_admin=True)

    # === BƯỚC 1 ======================================================================
    heading("1. Prepare the schema on OpenMetadata")
    client = OmHttpClient(settings.catalog, container.executor("catalog"))
    try:
        await OmSchemaMigration(client, settings.catalog).run_on_startup()
        print("  [OK  ] schema migration finished")
    except Exception as error:  # hạ tầng thật có thể từ chối vì nhiều lý do
        print(f"  [FAIL] migration failed: {error}")
        print("  Check DS_CATALOG__BOT_TOKEN and the server version.")
        await client.aclose()
        sys.exit(1)

    async def register(document_type: str, title: str) -> Any:
        """Đăng ký một tài liệu của Project A."""
        return await container.use_cases.register_document().execute(
            RegisterDocumentCommand(
                principal=principal,
                metadata=DocumentMetadata(
                    title=title, document_type=document_type, collection_id=COLLECTION
                ),
            )
        )

    async def upload(document: Any, label: str, file_name: str) -> Any:
        """Upload một PDF thật làm phiên bản mới, rồi duyệt luôn."""
        payload = _read_fixture(file_name)

        def stream_factory() -> object:
            async def iterator() -> object:
                yield payload

            return iterator()

        result = await container.use_cases.create_version().execute(
            CreateVersionCommand(
                request=UploadRequest(
                    document_id=document.document_id,
                    original_file_name=file_name,
                    content_format=PDF,
                    checksum=Checksum(algorithm="sha256", hex_digest=digest_of(payload)),
                    size_bytes=len(payload),
                    actor=principal.as_actor(),
                    # Khoá theo document_id (mới mỗi lần chạy) + nhãn phiên bản, KHÔNG
                    # theo checksum: khoá theo checksum thì lần chạy sau bị replay lại
                    # phiên bản của lần đầu, gắn vào document cũ.
                    idempotency_key=IdempotencyKey(f"proj-{document.document_id}-{label}"),
                    label=VersionLabel(label),
                ),
                principal=principal,
                stream_factory=stream_factory,
            )
        )
        await container.use_cases.approve_version().execute(
            TransitionStatusCommand(
                document_id=document.document_id,
                version_id=result.version.version_id,
                target_status=DocumentStatus.APPROVED,
                principal=principal,
            )
        )
        line(f"{file_name}", f"{len(payload)} bytes -> {result.version.version_id}")
        return result.version

    async def relate(relation: RelationType, source: Any, target: Any) -> None:
        """Khai báo một quan hệ giữa hai phiên bản."""
        await container.use_cases.declare_relationship().execute(
            DeclareRelationshipCommand(
                relation_type=relation,
                source_version_id=source.version_id,
                target_version_id=target.version_id,
                principal=principal,
            )
        )
        check(f"declared {relation}", True)

    async def edges(version: Any, direction: Direction) -> list[Any]:
        """Quan hệ của một phiên bản theo chiều cho trước."""
        return await container.use_cases.query_relationships().execute(
            QueryRelationshipsCommand(
                version_id=version.version_id, principal=principal, direction=direction
            )
        )

    # === BƯỚC 2 ======================================================================
    heading("2. Create three documents for Project A")
    urd = await register("URD", "User Requirements Document")
    srs = await register("SRS", "Software Requirements Specification")
    sad = await register("SAD", "Software Architecture Document")
    line("URD", urd.document_id)
    line("SRS", srs.document_id)
    line("SAD", sad.document_id)

    # === BƯỚC 3 ======================================================================
    # Mỗi lần upload là một file PDF thật đi lên S3 thật, không phải vài chục byte giả.
    heading("3. Upload the real PDF versions and approve them")
    urd_v10 = await upload(urd, "1.0", "URD-PROJECT-A-v1.0.pdf")
    urd_v12 = await upload(urd, "1.2", "URD-PROJECT-A-v1.2.pdf")
    srs_v20 = await upload(srs, "2.0", "SRS-PROJECT-A-v2.0.pdf")
    sad_v11 = await upload(sad, "1.1", "SAD-PROJECT-A-v1.1.pdf")
    check("four versions created", all(v is not None for v in (urd_v10, urd_v12, srs_v20, sad_v11)))

    # === BƯỚC 4 ======================================================================
    # Quan hệ gắn vào PHIÊN BẢN chứ không gắn vào tài liệu: đó là điều kiện để bước 6
    # chứng minh được quan hệ cũ không bị đổi đích khi có bản mới.
    heading("4. Declare relationships per version")
    await relate(RelationType.DERIVED_FROM, srs_v20, urd_v12)
    await relate(RelationType.REFERENCES, sad_v11, srs_v20)

    # === BƯỚC 5 ======================================================================
    heading("5. Trace from SRS v2.0 and back from URD v1.2")
    outgoing = await edges(srs_v20, Direction.OUTGOING)
    for item in outgoing:
        line(str(item.relation_type), f"-> {item.target_version_id}")
    check(
        "SRS v2.0 derived_from URD v1.2",
        any(
            item.relation_type is RelationType.DERIVED_FROM
            and item.target_version_id == urd_v12.version_id
            for item in outgoing
        ),
    )
    incoming = await edges(urd_v12, Direction.INCOMING)
    # Với chiều INCOMING, registry gọi `reversed_direction()` nên phiên bản đang hỏi
    # luôn nằm ở `source_version_id`, còn đầu kia nằm ở `target_version_id`. Đây là
    # góc nhìn "hàng xóm", không phải chiều thật của cạnh.
    for item in incoming:
        line(str(item.relation_type), f"<- {item.target_version_id}")
    check(
        "URD v1.2 is derived by SRS v2.0",
        any(item.target_version_id == srs_v20.version_id for item in incoming),
    )

    # === BƯỚC 6 ======================================================================
    heading("6. Create SRS v2.1 - existing relationships must stay")
    srs_v21 = await upload(srs, "2.1", "SRS-PROJECT-A-v2.1.pdf")
    after = await edges(srs_v20, Direction.OUTGOING)
    check(
        "v2.0 relationship target unchanged",
        [item.target_version_id for item in after] == [urd_v12.version_id],
    )
    check("v2.1 has no relationship yet", await edges(srs_v21, Direction.OUTGOING) == [])

    # === BƯỚC 7 ======================================================================
    # Dùng list_versions của catalog thật, KHÔNG dùng Search API: OpenMetadata 1.12.0
    # không index được File entity có custom property (đo ở ví dụ 07), nên search luôn
    # trả rỗng và sẽ làm bước này sai một cách khó hiểu.
    heading("7. Read the project back from the real catalog")
    found: list[tuple[str, str]] = []
    for document in (urd, srs, sad):
        reread = await container.ports.catalog.read_document(document.document_id)
        versions = await container.ports.catalog.list_versions(document.document_id)
        current = [v for v in versions if v.version_id == reread.current_version_id]
        label = str(current[0].label) if current else "-"
        line(document.metadata.document_type, f"{len(versions)} versions, current {label}")
        found.append((document.metadata.document_type, label))
    check("all three document types", sorted(t for t, _ in found) == ["SAD", "SRS", "URD"])
    check("SRS current version is 2.1", dict(found)["SRS"] == "2.1")

    # === BƯỚC 8 ======================================================================
    # Tờ khai trong catalog đúng KHÔNG đảm bảo ruột file đúng. Chỉ tải về so sánh
    # sha256 mới biết chắc đúng PDF đó nằm trên S3.
    heading("8. Download one PDF back and verify the bytes")
    source = _read_fixture("SRS-PROJECT-A-v2.0.pdf")
    url = await container.presigned_issuer().issue(srs_v20.storage_uri)
    async with httpx.AsyncClient(timeout=30.0) as downloader:
        fetched = await downloader.get(url)
    line("HTTP status", fetched.status_code)
    line("downloaded (bytes)", len(fetched.content))
    line("is a real PDF", fetched.content[:5] == b"%PDF-")
    check("download returns 200", fetched.status_code == 200)
    check("byte count matches the upload", len(fetched.content) == len(source))
    check("checksum round-trips through S3", digest_of(fetched.content) == digest_of(source))

    await client.aclose()
    print("\nExample 8 complete.")


if __name__ == "__main__":
    asyncio.run(main())
