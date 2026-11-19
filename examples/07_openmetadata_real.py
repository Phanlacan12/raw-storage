"""Ví dụ 7 — Chạy với OpenMetadata và Object Storage **thật**.

Chạy:

    docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
    set -a && source deploy/.env && set +a
    uv run python examples/07_openmetadata_real.py

Thiếu biến môi trường thì ví dụ **không** chạy giả lập: nó in hướng dẫn rồi dừng, để
không ai nhầm kết quả của profile fake với kết quả trên hạ tầng thật.

Ví dụ này là nơi kiểm chứng những điều mà mock không trả lời được: POC-19 (lọc custom
property qua Search API thật), migration schema chạy được, và vòng đời đầy đủ của một
file thật — upload lên S3, duyệt, rồi tải lại qua presigned URL và đối chiếu checksum.

Mặc định ví dụ tự sinh nội dung. Muốn dùng một file có sẵn trên máy:

    DS_EXAMPLE_FILE=/duong/dan/toi/file.pdf uv run python examples/07_openmetadata_real.py

Luồng sáu bước — toàn bộ đời của một file, từ lúc đưa vào tới lúc lấy ra:

    [1] Dựng sẵn các ô thông tin riêng       -> OpenMetadata
    [2] Hỏi hai phụ thuộc còn sống không     -> OpenMetadata + S3
    [3] Khai báo tài liệu rồi đẩy file lên   -> S3 (bytes) + OpenMetadata (metadata)
    [4] Đóng dấu Approved                    -> OpenMetadata
    [5] Thử tìm lại bằng custom property     -> OpenMetadata Search API
    [6] Tải về và cân lại checksum           -> S3

Hai nơi lưu, hai việc khác nhau: **S3 giữ ruột file**, **OpenMetadata giữ tờ khai**
(tên, loại tài liệu, thuộc dự án nào, trạng thái gì).

Khác ví dụ 01–06: ví dụ này **không đi qua HTTP**, nó gọi thẳng use case trong
container. Không FastAPI, không ASGITransport — bớt một lớp để nhìn rõ phần lõi.
"""

from __future__ import annotations

import asyncio
import mimetypes
import os
import sys
from pathlib import Path

import httpx
from _common import check, heading, line

REQUIRED_ENV = ("DS_CATALOG__BASE_URL", "DS_STORAGE__ENDPOINT", "DS_STORAGE__BUCKET")


def _missing_env() -> list[str]:
    """Danh sách biến môi trường còn thiếu."""
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


def _payload_from_env() -> tuple[bytes, str, str]:
    """Nội dung upload: file thật nếu DS_EXAMPLE_FILE trỏ tới một file, nếu không thì tự sinh.

    Trả về (bytes, tên file, content type). Dùng file thật là cách duy nhất thấy được
    service xử lý đúng nội dung nhị phân và kích thước thật, thay vì vài chục byte.
    """
    raw = os.environ.get("DS_EXAMPLE_FILE")
    if raw:
        path = Path(raw).expanduser()
        if not path.is_file():
            print(f"DS_EXAMPLE_FILE does not point to a file: {path}")
            sys.exit(1)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path.read_bytes(), path.name, content_type
    return b"noi dung tren ha tang that", "srs.pdf", "application/pdf"


def _print_instructions(missing: list[str]) -> None:
    """In hướng dẫn dựng hạ tầng."""
    print("This example needs real infrastructure, these env vars are missing:")
    for name in missing:
        print(f"  - {name}")
    print("\nHow to run:")
    print("  docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d")
    print("  until curl -sf http://localhost:8586/healthcheck >/dev/null; do sleep 5; done")
    print("  aws --endpoint-url http://localhost:8333 s3 mb s3://raw-documents")
    print("  set -a && source deploy/.env && set +a")
    print("  uv run python examples/07_openmetadata_real.py")
    print("\nDetails: deploy/README.md")


