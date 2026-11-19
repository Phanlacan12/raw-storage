"""Fixture cho contract test: dựng từng hiện thực của một port.

Mục đích theo mục 14 của docs/c4-04b-code-structure.md: **một bộ test cho mỗi port**,
chạy trên mọi hiện thực. Nhờ vậy quyết định Q2 (intent store) và Q4 (relationship
store) được chốt bằng kết quả test, không bằng lập luận.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import respx

from document_service.adapter.outbound.fake.in_memory import (
    InMemoryDocumentLock,
    InMemoryIntentStore,
    InMemoryObjectStore,
    InMemoryRelationshipStore,
)
from document_service.adapter.outbound.intent.s3_manifest_store import S3ManifestIntentStore
from document_service.adapter.outbound.intent.sqlite_store import SqliteRegistryIntentStore
from document_service.adapter.outbound.lock.redis_lock import RedisDocumentLock
from document_service.adapter.outbound.openmetadata import endpoints
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.adapter.outbound.openmetadata.lineage import OmLineageRelationshipStore
from document_service.adapter.outbound.relationship.sqlite_registry import (
    SqliteRelationshipRegistry,
)
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.config import (
    CatalogSettings,
    DependencyResiliencePolicy,
    LockKind,
    LockSettings,
)
from document_service.domain.port import DocumentLockPort, IntentStorePort, RelationshipStorePort
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from tests.contract.fake_openmetadata import FakeOpenMetadataServer


@pytest.fixture
def database(tmp_path: Path) -> SqliteDatabase:
    """Database sqlite riêng cho mỗi test."""
    return SqliteDatabase(str(tmp_path / "contract.sqlite"))


@pytest.fixture
def executor() -> ResilientCallExecutor:
    """Executor với tham số nhanh, dùng cho adapter trong test."""
    policy = DependencyResiliencePolicy(
        read_timeout_seconds=2.0, total_timeout_seconds=3.0, max_attempts=2
    )
    return ResilientCallExecutor("contract", policy)


@pytest.fixture(params=["in_memory", "sqlite", "s3_manifest"])
def intent_store(
    request: pytest.FixtureRequest, database: SqliteDatabase, executor: ResilientCallExecutor
) -> IntentStorePort:
    """Ba hiện thực của intent store: fake, registry sqlite và manifest trên S3.

    Hai hiện thực sau là đúng hai biến thể của quyết định **Q2**, nên bộ test này là
    nơi so sánh chúng trên cùng một hợp đồng.
    """
    if request.param == "in_memory":
        return InMemoryIntentStore()
    if request.param == "sqlite":
        return SqliteRegistryIntentStore(database, executor)
    return S3ManifestIntentStore(InMemoryObjectStore(), "test-bucket", executor)


@pytest.fixture(params=["in_memory", "sqlite", "om_lineage"])
async def relationship_store(
    request: pytest.FixtureRequest, database: SqliteDatabase, executor: ResilientCallExecutor
) -> AsyncIterator[RelationshipStorePort]:
    """Ba hiện thực của relationship store, ứng với quyết định Q4."""
    if request.param == "in_memory":
        yield InMemoryRelationshipStore()
    elif request.param == "sqlite":
        yield SqliteRelationshipRegistry(database, executor)
    else:
        server = FakeOpenMetadataServer("http://om.contract.test")
        client = OmHttpClient(CatalogSettings(base_url=server.base_url), executor)
        try:
            with respx.mock(assert_all_called=False) as router:
                server.install(router)
                for version in ("VER-SRS-0020", "VER-SRS-0021", "VER-URD-0012", "VER-SAD-0011"):
                    await client.put(endpoints.FILES, {"name": version, "directory": "raw.docs"})
                yield OmLineageRelationshipStore(client, executor)
        finally:
            await client.aclose()


# tests/conftest.py::clean_env (autouse) xoá mọi `DS_*`, nên PHẢI đọc REDIS_URL ở
# mức module lúc import; cùng mẫu đã dùng ở tests/integration/test_real_infrastructure.py.
REDIS_URL = os.environ.get("DS_LOCK__REDIS_URL", "")


@pytest.fixture(params=["in_memory", "redis"])
async def document_lock(
    request: pytest.FixtureRequest,
) -> AsyncIterator[DocumentLockPort]:
    """Hai hiện thực của document lock, ứng với quyết định Q12 (C13).

    `in_memory` chạy luôn, `redis` yêu cầu `DS_LOCK__REDIS_URL` trỏ tới Redis
    thật; không có thì skip. `acquire_timeout_seconds=0.1` để case 5 kiểm được
    fail-fast trên cả hai hiện thực.
    """
    if request.param == "in_memory":
        settings = LockSettings(kind=LockKind.IN_MEMORY, acquire_timeout_seconds=0.1)
        yield InMemoryDocumentLock(settings)
        return
    pytest.importorskip("redis")
    if not REDIS_URL:
        pytest.skip("thiếu DS_LOCK__REDIS_URL, xem deploy/README.md")
    import redis.asyncio as redis_async

    client = redis_async.from_url(REDIS_URL, socket_timeout=0.5)
    try:
        await client.ping()
    except Exception as error:  # noqa: BLE001
        await client.aclose()
        pytest.skip(f"redis unreachable: {error}")
    settings = LockSettings(
        kind=LockKind.REDIS,
        redis_url=REDIS_URL,
        key_prefix=f"ds:test:{uuid4().hex}",
        acquire_timeout_seconds=0.1,
        lease_seconds=2.0,
        renew_interval_seconds=0.7,
    )
    policy = DependencyResiliencePolicy(
        connect_timeout_seconds=0.3,
        read_timeout_seconds=1.0,
        total_timeout_seconds=1.0,
        max_attempts=1,
    )
    executor = ResilientCallExecutor("document_lock", policy)
    lock = RedisDocumentLock(settings, executor, client=client)
    yield lock
    await lock.aclose()
