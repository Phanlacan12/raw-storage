"""Base class của các use case (quy tắc R1, docs/c4-04b mục 2.2).

`UseCase` giữ ba hành vi dùng chung: kiểm tra quyền, ghi audit và phát sự kiện. Hai
nhánh con tách theo bản chất thao tác: `ReadUseCase` chỉ đọc, `WriteUseCase` cần
tuần tự hoá theo document_id trước khi ghi.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

from document_service.application.context import PortBundle
from document_service.application.orchestration.lock_manager import DocumentLockManager
from document_service.domain.errors import PolicyDeniedError
from document_service.domain.model import AuditEvent, DomainEvent, Principal
from document_service.domain.value import Action, DocumentId

CommandT = TypeVar("CommandT")
ResultT = TypeVar("ResultT")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class AuditTarget:
    """Đối tượng của một thao tác được audit."""

    document_id: str
    target_id: str

    @classmethod
    def of_document(cls, document_id: object) -> AuditTarget:
        """Thao tác ở mức tài liệu."""
        return cls(document_id=str(document_id), target_id=str(document_id))

    @classmethod
    def of_version(cls, document_id: object, version_id: object) -> AuditTarget:
        """Thao tác ở mức phiên bản, vẫn gắn về tài liệu."""
        return cls(document_id=str(document_id), target_id=str(version_id))


@dataclass(frozen=True, slots=True)
class AuditOutcome:
    """Kết quả một thao tác, dùng khi ghi audit."""

    result: str
    detail: str = ""

    @classmethod
    def ok(cls, detail: str = "") -> AuditOutcome:
        """Thao tác thành công."""
        return cls(result="ok", detail=detail)

    @classmethod
    def denied(cls, reason: str) -> AuditOutcome:
        """Thao tác bị từ chối quyền."""
        return cls(result="denied", detail=reason)


class UseCase(ABC, Generic[CommandT, ResultT]):
    """Base class của mọi use case."""

    def __init__(self, ports: PortBundle) -> None:
        """Nhận bundle port dùng chung."""
        self._ports = ports

    @property
    def ports(self) -> PortBundle:
        """Bundle port, cho lớp con và test truy cập."""
        return self._ports

    @abstractmethod
    async def execute(self, command: CommandT) -> ResultT:
        """Thực hiện use case."""

    async def _authorize(self, principal: Principal, action: Action, resource: str) -> None:
        """Kiểm tra quyền, phát lỗi nếu bị từ chối."""
        decision = await self._ports.policies.decide(principal, action, resource)
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason or f"không có quyền {action}")

    async def _record(
        self,
        principal: Principal,
        action: str,
        target: AuditTarget,
        outcome: AuditOutcome,
    ) -> None:
        """Ghi một bản ghi audit (bất biến I12)."""
        await self._ports.audit.record(
            AuditEvent(
                actor=principal.as_actor(),
                action=action,
                target_id=target.target_id,
                result=outcome.result,
                document_id=target.document_id,
                detail=outcome.detail,
            )
        )

    async def _publish(self, event: DomainEvent) -> None:
        """Phát một sự kiện miền cho downstream."""
        await self._ports.events.publish(event)


class ReadUseCase(UseCase[CommandT, ResultT], ABC):
    """Use case chỉ đọc: không cần khóa, nhưng luôn kiểm tra quyền xem."""

    async def _authorize_view(self, principal: Principal, resource: str) -> None:
        """Kiểm tra quyền xem metadata trên một tài nguyên."""
        await self._authorize(principal, Action.VIEW_METADATA, resource)


class WriteUseCase(UseCase[CommandT, ResultT], ABC):
    """Use case ghi: tuần tự hoá theo document_id trước khi thay đổi trạng thái."""

    def __init__(self, ports: PortBundle) -> None:
        """Dựng thêm lock manager từ port khóa."""
        super().__init__(ports)
        self._locks = DocumentLockManager(ports.locks)

    async def _authorize_write(self, principal: Principal, resource: str) -> None:
        """Kiểm tra quyền ghi trên một tài nguyên."""
        await self._authorize(principal, Action.WRITE, resource)

    async def _run_exclusive(
        self, document_id: DocumentId, operation: Callable[[], Awaitable[T]]
    ) -> T:
        """Chạy phần ghi trong khóa của tài liệu (bất biến I4, I5)."""
        return await self._locks.run_exclusive(document_id, operation)
