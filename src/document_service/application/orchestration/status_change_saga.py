"""Phục hồi chuyển trạng thái bằng kết quả đã quyết định trong khóa tài liệu."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from document_service.application.context import PortBundle
from document_service.application.orchestration.snapshot import VersionSnapshot
from document_service.domain.metadata_builder import CatalogMetadataBuilder
from document_service.domain.model import (
    AuditEvent,
    DocumentVersion,
    DomainEvent,
    ProcessingIntent,
    TransitionResult,
)
from document_service.domain.value import Actor, DocumentStatus, IntentState


@dataclass(frozen=True, slots=True)
class StatusChangePlan:
    """Trạng thái sau chuyển đổi, gồm phiên bản hiện hành và người thực hiện."""

    result: TransitionResult
    current_version_id: str
    actor: str


class StatusChangeSnapshot:
    """Lưu đầy đủ kết quả để replay giữ nguyên trạng thái, người và thời điểm."""

    def _encode(self, version: DocumentVersion) -> str:
        fields = VersionSnapshot().to_payload(version)
        fields.update(CatalogMetadataBuilder().lifecycle_fields(version))
        fields["created_at"] = version.created_at.isoformat()
        return json.dumps(fields)

    def _decode(self, value: str) -> DocumentVersion:
        fields = json.loads(value)
        version = VersionSnapshot().from_payload(fields)
        version.created_at = datetime.fromisoformat(fields["created_at"])
        version.approved_by = fields["approved_by"] or None
        version.obsoleted_by = fields["obsoleted_by"] or None
        if fields["approved_at"]:
            version.approved_at = datetime.fromisoformat(fields["approved_at"])
        if fields["obsoleted_at"]:
            version.obsoleted_at = datetime.fromisoformat(fields["obsoleted_at"])
        return version

    def to_payload(self, plan: StatusChangePlan) -> dict[str, str]:
        """Serialize các phiên bản đã được domain áp dụng chuyển trạng thái."""
        result = plan.result
        return {
            "changed": self._encode(result.changed),
            "changed_from": str(result.changed_from),
            "obsoleted": self._encode(result.obsoleted) if result.obsoleted else "",
            "obsoleted_from": str(result.obsoleted_from) if result.obsoleted_from else "",
            "current_version_id": plan.current_version_id,
            "actor": plan.actor,
        }

    def from_payload(self, payload: dict[str, str]) -> StatusChangePlan:
        """Khôi phục đúng kết quả của lệnh gốc kể cả sau lượt duyệt mới."""
        result = TransitionResult(
            self._decode(payload["changed"]),
            DocumentStatus(payload["changed_from"]),
            self._decode(payload["obsoleted"]) if payload["obsoleted"] else None,
            DocumentStatus(payload["obsoleted_from"]) if payload["obsoleted_from"] else None,
        )
        return StatusChangePlan(result, payload["current_version_id"], payload["actor"])


class StatusChangeSaga:
    """Ghi lại kế hoạch đã lưu khi bên gọi đang giữ khóa theo document_id."""

    def __init__(self, ports: PortBundle, builder: CatalogMetadataBuilder) -> None:
        """Nhận các port dùng chung giữa lượt ghi và job phục hồi."""
        self._ports = ports
        self._builder = builder

    async def resume(self, intent: ProcessingIntent) -> None:
        """PATCH cùng một bộ giá trị nên có thể tiếp tục sau lỗi ở bất cứ bước nào."""
        plan = StatusChangeSnapshot().from_payload(intent.payload)
        for version in (plan.result.changed, plan.result.obsoleted):
            if version is not None:
                await self._ports.catalog.patch_controlled_fields(
                    intent.document_id, version.version_id, self._builder.lifecycle_fields(version)
                )
        await self._ports.catalog.patch_document_fields(
            intent.document_id, {"current_version_id": plan.current_version_id}
        )
        await self._notify(intent, plan, plan.result.changed, plan.result.changed_from)
        if plan.result.obsoleted is not None and plan.result.obsoleted_from is not None:
            await self._notify(intent, plan, plan.result.obsoleted, plan.result.obsoleted_from)
        await self._ports.intents.advance(intent.request_id, IntentState.COMPLETED)

    async def _notify(
        self,
        intent: ProcessingIntent,
        plan: StatusChangePlan,
        version: DocumentVersion,
        previous: DocumentStatus,
    ) -> None:
        """Cùng một intent chỉ tạo một audit và một sự kiện cho mỗi phiên bản."""
        delivery_id = f"{intent.request_id}/{version.version_id}"
        await self._ports.events.publish(
            DomainEvent(
                event_type=f"version.{str(version.status).lower()}",
                document_id=intent.document_id,
                version_id=version.version_id,
                occurred_at=intent.created_at,
                payload={"actor": plan.actor},
                delivery_id=delivery_id,
            )
        )
        await self._ports.audit.record(
            AuditEvent(
                actor=Actor(plan.actor),
                action="version.status_changed",
                result="ok",
                document_id=str(intent.document_id),
                target_id=str(version.version_id),
                occurred_at=intent.created_at,
                detail=f"{previous} -> {version.status}",
                delivery_id=delivery_id,
            )
        )
