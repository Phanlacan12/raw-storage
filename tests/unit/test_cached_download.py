"""Đường tải file còn hoạt động khi catalog không thể phục vụ."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from document_service.adapter.outbound.policy.policy_decision import CachingPolicyDecision
from document_service.application.context import PortBundle
from document_service.application.usecase.issue_download import (
    IssueDownloadCommand,
    IssueDownloadUseCase,
)
from document_service.config import SecuritySettings
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import AccessPolicy, Document, DocumentVersion, Principal
from document_service.domain.value import (
    Action,
    Checksum,
    DocumentId,
    DocumentVersionId,
    StorageUri,
    VersionLabel,
)
from document_service.utils.clock import FixedClock


async def test_download_only_uses_current_policy_for_requested_version(ports: PortBundle) -> None:
    """Chỉ tài liệu thường, đúng người, đúng phiên bản và trong TTL được ký URL."""
    clock = FixedClock()
    policies = CachingPolicyDecision(
        ports.catalog, SecuritySettings(auth_disabled=False, policy_cache_ttl_seconds=10), clock
    )
    doc_id, version_id = DocumentId("doc-cache"), DocumentVersionId("ver-cache")
    policy = AccessPolicy(allowed_principals=("reader",))
    uri = StorageUri("cache", "objects/cached")
    version = DocumentVersion(
        version_id, doc_id, VersionLabel("1"), Checksum("sha256", "0" * 64), uri, "f", "text", 5
    )
    document = Document(doc_id, access_policy=policy, versions=[version])
    await ports.catalog.register_document(document)
    await policies.effective_policy(doc_id)
    command = IssueDownloadCommand(doc_id, version_id, Principal("reader"), cached_only=True)
    objects = AsyncMock()
    objects.presign.return_value = "signed"
    # Đường này không cần đọc lại catalog.
    use_case = IssueDownloadUseCase(
        replace(
            ports,
            policies=policies,
            catalog=AsyncMock(read_document=AsyncMock(side_effect=AssertionError)),
            objects=objects,
        )
    )
    clock.advance(4)
    assert policies.has_cached_download()
    grant = await use_case.execute(command)
    assert grant.url == "signed" and grant.expires_in_seconds == 6
    for invalid in [
        replace(command, principal=Principal("other")),
        replace(command, version_id=DocumentVersionId("other-ver")),
    ]:
        with pytest.raises(PolicyDeniedError):
            await use_case.execute(invalid)
    clock.advance(6)
    assert not policies.has_cached_download()
    with pytest.raises(PolicyDeniedError):
        await use_case.execute(command)
    document.access_policy = replace(policy, require_proxy_download=True)
    await policies.effective_policy(doc_id)
    assert not policies.has_cached_download()
    with pytest.raises(PolicyDeniedError):
        await use_case.execute(command)


async def test_download_only_http_obeys_readiness_and_expiry(
    ports: PortBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đọc readiness qua HTTP rồi cấp đúng phiên bản khi catalog đã mất."""
    import httpx

    from document_service.adapter.outbound.fake.in_memory import InMemoryCatalog
    from document_service.domain.errors import DocumentNotFoundError
    from document_service.infrastructure.container import ServiceContainer
    from document_service.main import create_app
    from document_service.utils.singleton import SingletonMeta

    SingletonMeta.clear()

    clock = FixedClock()
    policy = CachingPolicyDecision(
        ports.catalog, SecuritySettings(auth_disabled=False, policy_cache_ttl_seconds=10), clock
    )
    monkeypatch.setattr(
        ServiceContainer, "_build_fake_ports", lambda _: replace(ports, policies=policy)
    )
    document_id = DocumentId("doc-web")
    version_id = DocumentVersionId("ver-web")
    uri = StorageUri("test-bucket", "objects/v1")
    version = DocumentVersion(
        version_id,
        document_id,
        VersionLabel("v1"),
        Checksum("sha256", "0" * 64),
        uri,
        "file",
        "text",
        1,
    )
    await ports.catalog.register_document(
        Document(
            document_id,
            access_policy=AccessPolicy(allowed_principals=("dev-user",)),
            versions=[version],
        )
    )
    await ports.objects.put_overwrite(uri, b"a")
    await policy.effective_policy(document_id)
    assert isinstance(ports.catalog, InMemoryCatalog)
    ports.catalog.available = False
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert (await client.get("/readyz")).json()["mode"] == "DOWNLOAD_ONLY"
        path = "/api/v1/versions/ver-web/download?document_id=doc-web"
        assert (await client.get(path)).status_code == 200
        assert (
            await client.get(
                path, headers={"X-Principal-Id": "stranger", "X-Principal-Groups": "ordinary"}
            )
        ).status_code == 403
        assert (await client.get("/api/v1/search")).status_code == 503
        clock.advance(10)
        assert (await client.get("/readyz")).json()["mode"] == "NOT_READY"
        assert (await client.get(path)).status_code == 503

    await policy.effective_policy(document_id)
    assert policy.has_cached_download()
    monkeypatch.setattr(
        ports.catalog, "read_document", AsyncMock(side_effect=DocumentNotFoundError("gone"))
    )
    assert not (
        await policy.decide(Principal("dev-user"), Action.DOWNLOAD, str(document_id))
    ).allowed
    assert not policy.has_cached_download()
