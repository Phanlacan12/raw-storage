"""Phân loại lỗi, backoff có jitter và retry budget.

Theo mục 11.2 và 11.3 của docs/c4-04b-code-structure.md. Nguyên tắc: khi phụ thuộc
quá tải thì số lần retry phải **giảm**, nên budget là một token bucket chặn trên tỷ
lệ retry so với tổng số lời gọi.
"""

from __future__ import annotations

import random
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class ErrorClass(StrEnum):
    """Năm nhóm lỗi quyết định có retry hay không."""

    RETRYABLE_TRANSIENT = "retryable_transient"
    RETRYABLE_THROTTLED = "retryable_throttled"
    AUTH_REFRESHABLE = "auth_refreshable"
    NON_RETRYABLE_CLIENT = "non_retryable_client"
    NON_RETRYABLE_CONFLICT = "non_retryable_conflict"

    @property
    def retryable(self) -> bool:
        """Nhóm lỗi có được retry trong cùng request hay không."""
        return self in (
            ErrorClass.RETRYABLE_TRANSIENT,
            ErrorClass.RETRYABLE_THROTTLED,
            ErrorClass.AUTH_REFRESHABLE,
        )


class ClassifiedError(Exception):
    """Lỗi từ một phụ thuộc, đã được adapter phân loại."""

    def __init__(
        self,
        error_class: ErrorClass,
        message: str = "",
        retry_after_seconds: float | None = None,
    ) -> None:
        """Ghi lại nhóm lỗi và gợi ý thời gian chờ từ phía server."""
        super().__init__(message or error_class.value)
        self.error_class = error_class
        self.retry_after_seconds = retry_after_seconds


class BackoffStrategy(ABC):
    """Base class của chiến lược chờ giữa hai lần thử.

    Base lo phần dùng chung: chặn trên `max_delay` và rải ngẫu nhiên; lớp con chỉ
    quyết định thời gian chờ cơ sở theo số lần đã thử.
    """

    def __init__(
        self, base_delay: float, max_delay: float, rng: random.Random | None = None
    ) -> None:
        """Nhận thời gian chờ cơ sở, mức chặn trên và nguồn ngẫu nhiên."""
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._rng = rng or random.Random()

    @abstractmethod
    def next_delay(self, attempt: int) -> float:
        """Thời gian chờ trước lần thử thứ `attempt` (tính từ 1)."""

    def with_full_jitter(self, delay: float) -> float:
        """Rải đều trong khoảng [0, delay] để nhiều client không cùng thử lại."""
        return self._rng.uniform(0.0, max(0.0, delay))

    def jittered_delay(self, attempt: int) -> float:
        """Thời gian chờ đã rải ngẫu nhiên, không vượt max_delay."""
        return self.with_full_jitter(min(self._max_delay, self.next_delay(attempt)))


class FullJitterBackoff(BackoffStrategy):
    """Chờ theo hàm mũ với full jitter, mặc định cho mọi phụ thuộc."""

    def next_delay(self, attempt: int) -> float:
        """Thời gian chờ tăng theo lũy thừa 2, chặn trên bởi max_delay."""
        exponential = self._base_delay * (2 ** max(0, attempt - 1))
        return min(self._max_delay, exponential)


class FixedBackoff(BackoffStrategy):
    """Chờ cố định, dùng trong test để kết quả đoán được."""

    def next_delay(self, attempt: int) -> float:
        """Luôn trả về thời gian chờ cơ sở."""
        return self._base_delay

    def with_full_jitter(self, delay: float) -> float:
        """Không rải ngẫu nhiên, giữ nguyên thời gian chờ."""
        return delay


class RetryBudget:
    """Giới hạn tỷ lệ retry trên tổng số lời gọi của một phụ thuộc."""

    def __init__(self, max_retry_ratio: float = 0.1, min_tokens: float = 5.0) -> None:
        """Nhận tỷ lệ retry tối đa và lượng token tối thiểu luôn được cấp."""
        self._ratio = max_retry_ratio
        self._min_tokens = min_tokens
        self._tokens = min_tokens
        self._rejected = 0
        self._lock = threading.Lock()

    @property
    def tokens(self) -> float:
        """Số token còn lại."""
        return self._tokens

    @property
    def rejected_count(self) -> int:
        """Số lần retry bị budget từ chối, dùng cho metric."""
        return self._rejected

    def register_call(self) -> None:
        """Ghi nhận một lời gọi thành công hoặc thất bại ở lần thử đầu."""
        with self._lock:
            self._tokens = min(self._tokens + self._ratio, self._min_tokens * 4)

    def try_acquire(self) -> bool:
        """Xin một token để retry, trả False khi hết budget."""
        with self._lock:
            if self._tokens < 1.0:
                self._rejected += 1
                return False
            self._tokens -= 1.0
            return True

    def reset(self) -> None:
        """Đưa budget về trạng thái ban đầu, dùng trong test."""
        with self._lock:
            self._tokens = self._min_tokens
            self._rejected = 0


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Chính sách retry của một phụ thuộc."""

    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float

    def is_retryable(self, error: ClassifiedError) -> bool:
        """Lỗi có thuộc nhóm được retry hay không."""
        return error.error_class.retryable

    def delay_for(self, attempt: int, error: ClassifiedError, backoff: BackoffStrategy) -> float:
        """Thời gian chờ, tôn trọng Retry-After nếu server có gửi."""
        if error.retry_after_seconds is not None:
            return max(error.retry_after_seconds, backoff.next_delay(attempt))
        return backoff.jittered_delay(attempt)
