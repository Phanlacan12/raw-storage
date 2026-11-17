"""ResilientCallExecutor: một executor cho mỗi phụ thuộc.

Theo mục 11.1 và 11.5 của docs/c4-04b-code-structure.md. Ba ràng buộc được thực thi
ở đây: deadline lan truyền, retry budget giới hạn tỷ lệ retry, và lỗi không retry
được thì trả ngay cho người gọi thay vì chờ hết số lần thử.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, TypeVar

from document_service.config import DependencyResiliencePolicy
from document_service.domain.errors import DependencyUnavailableError
from document_service.infrastructure.resilience.breaker import Bulkhead, CircuitBreaker
from document_service.infrastructure.resilience.deadline import Deadline, TimeoutPolicy
from document_service.infrastructure.resilience.retry import (
    BackoffStrategy,
    ClassifiedError,
    ErrorClass,
    FullJitterBackoff,
    RetryBudget,
    RetryPolicy,
)
from document_service.utils.logging_setup import get_logger
from document_service.utils.singleton import SingletonMeta

T = TypeVar("T")
_LOGGER = get_logger(__name__)


class ResilientCallExecutor:
    """Gói một lời gọi ra ngoài trong timeout, retry, breaker và bulkhead."""

    def __init__(self, name: str, policy: DependencyResiliencePolicy) -> None:
        """Dựng executor cho một phụ thuộc theo tham số cấu hình của nó."""
        self._name = name
        self._timeouts = TimeoutPolicy(
            connect_seconds=policy.connect_timeout_seconds,
            read_seconds=policy.read_timeout_seconds,
            total_seconds=policy.total_timeout_seconds,
        )
        self._retry = RetryPolicy(
            max_attempts=policy.max_attempts,
            base_delay_seconds=policy.base_delay_seconds,
            max_delay_seconds=policy.max_delay_seconds,
        )
        self._backoff: BackoffStrategy = FullJitterBackoff(
            policy.base_delay_seconds, policy.max_delay_seconds
        )
        self._budget = RetryBudget(policy.max_retry_ratio)
        self._breaker = CircuitBreaker(
            name=name,
            failure_ratio_threshold=policy.failure_ratio_threshold,
            window_size=policy.rolling_window_size,
            open_duration_seconds=policy.open_duration_seconds,
        )
        self._bulkhead = Bulkhead(policy.max_concurrent_calls, policy.queue_capacity)

    @property
    def name(self) -> str:
        """Tên phụ thuộc."""
        return self._name

    @property
    def breaker(self) -> CircuitBreaker:
        """Breaker của phụ thuộc, health indicator đọc trạng thái từ đây."""
        return self._breaker

    @property
    def budget(self) -> RetryBudget:
        """Retry budget, dùng cho metric."""
        return self._budget

    @property
    def timeouts(self) -> TimeoutPolicy:
        """Bộ timeout đang áp dụng."""
        return self._timeouts

    def new_deadline(self) -> Deadline:
        """Deadline mặc định theo total timeout của phụ thuộc."""
        return Deadline(self._timeouts.total_seconds)

    async def call(
        self,
        operation: Callable[[], Awaitable[T]],
        deadline: Deadline | None = None,
    ) -> T:
        """Thực hiện lời gọi, có retry trong hạn deadline."""
        effective_deadline = deadline or self.new_deadline()
        if not self._breaker.allow_request():
            raise DependencyUnavailableError(
                self._name, f"circuit breaker của {self._name} đang mở"
            )
        self._budget.register_call()
        async with self._bulkhead:
            return await self._attempt_loop(operation, effective_deadline)

    async def _attempt_loop(self, operation: Callable[[], Awaitable[T]], deadline: Deadline) -> T:
        """Vòng thử lại cho tới khi thành công, hết lượt hoặc hết deadline."""
        last_error: ClassifiedError | None = None
        for attempt in range(1, self._retry.max_attempts + 1):
            deadline.assert_not_expired(self._name)
            try:
                return await self._single_call(operation, deadline)
            except ClassifiedError as error:
                last_error = error
                self._record_outcome(error)
                if not self._retry.is_retryable(error):
                    raise
                if attempt == self._retry.max_attempts:
                    break
                if not await self._wait_before_retry(attempt, error, deadline):
                    break
        raise self._exhausted(last_error)

    async def _single_call(self, operation: Callable[[], Awaitable[T]], deadline: Deadline) -> T:
        """Một lần gọi, có timeout không vượt phần còn lại của deadline."""
        timeout = deadline.slice_for(self._timeouts.read_seconds)
        try:
            result = await asyncio.wait_for(operation(), timeout=timeout or None)
        except asyncio.TimeoutError as error:
            raise ClassifiedError(
                ErrorClass.RETRYABLE_TRANSIENT, f"{self._name} timeout sau {timeout:.3f}s"
            ) from error
        self._breaker.on_success()
        return result

    async def _wait_before_retry(
        self, attempt: int, error: ClassifiedError, deadline: Deadline
    ) -> bool:
        """Chờ backoff rồi cho biết có nên thử lại nữa không."""
        if not self._budget.try_acquire():
            _LOGGER.warning(
                "retry bị budget từ chối", extra={"dependency": self._name, "attempt": attempt}
            )
            return False
        delay = self._retry.delay_for(attempt, error, self._backoff)
        if delay >= deadline.remaining():
            return False
        await asyncio.sleep(delay)
        return not deadline.expired()

    def _record_outcome(self, error: ClassifiedError) -> None:
        """Chỉ tính lỗi của phụ thuộc vào breaker, không tính lỗi phía client."""
        client_fault = error.error_class in (
            ErrorClass.NON_RETRYABLE_CLIENT,
            ErrorClass.NON_RETRYABLE_CONFLICT,
        )
        if client_fault:
            self._breaker.on_success()
        else:
            self._breaker.on_failure()

    def _exhausted(self, last_error: ClassifiedError | None) -> DependencyUnavailableError:
        """Lỗi trả về khi đã hết lượt thử hoặc hết deadline."""
        detail = str(last_error) if last_error is not None else "không rõ nguyên nhân"
        retry_after = self._timeouts.total_seconds
        if last_error is not None and last_error.retry_after_seconds is not None:
            retry_after = last_error.retry_after_seconds
        _LOGGER.warning(
            "phụ thuộc không khả dụng sau khi retry",
            extra={"dependency": self._name, "detail": detail},
        )
        return DependencyUnavailableError(self._name, detail, retry_after)


class ExecutorRegistry(metaclass=SingletonMeta):
    """Giữ đúng một executor cho mỗi phụ thuộc trong cả tiến trình."""

    def __init__(self) -> None:
        """Khởi tạo registry rỗng."""
        self._executors: dict[str, ResilientCallExecutor] = {}

    def register(self, name: str, policy: DependencyResiliencePolicy) -> ResilientCallExecutor:
        """Tạo executor cho phụ thuộc nếu chưa có và trả về nó."""
        if name not in self._executors:
            self._executors[name] = ResilientCallExecutor(name, policy)
        return self._executors[name]

    def get(self, name: str) -> ResilientCallExecutor:
        """Lấy executor đã đăng ký."""
        if name not in self._executors:
            raise KeyError(f"chưa đăng ký executor cho phụ thuộc {name}")
        return self._executors[name]

    def all_executors(self) -> dict[str, ResilientCallExecutor]:
        """Toàn bộ executor, dùng cho health check và metric."""
        return dict(self._executors)

    def reset(self) -> None:
        """Xoá toàn bộ executor, dùng trong test."""
        self._executors.clear()