async def main() -> None:
    """Chạy kịch bản trên hạ tầng thật, hoặc in hướng dẫn nếu chưa có."""
    missing = _missing_env()
    if missing:
        _print_instructions(missing)
        return

    # Phải đặt profile TRƯỚC khi import document_service: config đọc biến môi trường
    # ngay lúc import. Đó là lý do mọi import bên dưới nằm trong hàm chứ không ở đầu file.
    os.environ["DS_APP__PROFILE"] = "openmetadata"
    from document_service.adapter.outbound.openmetadata.bootstrap import OmSchemaMigration
    from document_service.adapter.outbound.openmetadata.client import OmHttpClient
    from document_service.config import SettingsProvider
    from document_service.domain.dto import SearchFilter, SearchQuery, UploadRequest
    from document_service.domain.metadata_builder import CatalogMetadataBuilder
    from document_service.domain.model import DocumentMetadata, Principal
    from document_service.domain.value import Checksum, IdempotencyKey
    from document_service.infrastructure.container import ServiceContainer
    from document_service.utils.hashing import digest_of
    from document_service.utils.singleton import SingletonMeta

    # Xoá singleton cũ để container dựng lại theo profile vừa đặt ở trên.
    SingletonMeta.clear()
    settings = SettingsProvider().reload()
    container = ServiceContainer(settings)

    # === BƯỚC 1 ======================================================================
    # Đăng ký các custom property (document_type, collection_id...) lên OpenMetadata.
    # Chưa có mấy ô này thì năm bước sau không có chỗ ghi, nên đây là bước DUY NHẤT
    # thoát hẳn chương trình khi lỗi.
    heading("1. Prepare the schema on OpenMetadata")
    # Client riêng, không lấy từ container, vì migration chạy trước khi cần cả bundle.
    # Chính client này được aclose() ở cuối hàm.
    client = OmHttpClient(settings.catalog, container.executor("catalog"))
    try:
        await OmSchemaMigration(client, settings.catalog).run_on_startup()
        line("drive service", settings.catalog.drive_service_name)
        line("required custom property", ", ".join(settings.catalog.required_properties))
        print("  [OK  ] schema migration finished")
    except Exception as error:  # hạ tầng thật có thể từ chối vì nhiều lý do
        print(f"  [FAIL] migration failed: {error}")
        print("  Check DS_CATALOG__BOT_TOKEN and the server version.")
        await client.aclose()
        sys.exit(1)

    # === BƯỚC 2 ======================================================================
    # Probe từng phụ thuộc. Chỉ đọc, không ghi gì — health check mà tạo dữ liệu thì
    # không dùng được trong môi trường thật.
    heading("2. Health of each dependency")
    report = await container.health.details(settings.health.probe_timeout_seconds)
    for item in report.results:
        line(item.name, f"{item.status} · {item.detail[:50]}")
    check("every dependency can serve", all(item.healthy for item in report.results))

    # === BƯỚC 3 ======================================================================
    # Bước nặng nhất. Hai lời gọi, nhưng create_version bên dưới chạy cả một saga:
    #
    #   kiểm idempotency  -> gặp lại key cũ thì trả luôn bản cũ, không ghi gì
    #   khoá theo document_id
    #   đọc lại tài liệu từ OpenMetadata
    #   chống trùng nội dung theo checksum -> trùng thì trả bản cũ, KHÔNG upload
    #   sinh document_version_id
    #   ghi intent xuống database   <- ghi sổ TRƯỚC khi chạm hạ tầng
    #   PUT bytes lên S3
    #   đăng ký metadata lên OpenMetadata
    #   đánh dấu intent Completed
    #
    # Thứ tự "object trước, catalog sau" là cố ý: hai thao tác này không nằm trong một
    # giao dịch. Nếu catalog lỗi, file đã an toàn trên S3 và intent chuyển RetryPending
    # để job đối soát ghi nốt metadata — không phải upload lại. Ví dụ 03 mô phỏng đúng
    # kịch bản này bằng mock.
    heading("3. Register a document and one version")
    principal = Principal(principal_id="example", groups=("document-admins",), is_admin=True)
    from document_service.application.usecase.create_version import CreateVersionCommand
    from document_service.application.usecase.register_document import RegisterDocumentCommand

    document = await container.use_cases.register_document().execute(
        RegisterDocumentCommand(
            principal=principal,
            metadata=DocumentMetadata(
                title="SRS tich hop", document_type="SRS", collection_id="PROJECT-IT"
            ),
        )
    )
    line("document_id", document.document_id)

    payload, file_name, content_type = _payload_from_env()
    line("file", file_name)
    line("size (bytes)", len(payload))
    request = UploadRequest(
        document_id=document.document_id,
        original_file_name=file_name,
        content_format=content_type,
        checksum=Checksum(algorithm="sha256", hex_digest=digest_of(payload)),
        size_bytes=len(payload),
        actor=principal.as_actor(),
        # Khoá theo document_id (ULID, mới mỗi lần chạy) chứ KHÔNG theo checksum nội
        # dung. Khoá theo checksum thì lần chạy thứ hai bị idempotency guard trả về
        # phiên bản của lần đầu — gắn vào document cũ, không phải document vừa tạo ở
        # trên — và ví dụ dừng ở `[FAIL] version created`.
        idempotency_key=IdempotencyKey(f"real-example-{document.document_id}"),
    )

    # Truyền generator chứ không truyền bytes: service đọc theo luồng nên file lớn
    # không bị nạp hết vào RAM.
    def stream_factory() -> object:
        async def iterator() -> object:
            yield payload

        return iterator()

    result = await container.use_cases.create_version().execute(
        CreateVersionCommand(request=request, principal=principal, stream_factory=stream_factory)
    )
    line("document_version_id", result.version.version_id)
    line("storage_uri", result.version.storage_uri)
    # Mỗi lần chạy tạo một document mới nên bình thường luôn là `created`. Vẫn chấp
    # nhận `duplicate` phòng trường hợp chạy lại trên cùng document đã có nội dung đó.
    check("version created", result.created or result.duplicate)

    # === BƯỚC 4 ======================================================================
    # Chuyển Draft -> Approved. Use case chạy trong khoá theo document_id và patch ba
    # thứ xuống catalog: status bản được duyệt, status bản bị Obsolete (ở đây không có
    # vì mới một phiên bản), và current_version_id của tài liệu.
    heading("4. Approve the version on the real catalog")
    from document_service.application.usecase.approve_version import TransitionStatusCommand
    from document_service.domain.value import DocumentStatus

    approval = await container.use_cases.approve_version().execute(
        TransitionStatusCommand(
            document_id=document.document_id,
            version_id=result.version.version_id,
            idempotency_key=IdempotencyKey(f"status-{result.version.version_id}"),
            target_status=DocumentStatus.APPROVED,
            principal=principal,
        )
    )
    line("status", approval.changed.status)
    # Đọc LẠI từ OpenMetadata thay vì tin vào object trong bộ nhớ: nếu lệnh patch
    # current_version_id xuống catalog trượt âm thầm, chỉ check này mới bắt được.
    reread = await container.ports.catalog.read_document(document.document_id)
    line("current_version_id", reread.current_version_id)
    check("status is Approved", approval.changed.status is DocumentStatus.APPROVED)
    check("catalog points at this version", reread.current_version_id == result.version.version_id)

    # === BƯỚC 5 ======================================================================
    # Câu hỏi mà mock không trả lời được: OpenMetadata có tìm được theo custom property
    # không, hay phải dựng thêm C9 Search Gateway.
    # Cố ý KHÔNG dùng check() ở đây — index của OpenMetadata có độ trễ, trượt lần đầu
    # chưa chắc là không làm được, nên chỉ in cảnh báo chứ không dừng ví dụ.
    heading("5. POC-19 - filtering by custom property through the real Search API")
    page = await container.ports.catalog.search(
        SearchQuery(
            filters=(
                SearchFilter(field_name="document_type", value="SRS"),
                SearchFilter(field_name="collection_id", value="PROJECT-IT"),
            )
        )
    )
    line("result count", page.total_hits)
    if any(hit.version_id == result.version.version_id for hit in page.hits):
        print("  [OK  ] Search API can filter by custom property, POC-19 met natively")
    else:
        print("  [FAIL] Search API CANNOT filter by custom property")
        print("         Most likely cause: the stack was not patched. OpenMetadata 1.12.0")
        print("         maps `extension` of file_search_index as keyword and aggregates on")
        print("         it in search settings, so no File is ever indexed. Fix both with:")
        print("             make compose-patch")
        print("         then run this example again. See deploy/patch_openmetadata.py.")

    # === BƯỚC 6 ======================================================================
    # Tờ khai trong catalog ghi đúng KHÔNG đảm bảo ruột file đúng: file có thể rỗng,
    # hỏng, hoặc bị ghi đè. Chỉ tải về cân lại mới biết chắc.
    heading("6. Download the file back from real Object Storage")
    builder = CatalogMetadataBuilder()
    line(
        "metadata is filterable",
        ", ".join(builder.filterable_subset(builder.build(document, result.version)).keys()),
    )
    url = await container.presigned_issuer().issue(result.version.storage_uri)
    line("presigned url", f"{url[:80]}...")
    check("download link issued", bool(url))

    # Tải thật qua presigned URL và đối chiếu ba thứ: status 200, số byte, và sha256 so
    # với checksum lúc upload. Đây là bằng chứng duy nhất rằng đúng nội dung nằm trên S3.
    async with httpx.AsyncClient(timeout=30.0) as downloader:
        fetched = await downloader.get(url)
    line("HTTP status", fetched.status_code)
    line("downloaded (bytes)", len(fetched.content))
    line("checksum matches", digest_of(fetched.content) == request.checksum.hex_digest)
    check("download returns 200", fetched.status_code == 200)
    check("byte count matches the upload", len(fetched.content) == len(payload))
    check(
        "checksum round-trips through S3", digest_of(fetched.content) == request.checksum.hex_digest
    )

    await client.aclose()
    print("\nExample 7 complete. Record the outcome in docs/c4-08-tra-soat-code-vs-thiet-ke.md")


if __name__ == "__main__":
    asyncio.run(main())
