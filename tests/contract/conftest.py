"""Fixture cho contract test: dựng từng hiện thực của một port.

Mục đích theo mục 14 của docs/c4-04b-code-structure.md: **một bộ test cho mỗi port**,
chạy trên mọi hiện thực. Nhờ vậy quyết định Q2 (intent store) và Q4 (relationship
store) được chốt bằng kết quả test, không bằng lập luận.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from document_service.adapter.outbound.intent.sqlite_store import SqliteRegistryIntentStore
from document_service.adapter.outbound.relationship.sqlite_registry import (
    SqliteRelationshipRegistry,
)
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.config import DependencyResiliencePolicy
from document_service.domain.port import IntentStorePort, RelationshipStorePort
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.adapter.outbound.fake.in_memory import (
    InMemoryIntentStore,
    InMemoryObjectStore,
    InMemoryRelationshipStore,
)
from document_service.adapter.outbound.intent.s3_manifest_store import S3ManifestIntentStore


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


@pytest.fixture(params=["in_memory", "sqlite"])
def relationship_store(
    request: pytest.FixtureRequest, database: SqliteDatabase, executor: ResilientCallExecutor
) -> RelationshipStorePort:
    """Hai hiện thực của relationship store, ứng với quyết định Q4."""
    if request.param == "in_memory":
        return InMemoryRelationshipStore()
    return SqliteRelationshipRegistry(database, executor)
