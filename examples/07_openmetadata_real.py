"""Ví dụ 7 — Chạy với OpenMetadata và Object Storage **thật**.

Chạy:

    docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
    set -a && source deploy/.env && set +a
    uv run python examples/07_openmetadata_real.py

Thiếu biến môi trường thì ví dụ **không** chạy giả lập: nó in hướng dẫn rồi dừng, để
không ai nhầm kết quả của profile fake với kết quả trên hạ tầng thật.

Ví dụ này là nơi kiểm chứng hai điều mà mock không trả lời được:
POC-19 (lọc custom property qua Search API thật) và việc migration schema chạy được.
"""

from __future__ import annotations

import asyncio
import os
import sys

from _common import check, heading, line

REQUIRED_ENV = ("DS_CATALOG__BASE_URL", "DS_STORAGE__ENDPOINT", "DS_STORAGE__BUCKET")


def _missing_env() -> list[str]:
    """Danh sách biến môi trường còn thiếu."""
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]


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

    os.environ["DS_APP__PROFILE"] = "openmetadata"
    from document_service.adapter.outbound.openmetadata.bootstrap import OmSchemaMigration
    from document_service.adapter.outbound.openmetadata.client import OmHttpClient
    from document_service.application.metadata_builder import CatalogMetadataBuilder
    from document_service.config import SettingsProvider
    from document_service.domain.dto import SearchFilter, SearchQuery, UploadRequest
    from document_service.domain.model import DocumentMetadata, Principal
    from document_service.domain.value import Checksum, IdempotencyKey
    from document_service.infrastructure.container import ServiceContainer
    from document_service.utils.hashing import digest_of
    from document_service.utils.singleton import SingletonMeta

    SingletonMeta.clear()
    settings = SettingsProvider().reload()
    container = ServiceContainer(settings)

    heading("1. Prepare the schema on OpenMetadata")
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

    heading("2. Health of each dependency")
    report = await container.health.details(settings.health.probe_timeout_seconds)
    for item in report.results:
        line(item.name, f"{item.status} · {item.detail[:50]}")
    check("every dependency can serve", all(item.healthy for item in report.results))

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

    payload = b"noi dung tren ha tang that"
    request = UploadRequest(
        document_id=document.document_id,
        original_file_name="srs.pdf",
        content_format="application/pdf",
        checksum=Checksum(algorithm="sha256", hex_digest=digest_of(payload)),
        size_bytes=len(payload),
        actor=principal.as_actor(),
        idempotency_key=IdempotencyKey(f"real-example-{digest_of(payload)[:16]}"),
    )

    def stream_factory() -> object:
        async def iterator() -> object:
            yield payload

        return iterator()

    result = await container.use_cases.create_version().execute(
        CreateVersionCommand(request=request, principal=principal, stream_factory=stream_factory)
    )
    line("document_version_id", result.version.version_id)
    line("storage_uri", result.version.storage_uri)
    check("version created", result.created or result.duplicate)

    heading("4. POC-19 - filtering by custom property through the real Search API")
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
        print("         Record 'Not met' for POC-19 and budget for enabling C9 Search Gateway.")
        print("         Note: the index may still lag, retry in a few seconds before concluding.")

    heading("5. Download the file from real Object Storage")
    builder = CatalogMetadataBuilder()
    line(
        "metadata is filterable",
        ", ".join(builder.filterable_subset(builder.build(document, result.version)).keys()),
    )
    url = await container.presigned_issuer().issue(result.version.storage_uri)
    line("presigned url", f"{url[:80]}...")
    check("download link issued", bool(url))

    await client.aclose()
    print("\nExample 7 complete. Record the outcome in docs/c4-08-tra-soat-code-vs-thiet-ke.md")


if __name__ == "__main__":
    asyncio.run(main())
