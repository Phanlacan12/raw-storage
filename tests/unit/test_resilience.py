"""Test lớp resilience (docs/c4-04b mục 11).

Khẳng định: backoff có jitter và bị chặn trên, `Retry-After` được tôn trọng, retry
budget chặn bão retry, breaker mở rồi nửa mở, deadline lan truyền, và lỗi phía client
không bị retry.
"""

from __future__ import annotations

import asyncio
import random

import pytest

from document_service.config import DependencyResiliencePolicy
from document_service.domain.errors import DependencyUnavailableError
from document_service.infrastructure.resilience.breaker import (
    BreakerState,
    Bulkhead,
    CircuitBreaker,
)
from document_service.infrastructure.resilience.deadline import Deadline
from document_service.infrastructure.resilience.executor import (
    ExecutorRegistry,
    ResilientCallExecutor,
)
from document_service.infrastructure.resilience.retry import (
    ClassifiedError,
    ErrorClass,
    FixedBackoff,
    FullJitterBackoff,
    RetryBudget,
    RetryPolicy,
)

FAST_POLICY = DependencyResiliencePolicy(
    read_timeout_seconds=0.5,
    total_timeout_seconds=1.0,
    max_attempts=3,
    base_delay_seconds=0.01,
    max_delay_seconds=0.02,
    rolling_window_size=4,
    open_duration_seconds=0.05,
)


class TestBackoff:
    """Chiến lược chờ giữa hai lần thử."""

    def test_exponential_growth_capped(self) -> None:
        """Thời gian chờ tăng theo lũy thừa 2 nhưng bị chặn bởi max_delay."""
        backoff = FullJitterBackoff(0.1, 0.5)
        assert backoff.next_delay(1) == pytest.approx(0.1)
        assert backoff.next_delay(2) == pytest.approx(0.2)
        assert backoff.next_delay(10) == pytest.approx(0.5)

    def test_full_jitter_within_bounds(self) -> None:
        """Jitter rải đều trong khoảng [0, delay]."""
        backoff = FullJitterBackoff(0.2, 1.0, random.Random(7))
        samples = [backoff.jittered_delay(3) for _ in range(50)]
        assert all(0.0 <= value <= 0.8 for value in samples)
        assert len(set(samples)) > 1

    def test_fixed_backoff_is_deterministic(self) -> None:
        """FixedBackoff dùng trong test cho kết quả đoán được."""
        backoff = FixedBackoff(0.05, 1.0)
        assert backoff.jittered_delay(1) == pytest.approx(0.05)
        assert backoff.jittered_delay(5) == pytest.approx(0.05)

    def test_retry_after_wins_over_backoff(self) -> None:
        """Server gửi Retry-After thì tôn trọng giá trị đó."""
        policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.1, max_delay_seconds=0.2)
        error = ClassifiedError(ErrorClass.RETRYABLE_THROTTLED, "429", retry_after_seconds=2.0)
        delay = policy.delay_for(1, error, FixedBackoff(0.1, 0.2))
        assert delay == pytest.approx(2.0)


class TestRetryBudget:
    """Budget giới hạn tỷ lệ retry."""

    def test_budget_blocks_retry_storm(self) -> None:
        """Hết token thì retry bị từ chối và được đếm lại."""
        budget = RetryBudget(max_retry_ratio=0.1, min_tokens=2.0)
        assert budget.try_acquire() is True
        assert budget.try_acquire() is True
        assert budget.try_acquire() is False
        assert budget.rejected_count == 1

    def test_budget_refills_on_calls(self) -> None:
        """Mỗi lời gọi nạp thêm token theo tỷ lệ cấu hình."""
        budget = RetryBudget(max_retry_ratio=0.5, min_tokens=1.0)
        budget.try_acquire()
        for _ in range(4):
            budget.register_call()
        assert budget.try_acquire() is True


class TestCircuitBreaker:
    """Trạng thái breaker theo mục 11.4."""

    def test_opens_after_failure_ratio(self) -> None:
        """Vượt ngưỡng lỗi trong cửa sổ trượt thì breaker mở."""
        breaker = CircuitBreaker("dep", failure_ratio_threshold=0.5, window_size=4)
        for _ in range(4):
            breaker.on_failure()
        assert breaker.state is BreakerState.OPEN
        assert breaker.allow_request() is False

    async def test_half_open_then_closed(self) -> None:
        """Hết thời gian mở thì chuyển nửa mở, thành công thì đóng lại."""
        breaker = CircuitBreaker(
            "dep", failure_ratio_threshold=0.5, window_size=4, open_duration_seconds=0.01
        )
        for _ in range(4):
            breaker.on_failure()
        await asyncio.sleep(0.02)
        assert breaker.state is BreakerState.HALF_OPEN
        breaker.on_success()
        assert breaker.state is BreakerState.CLOSED


