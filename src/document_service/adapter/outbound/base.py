"""Base class của mọi adapter gọi ra ngoài tiến trình.

Theo quy tắc R1 và mục 2.2, 10.2 của docs/c4-04b-code-structure.md. Adapter kế thừa
lớp này để có hai thứ dùng chung:

1. `_call()` — mọi lời gọi ra ngoài đi qua `ResilientCallExecutor` của đúng phụ thuộc,
   nên timeout, retry, breaker và bulkhead không bị lặp lại ở từng adapter.
2. `check_health()` — **health check là trách nhiệm của chính adapter**: nó biết phép
   thử rẻ và chỉ-đọc cho phụ thuộc của mình, và nó giữ circuit breaker nên đọc được
   trạng thái breaker trước khi quyết định có gọi thật hay không.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, TypeVar

from document_service.infrastructure.health import (
    DependencyKind,
    HealthProbeMixin,
    HealthResult,
)
from document_service.infrastructure.resilience.breaker import BreakerState
from document_service.infrastructure.resilience.deadline import Deadline
from document_service.infrastructure.resilience.executor import ResilientCallExecutor
from document_service.utils.logging_setup import get_logger

T = TypeVar("T")


class OutboundAdapter(HealthProbeMixin, ABC):
    """Phần chung của adapter hướng ra ngoài, kèm health check của phụ thuộc."""

    def __init__(
        self,
        executor: ResilientCallExecutor,
        kind: DependencyKind = DependencyKind.OPTIONAL,
        cache_ttl_seconds: float = 5.0,
    ) -> None:
        """Nhận executor riêng của phụ thuộc, nhóm phụ thuộc và TTL cache health."""
        super().__init__(cache_ttl_seconds)
        self._executor = executor
        self._kind = kind
        self._logger = get_logger(type(self).__module__)

    @property
    def dependency_name(self) -> str:
        """Tên phụ thuộc, dùng trong log, metric và health check."""
        return self._executor.name

    @property
    def dependency_kind(self) -> DependencyKind:
        """Nhóm chức năng mà phụ thuộc này phục vụ."""
        return self._kind

    @property
    def executor(self) -> ResilientCallExecutor:
        """Executor của phụ thuộc, nơi giữ breaker và retry budget."""
        return self._executor

    @abstractmethod
    async def _probe_dependency(self) -> HealthResult:
        """Phép thử health của phụ thuộc: rẻ, chỉ đọc, không tạo entity hay object."""

    async def check_health(self) -> HealthResult:
        """Đọc breaker trước, chỉ gọi phụ thuộc khi breaker không mở."""
        state = self._executor.breaker.state
        if state is BreakerState.OPEN:
            return self.health_down(f"circuit breaker của {self.dependency_name} đang mở")
        result = await super().check_health()
        if state is BreakerState.HALF_OPEN and result.healthy:
            return self.health_degraded("breaker đang nửa mở, phụ thuộc vừa phục hồi")
        return result

    async def _call(
        self, operation: Callable[[], Awaitable[T]], deadline: Deadline | None = None
    ) -> T:
        """Thực hiện một lời gọi ra ngoài trong khuôn khổ resilience."""
        return await self._executor.call(operation, deadline)
