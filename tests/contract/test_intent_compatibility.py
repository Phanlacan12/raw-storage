"""Kiểm chứng dữ liệu intent được ghi trước khi phân loại thao tác."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from document_service.adapter.outbound.fake.in_memory import InMemoryObjectStore
from document_service.adapter.outbound.intent.s3_manifest_store import S3ManifestIntentStore
from document_service.adapter.outbound.intent.sqlite_store import SqliteRegistryIntentStore
from document_service.adapter.outbound.sqlite_support import SqliteDatabase
from document_service.domain.errors import ConcurrencyConflictError
from document_service.domain.value import IdempotencyKey, IntentKind, RequestId, StorageUri
from document_service.infrastructure.resilience.executor import ResilientCallExecutor


def _legacy_manifest() -> dict[str, object]:
    """Dữ liệu ghi từ phiên bản chỉ hỗ trợ upload."""
    return {
        "request_id": "req-legacy",
        "idempotency_key": "idem-legacy",
        "document_id": "doc-01",
        "version_id": "ver-01",
        "expected_checksum": "sha256:" + "a" * 64,
        "state": "Received",
        "retry_count": 2,
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-02T00:00:00+00:00",
        "last_error": "interrupted",
        "payload": {"key": "value"},
    }


async def test_legacy_manifest_is_upload(executor: ResilientCallExecutor) -> None:
    """Đọc manifest cũ khi chưa có trường kind."""
    objects = InMemoryObjectStore()
    store = S3ManifestIntentStore(objects, "bucket", executor)
    raw = _legacy_manifest()
    uri = StorageUri("bucket", "intents/manifests/req-legacy.json")
    await objects.put_overwrite(uri, json.dumps(raw).encode())
    # Crash giữa viết manifest và công bố index: recovery bỏ qua bản này.
    assert await store.find_unfinished(timedelta(0)) == []
    assert await store.find_by_request_id(RequestId("req-legacy")) is None
    await objects.put_overwrite(
        StorageUri("bucket", "intents/by-key/idem-legacy.json"), b'{"request_id":"req-legacy"}'
    )
    intent = await store.find_by_request_id(RequestId("req-legacy"))
    assert intent is not None and intent.kind is IntentKind.UPLOAD
    assert intent.payload == raw["payload"]
    assert str(intent.expected_checksum) == raw["expected_checksum"]

    peer = S3ManifestIntentStore(objects, "bucket", executor)
    key = IdempotencyKey("idem-contended")
    first = replace(intent, request_id=RequestId("request-one"), idempotency_key=key)
    second = replace(first, request_id=RequestId("request-two"))
    results = await asyncio.gather(store.create(first), peer.create(second), return_exceptions=True)
    assert sum(isinstance(item, ConcurrencyConflictError) for item in results) == 1
    winner = await store.find_by_idempotency_key(key)
    assert winner is not None
    loser = second if winner.request_id == first.request_id else first
    assert await peer.find_by_request_id(loser.request_id) is None
    assert {item.request_id for item in await store.find_unfinished(timedelta(0))} == {
        intent.request_id,
        winner.request_id,
    }


async def test_legacy_sqlite_survives_restart(
    tmp_path: Path, executor: ResilientCallExecutor
) -> None:
    """Mở lại database sau migration vẫn đọc cùng khóa, trạng thái và payload."""
    path = tmp_path / "legacy.sqlite"
    raw = _legacy_manifest()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE upload_intent (request_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, "
            "document_id TEXT, version_id TEXT, expected_checksum TEXT NOT NULL, state TEXT, "
            "retry_count INTEGER, created_at TEXT, updated_at TEXT, last_error TEXT, payload TEXT)"
        )
        row = {**raw, "payload": json.dumps(raw["payload"])}
        connection.execute(
            f"INSERT INTO upload_intent VALUES ({','.join('?' for _ in row)})", tuple(row.values())
        )
    for _ in range(2):
        store = SqliteRegistryIntentStore(SqliteDatabase(str(path)), executor)
        intent = await store.find_by_idempotency_key(IdempotencyKey("idem-legacy"))
        assert intent is not None and intent.kind is IntentKind.UPLOAD
        assert intent.payload == raw["payload"] and intent.retry_count == 2
        assert str(intent.expected_checksum) == raw["expected_checksum"]
