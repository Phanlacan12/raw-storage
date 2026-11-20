"""Deadline và timeout, theo mục 11.3 của docs/c4-04b-code-structure.md.

Deadline được tạo ở lớp inbound theo timeout của API công khai và lan truyền xuống
mọi lời gọi ra ngoài qua một `ContextVar` (B18, c4-09 mục 5.4). Không lớp nào được
tự đặt thời gian chờ dài hơn phần còn lại.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

from document_service.domain.errors import DependencyUnavailableError
from document_service.utils.clock import Clock, SystemClock


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Ba mức timeout của một phụ thuộc."""

    connect_seconds: float
    read_seconds: float
    total_seconds: float


class Deadline:
    """Hạn chót của một lượt xử lý, dùng chung cho mọi lời gọi bên trong."""

    def __init__(self, budget_seconds: float, clock: Clock | None = None) -> None:
        """Khởi tạo hạn chót cách hiện tại một khoảng cho trước."""
        self._clock = clock or SystemClock()
        self._started_at = self._clock.now()
        self._budget_seconds = budget_seconds

    @property
    def budget_seconds(self) -> float:
        """Tổng thời gian được cấp."""
        return self._budget_seconds

    def elapsed_seconds(self) -> float:
        """Thời gian đã dùng."""
        return (self._clock.now() - self._started_at).total_seconds()

    def remaining(self) -> float:
        """Thời gian còn lại, không âm."""
        return max(0.0, self._budget_seconds - self.elapsed_seconds())

    def expired(self) -> bool:
        """Đã hết hạn hay chưa."""
        return self.remaining() <= 0.0

    def assert_not_expired(self, dependency: str) -> None:
        """Báo lỗi phụ thuộc không khả dụng nếu đã hết hạn."""
        if self.expired():
            raise DependencyUnavailableError(
                dependency, f"deadline exceeded after {self.elapsed_seconds():.3f}s"
            )

    def slice_for(self, requested_seconds: float) -> float:
        """Thời gian chờ cho một lời gọi, không vượt phần còn lại của deadline."""
        return max(0.0, min(requested_seconds, self.remaining()))


_CURRENT_DEADLINE: ContextVar[Deadline | None] = ContextVar(
    "current_request_deadline", default=None
)


def set_request_deadline(budget_seconds: float) -> Token[Deadline | None]:
    """Đặt deadline cho request hiện tại, trả token để reset về sau."""
    return _CURRENT_DEADLINE.set(Deadline(budget_seconds))


def reset_request_deadline(token: Token[Deadline | None]) -> None:
    """Reset deadline về giá trị trước khi set."""
    _CURRENT_DEADLINE.reset(token)


def get_current_deadline() -> Deadline | None:
    """Deadline của request đang xử lý, None khi ngoài request."""
    return _CURRENT_DEADLINE.get()
