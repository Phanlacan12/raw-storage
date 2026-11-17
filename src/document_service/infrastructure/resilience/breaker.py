"""Circuit breaker và bulkhead cho từng phụ thuộc.

Theo mục 11.4 của docs/c4-04b-code-structure.md. Trạng thái breaker là **đầu vào
của health check**: indicator đọc trạng thái này thay vì gọi thêm một lời gọi mới
tới phụ thuộc đang quá tải.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from enum import StrEnum

from document_service.utils.clock import Clock, SystemClock


class BreakerState(StrEnum):
    """Ba trạng thái của circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Ngắt lời gọi tới phụ thuộc khi tỷ lệ lỗi vượt ngưỡng."""

    def __init__(
        self,
        name: str,
        failure_ratio_threshold: float = 0.5,
        window_size: int = 20,
        open_duration_seconds: float = 10.0,
    ) -> None:
        """Nhận tên phụ thuộc, ngưỡng lỗi, kích thước cửa sổ trượt và thời gian mở."""
        self._name = name
        self._threshold = failure_ratio_threshold
        self._window: deque[bool] = deque(maxlen=window_size)
        self._min_samples = max(4, window_size // 4)
        self._open_duration = open_duration_seconds
        self._state = BreakerState.CLOSED
        self._opened_at: float | None = None
        self._clock: Clock = SystemClock()
        self._lock = threading.Lock()
        self._open_count = 0

    @property
    def name(self) -> str:
        """Tên phụ thuộc mà breaker này bảo vệ."""
        return self._name

    @property
    def state(self) -> BreakerState:
        """Trạng thái hiện tại, đã tính cả việc hết thời gian mở."""
        with self._lock:
            self._refresh_state()
            return self._state

    @property
    def open_count(self) -> int:
        """Số lần breaker đã mở, dùng cho metric và cảnh báo."""
        return self._open_count

    def allow_request(self) -> bool:
        """Cho biết có được gọi phụ thuộc ở thời điểm này hay không."""
        with self._lock:
            self._refresh_state()
            return self._state is not BreakerState.OPEN

    def on_success(self) -> None:
        """Ghi nhận một lời gọi thành công."""
        with self._lock:
            self._window.append(True)
            if self._state is BreakerState.HALF_OPEN:
                self._state = BreakerState.CLOSED
                self._window.clear()
                self._opened_at = None

    def on_failure(self) -> None:
        """Ghi nhận một lời gọi thất bại do phụ thuộc."""
        with self._lock:
            self._window.append(False)
            if self._state is BreakerState.HALF_OPEN:
                self._trip()
                return
            if len(self._window) >= self._min_samples:
                failures = sum(1 for ok in self._window if not ok)
                if failures / len(self._window) >= self._threshold:
                    self._trip()

    def reset(self) -> None:
        """Đưa breaker về CLOSED, dùng trong test và sau can thiệp thủ công."""
        with self._lock:
            self._state = BreakerState.CLOSED
            self._window.clear()
            self._opened_at = None

    def _trip(self) -> None:
        """Chuyển sang OPEN và ghi lại thời điểm mở."""
        self._state = BreakerState.OPEN
        self._opened_at = self._clock.now().timestamp()
        self._open_count += 1
        self._window.clear()

    def _refresh_state(self) -> None:
        """Chuyển OPEN sang HALF_OPEN khi đã hết thời gian mở."""
        if self._state is BreakerState.OPEN and self._opened_at is not None:
            elapsed = self._clock.now().timestamp() - self._opened_at
            if elapsed >= self._open_duration:
                self._state = BreakerState.HALF_OPEN


class Bulkhead:
    """Giới hạn số lời gọi đồng thời và độ sâu hàng đợi cho một phụ thuộc."""

    def __init__(self, max_concurrent_calls: int = 16, queue_capacity: int = 32) -> None:
        """Nhận số lời gọi đồng thời tối đa và dung lượng hàng đợi."""
        self._semaphore = asyncio.Semaphore(max_concurrent_calls)
        self._max_waiting = queue_capacity
        self._waiting = 0
        self._rejected = 0

    @property
    def rejected_count(self) -> int:
        """Số lời gọi bị từ chối nhanh vì hàng đợi đầy."""
        return self._rejected

    @property
    def waiting(self) -> int:
        """Số lời gọi đang chờ slot."""
        return self._waiting

    def has_capacity(self) -> bool:
        """Còn chỗ trong hàng đợi hay không."""
        return self._waiting < self._max_waiting

    async def __aenter__(self) -> Bulkhead:
        """Giữ một slot, từ chối nhanh nếu hàng đợi đã đầy."""
        if not self.has_capacity():
            self._rejected += 1
            raise asyncio.QueueFull("bulkhead đã đầy, từ chối nhanh")
        self._waiting += 1
        try:
            await self._semaphore.acquire()
        finally:
            self._waiting -= 1
        return self

    async def __aexit__(self, *_: object) -> None:
        """Nhả slot."""
        self._semaphore.release()
