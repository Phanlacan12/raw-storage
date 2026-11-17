"""Nguồn thời gian, tách riêng để test thay thế được mà không chạm domain."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


def utc_now() -> datetime:
    """Thời điểm hiện tại theo UTC."""
    return datetime.now(timezone.utc)


class Clock(Protocol):
    """Giao diện lấy thời gian hiện tại."""

    def now(self) -> datetime:
        """Thời điểm hiện tại."""


class SystemClock:
    """Đồng hồ thật của hệ thống."""

    def now(self) -> datetime:
        """Thời điểm hiện tại theo UTC."""
        return utc_now()


class FixedClock:
    """Đồng hồ cố định hoặc dịch chuyển được, dùng trong test."""

    def __init__(self, start: datetime | None = None) -> None:
        """Khởi tạo tại một mốc thời gian."""
        self._current = start or utc_now()

    def now(self) -> datetime:
        """Thời điểm đang được giữ."""
        return self._current

    def advance(self, seconds: float) -> datetime:
        """Dịch đồng hồ về phía trước."""
        self._current = self._current + timedelta(seconds=seconds)
        return self._current
