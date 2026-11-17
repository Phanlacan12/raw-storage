"""Fixture dùng chung.

Quy tắc R2: mỗi singleton phải reset được giữa các test, nếu không trạng thái của
circuit breaker, retry budget và registry health sẽ rò sang nhau và kết quả test mất
giá trị.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

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
from document_service.config import Settings, SettingsProvider
from document_service.domain.model import Principal
from document_service.domain.policy import (
    DedupPolicy,
    LifecyclePolicy,
    RelationshipPolicy,
    VersionPolicy,
)
from document_service.utils.ids import SequentialIdGenerator
from document_service.utils.logging_setup import LoggingConfigurator
from document_service.utils.singleton import SingletonMeta

TEST_BUCKET = "test-bucket"


@pytest.fixture(autouse=True)
def reset_singletons() -> Iterator[None]:
    """Xoá toàn bộ singleton trước và sau mỗi test."""
    SingletonMeta.clear()
    yield
    SingletonMeta.clear()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bỏ biến môi trường DS_* để test không phụ thuộc máy chạy."""
    for name in list(os.environ):
        if name.startswith("DS_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DS_APP__PROFILE", "fake")
    monkeypatch.setenv("DS_STORAGE__BUCKET", TEST_BUCKET)


@pytest.fixture
def settings(clean_env: None) -> Settings:
    """Cấu hình đọc lại từ configs/ và biến môi trường của test."""
    del clean_env
    return SettingsProvider().reload()


@pytest.fixture
def ports() -> PortBundle:
    """Bundle port in-memory."""
    catalog = InMemoryCatalog()
    return PortBundle(
        catalog=catalog,
        relationships=InMemoryRelationshipStore(),
        objects=InMemoryObjectStore(),
        intents=InMemoryIntentStore(),
        policies=AllowAllPolicyDecision(),
        events=InMemoryEventPublisher(),
        audit=InMemoryAuditLog(),
        locks=InMemoryDocumentLock(),
    )


@pytest.fixture
def policies() -> PolicySet:
    """Tập policy với bộ sinh ID đoán được."""
    dedup = DedupPolicy()
    return PolicySet(
        version=VersionPolicy(TEST_BUCKET, SequentialIdGenerator(), dedup),
        lifecycle=LifecyclePolicy(),
        relationship=RelationshipPolicy(),
        dedup=dedup,
    )


@pytest.fixture
def principal() -> Principal:
    """Chủ thể quản trị dùng trong phần lớn test."""
    return Principal(principal_id="tester", groups=("document-admins",), is_admin=True)


@pytest.fixture
def quiet_logging() -> Iterator[None]:
    """Tắt cấu hình log dùng chung để output test không bị nhiễu."""
    LoggingConfigurator().reset()
    yield
    LoggingConfigurator().reset()


@pytest.fixture
async def app_client() -> AsyncIterator[Any]:
    """Client HTTP gọi vào ứng dụng FastAPI qua ASGI, có chạy lifespan."""
    import httpx

    from document_service.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver", timeout=10.0
        ) as client:
            yield client
