"""Chống ghi lặp cho lệnh đăng ký tài liệu, khai báo quan hệ và cập nhật quyền."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from document_service.domain.errors import ConcurrencyConflictError
from document_service.domain.model import ProcessingIntent
from document_service.domain.port import IntentStorePort
from document_service.domain.value import (
    DocumentId,
    DocumentVersionId,
    IdempotencyKey,
    IntentKind,
    IntentState,
    RequestId,
)
from document_service.utils.hashing import digest_of
from document_service.utils.ids import UlidGenerator
from document_service.utils.jsonx import JsonCodec


@dataclass(frozen=True, slots=True)
class CommandReceipt:
    """Định danh đích ban đầu và trạng thái xử lý của lệnh."""

    document_id: DocumentId
    replayed: bool


@asynccontextmanager
async def command_receipt(
    intents: IntentStorePort,
    operation: str,
    arguments: dict[str, Any],
    key: IdempotencyKey | None,
    target: DocumentId | DocumentVersionId,
) -> AsyncIterator[CommandReceipt]:
    """Nhận khóa toàn cục sau kiểm quyền, lưu định danh ban đầu để phát lại."""
    document_id = DocumentId(str(target))
    if key is None:
        yield CommandReceipt(document_id, False)
        return
    payload = {"operation": operation, "fingerprint": digest_of(JsonCodec().dumpb(arguments))}
    existing = await intents.find_by_idempotency_key(key)
    if existing is not None:
        if (
            existing.kind is not IntentKind.COMMAND
            or existing.state is not IntentState.COMPLETED
            or existing.payload != payload
        ):
            raise ConcurrencyConflictError(f"idempotency key {key} already in use")
        yield CommandReceipt(existing.document_id, True)
        return
    intent = ProcessingIntent(
        request_id=RequestId(UlidGenerator().new_id("REQ")),
        idempotency_key=key,
        document_id=document_id,
        version_id=target if isinstance(target, DocumentVersionId) else None,
        expected_checksum=None,
        kind=IntentKind.COMMAND,
        payload=payload,
    )
    await intents.create(intent)
    try:
        yield CommandReceipt(document_id, False)
    except Exception as error:
        intent.advance(IntentState.FAILED)
        intent.last_error = str(error)
        await intents.save(intent)
        raise
    await intents.advance(intent.request_id, IntentState.COMPLETED)
