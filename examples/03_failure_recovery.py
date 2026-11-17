"""Ví dụ 3 — Lỗi một phía trong luồng ghi và phục hồi (POC-08, POC-18, POC-21).

Chạy: uv run python examples/03_failure_recovery.py

Mô phỏng đúng tình huống mục 3.5 báo cáo: object đã ghi lên Object Storage nhưng đăng
ký catalog thất bại. Ví dụ cho thấy intent chuyển `RetryPending`, job đối soát hoàn
tất lại được, và **không** sinh phiên bản thứ hai.
"""

from __future__ import annotations

import asyncio
from typing import Any

from _common import check, heading, line, reset_container, use_fake_profile


async def main() -> None:
    """Chạy kịch bản lỗi rồi phục hồi."""
    use_fake_profile()
    reset_container()

    from document_service.adapter.outbound.fake.in_memory import (
        AllowAllPolicyDecision,
        InMemoryAuditLog,
        InMemoryCatalog,
        InMemoryDocumentLock,
        InMemoryEventPublisher,
        InMemoryIntentStore,
        InMemoryObjectStore,
        InMemoryRelationshipStore,
    )
    from document_service.application.context import PolicySet, PortBundle
    from document_service.application.metadata_builder import CatalogMetadataBuilder
    from document_service.application.orchestration.upload_saga import UploadSaga
    from document_service.application.usecase.create_version import (
        CreateVersionCommand,
        CreateVersionUseCase,
    )
    from document_service.application.usecase.register_document import (
        RegisterDocumentCommand,
        RegisterDocumentUseCase,
    )
    from document_service.config import get_settings
    from document_service.domain.dto import UploadRequest
    from document_service.domain.errors import DependencyUnavailableError
    from document_service.domain.model import DocumentMetadata, Principal
    from document_service.domain.policy import (
        DedupPolicy,
        LifecyclePolicy,
        RelationshipPolicy,
        VersionPolicy,
    )
    from document_service.domain.value import Checksum, IdempotencyKey, IntentState, StorageUri
    from document_service.utils.hashing import digest_of
    from document_service.worker.reconcile import IntentRecoveryJob

    class FlakyCatalog(InMemoryCatalog):
        """Catalog lỗi ở lần đăng ký phiên bản đầu tiên."""

        def __init__(self) -> None:
            """Bắt đầu với một lần lỗi đang chờ."""
            super().__init__()
            self.fail_next = True

        async def register_version(self, version: Any, metadata: dict[str, Any]) -> Any:
            """Phát lỗi phụ thuộc một lần rồi hoạt động bình thường."""
            if self.fail_next:
                self.fail_next = False
                raise DependencyUnavailableError("catalog", "metadata registration failed")
            return await super().register_version(version, metadata)

    settings = get_settings()
    settings.intent.stale_after_seconds = -1.0

    catalog = FlakyCatalog()
    objects = InMemoryObjectStore()
    intents = InMemoryIntentStore()
    dedup = DedupPolicy()
    ports = PortBundle(
        catalog=catalog,
        relationships=InMemoryRelationshipStore(),
        objects=objects,
        intents=intents,
        policies=AllowAllPolicyDecision(),
        events=InMemoryEventPublisher(),
        audit=InMemoryAuditLog(),
        locks=InMemoryDocumentLock(),
    )
    policies = PolicySet(
        version=VersionPolicy(settings.storage.bucket, dedup=dedup),
        lifecycle=LifecyclePolicy(),
        relationship=RelationshipPolicy(),
        dedup=dedup,
    )
    builder = CatalogMetadataBuilder()
    principal = Principal(principal_id="example", groups=("document-admins",), is_admin=True)

    heading("1. Register a document")
    document = await RegisterDocumentUseCase(ports, builder).execute(
        RegisterDocumentCommand(
            principal=principal,
            metadata=DocumentMetadata(title="SRS", document_type="SRS"),
        )
    )
    line("document_id", document.document_id)

    heading("2. Upload while the catalog is failing")
    payload = b"noi dung can luu"
    request = UploadRequest(
        document_id=document.document_id,
        original_file_name="srs.pdf",
        content_format="application/pdf",
        checksum=Checksum(algorithm="sha256", hex_digest=digest_of(payload)),
        size_bytes=len(payload),
        actor=principal.as_actor(),
        idempotency_key=IdempotencyKey("recovery-example-0001"),
    )

    def stream_factory() -> Any:
        async def iterator() -> Any:
            yield payload

        return iterator()

    create_version = CreateVersionUseCase(ports, policies, builder)
    try:
        await create_version.execute(
            CreateVersionCommand(
                request=request, principal=principal, stream_factory=stream_factory
            )
        )
        raise AssertionError("it should have failed at catalog registration")
    except DependencyUnavailableError as error:
        line("error returned to the client", f"503 {error}")

    intent = await intents.find_by_idempotency_key(request.idempotency_key)
    assert intent is not None
    line("intent state", intent.state)
    line("attempts", intent.retry_count)
    check("intent is RetryPending", intent.state is IntentState.RETRY_PENDING)

    heading("3. State after the failure")
    stored_object = await objects.head(StorageUri.parse(intent.payload["storage_uri"]))
    line("object written (bytes)", stored_object.size_bytes)
    line("versions in the catalog", len(await catalog.list_versions(document.document_id)))
    check("object is on storage", stored_object.size_bytes == len(payload))
    check(
        "catalog has no version yet",
        len(await catalog.list_versions(document.document_id)) == 0,
    )

    heading("4. The reconciliation job recovers it")
    saga = UploadSaga(objects, catalog, intents)
    report = await IntentRecoveryJob(intents, saga, catalog, settings).run_once()
    line("recovered", report.recovered)
    line("failed", report.failed)
    recovered = await intents.find_by_request_id(intent.request_id)
    assert recovered is not None
    line("intent state", recovered.state)
    versions = await catalog.list_versions(document.document_id)
    line("versions in the catalog", len(versions))
    check("intent is Completed", recovered.state is IntentState.COMPLETED)
    check("exactly one version, no duplicate", len(versions) == 1)
    check("document_version_id unchanged", versions[0].version_id == intent.version_id)

    heading("5. Re-run the job with nothing left to do")
    again = await IntentRecoveryJob(intents, saga, catalog, settings).run_once()
    line("recovered", again.recovered)
    check("no pending intent left", again.recovered == 0 and again.failed == 0)

    print("\nExample 3 complete.")


if __name__ == "__main__":
    asyncio.run(main())