class TestBulkhead:
    """Giới hạn đồng thời và từ chối nhanh."""

    async def test_limits_concurrency(self) -> None:
        """Không quá số lời gọi đồng thời cho phép."""
        bulkhead = Bulkhead(max_concurrent_calls=2, queue_capacity=10)
        active = 0
        peak = 0

        async def task() -> None:
            nonlocal active, peak
            async with bulkhead:
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(task() for _ in range(6)))
        assert peak <= 2


class TestDeadline:
    """Deadline lan truyền."""

    def test_slice_never_exceeds_remaining(self) -> None:
        """Timeout của một lời gọi không vượt phần còn lại của deadline."""
        deadline = Deadline(0.2)
        assert deadline.slice_for(5.0) <= 0.2

    async def test_expired_deadline_raises(self) -> None:
        """Hết deadline thì báo phụ thuộc không khả dụng."""
        deadline = Deadline(0.01)
        await asyncio.sleep(0.02)
        assert deadline.expired() is True
        with pytest.raises(DependencyUnavailableError):
            deadline.assert_not_expired("dep")


class TestExecutor:
    """Hành vi tổng hợp của ResilientCallExecutor."""

    async def test_retries_transient_then_succeeds(self) -> None:
        """Lỗi tạm thời được thử lại và lần sau thành công."""
        executor = ResilientCallExecutor("dep", FAST_POLICY)
        attempts = 0

        async def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ClassifiedError(ErrorClass.RETRYABLE_TRANSIENT, "503")
            return "ok"

        assert await executor.call(operation) == "ok"
        assert attempts == 2

    async def test_client_error_not_retried(self) -> None:
        """Lỗi 4xx phía client trả ngay, không retry."""
        executor = ResilientCallExecutor("dep", FAST_POLICY)
        attempts = 0

        async def operation() -> str:
            nonlocal attempts
            attempts += 1
            raise ClassifiedError(ErrorClass.NON_RETRYABLE_CLIENT, "400")

        with pytest.raises(ClassifiedError):
            await executor.call(operation)
        assert attempts == 1

    async def test_open_breaker_short_circuits(self) -> None:
        """Breaker mở thì không gọi phụ thuộc nữa."""
        executor = ResilientCallExecutor("dep", FAST_POLICY)
        for _ in range(4):
            executor.breaker.on_failure()
        called = False

        async def operation() -> str:
            nonlocal called
            called = True
            return "ok"

        with pytest.raises(DependencyUnavailableError):
            await executor.call(operation)
        assert called is False

    async def test_timeout_becomes_dependency_unavailable(self) -> None:
        """Quá timeout nhiều lần thì báo phụ thuộc không khả dụng."""
        executor = ResilientCallExecutor("dep", FAST_POLICY)

        async def slow() -> str:
            await asyncio.sleep(5)
            return "never"

        with pytest.raises(DependencyUnavailableError):
            await executor.call(slow, Deadline(0.05))

    def test_registry_is_singleton_per_dependency(self) -> None:
        """Mỗi phụ thuộc có đúng một executor."""
        registry = ExecutorRegistry()
        first = registry.register("catalog", FAST_POLICY)
        second = registry.register("catalog", FAST_POLICY)
        assert first is second
        assert registry.get("catalog") is first


class TestDeadlineContextVar:
    """X25: deadline từ ContextVar lan truyền vào mọi lời gọi `_call`."""

    async def test_executor_picks_up_context_deadline(self) -> None:
        """Khi `request_deadline` được set, executor không tự `new_deadline`."""
        from document_service.infrastructure.resilience.deadline import (
            reset_request_deadline,
            set_request_deadline,
        )

        executor = ResilientCallExecutor("dep", FAST_POLICY)

        async def slow() -> str:
            await asyncio.sleep(1)
            return "never"

        # Ngân sách rất nhỏ — nếu executor đọc được ContextVar, call phải bung
        # DependencyUnavailableError gần như tức thì.
        token = set_request_deadline(0.05)
        try:
            with pytest.raises(DependencyUnavailableError):
                await executor.call(slow)
        finally:
            reset_request_deadline(token)

    async def test_no_context_deadline_falls_back_to_executor_default(self) -> None:
        """Ngoài request, executor dùng `new_deadline()` như cũ (worker nền)."""
        from document_service.infrastructure.resilience.deadline import get_current_deadline

        assert get_current_deadline() is None
        executor = ResilientCallExecutor("dep", FAST_POLICY)

        async def quick() -> str:
            return "ok"

        assert await executor.call(quick) == "ok"
