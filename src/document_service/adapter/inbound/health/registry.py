"""HealthCheckRegistry, ReadinessPolicy và DegradedModeGate (docs/c4-04b mục 10.4).

`/livez` **không** chạm phụ thuộc ngoài, để một sự cố của catalog không làm
orchestrator restart hàng loạt pod. `/readyz` mới tổng hợp theo nhóm phụ thuộc.
"""

from __future__ import annotations

import asyncio

from document_service.domain.errors import ServiceDegradedError
from document_service.domain.value import Action
from document_service.infrastructure.health import (
    DependencyKind,
    HealthIndicator,
    HealthReport,
    HealthResult,
    HealthStatus,
    ServiceMode,
)
from document_service.utils.singleton import SingletonMeta


class ReadinessPolicy:
    """Suy ra chế độ phục vụ từ tập kết quả health."""

    def evaluate(self, results: tuple[HealthResult, ...]) -> ServiceMode:
        """Quy tắc ở mục 10.4: ghi cần intent store, khóa và storage.

        Nhóm phụ thuộc lấy từ `HealthResult.kind` do chính adapter khai báo, nên lớp
        này không cần biết tên cụ thể của từng phụ thuộc.
        """
        write_ready = self._all_up(results, DependencyKind.REQUIRED_FOR_WRITE)
        read_ready = self._all_up(results, DependencyKind.REQUIRED_FOR_READ)
        download_ready = self._all_up(results, DependencyKind.REQUIRED_FOR_DOWNLOAD)
        if write_ready and read_ready and download_ready:
            return ServiceMode.FULL
        if read_ready and download_ready:
            return ServiceMode.READ_ONLY
        if download_ready:
            return ServiceMode.DOWNLOAD_ONLY
        return ServiceMode.NOT_READY

    def _all_up(self, results: tuple[HealthResult, ...], kind: DependencyKind) -> bool:
        """Mọi phụ thuộc của một nhóm đều không DOWN."""
        return all(item.status is not HealthStatus.DOWN for item in results if item.kind is kind)


class HealthCheckRegistry(metaclass=SingletonMeta):
    """Giữ danh sách indicator và tổng hợp báo cáo cho các endpoint."""

    def __init__(self) -> None:
        """Khởi tạo registry rỗng, chưa chạy migration."""
        self._indicators: list[HealthIndicator] = []
        self._policy = ReadinessPolicy()
        self._startup_done = False

    def register(self, indicator: HealthIndicator) -> None:
        """Thêm một indicator."""
        self._indicators.append(indicator)

    def mark_startup_done(self) -> None:
        """Ghi nhận migration schema đã chạy xong."""
        self._startup_done = True

    def liveness(self) -> dict[str, str]:
        """Chỉ báo tiến trình còn phục vụ, không gọi phụ thuộc ngoài."""
        return {"status": "alive"}

    def startup(self) -> dict[str, object]:
        """Cho biết migration khởi động đã hoàn tất chưa."""
        return {"status": "ready" if self._startup_done else "pending"}

    async def readiness(self, timeout_seconds: float = 2.0) -> HealthReport:
        """Chạy toàn bộ indicator song song và suy ra chế độ phục vụ."""
        results = await self._collect(timeout_seconds)
        mode = self._policy.evaluate(results)
        if not self._startup_done:
            mode = ServiceMode.NOT_READY
        return HealthReport(results=results, mode=mode)

    async def details(self, timeout_seconds: float = 2.0) -> HealthReport:
        """Báo cáo chi tiết cho vận hành, chỉ dùng trong mạng nội bộ."""
        return await self.readiness(timeout_seconds)

    def reset(self) -> None:
        """Xoá indicator và cờ khởi động, dùng trong test."""
        self._indicators.clear()
        self._startup_done = False

    async def _collect(self, timeout_seconds: float) -> tuple[HealthResult, ...]:
        """Gọi song song mọi indicator."""
        if not self._indicators:
            return ()
        checks = [indicator.check(timeout_seconds) for indicator in self._indicators]
        return tuple(await asyncio.gather(*checks))


class DegradedModeGate(metaclass=SingletonMeta):
    """Nơi duy nhất chặn hành động theo chế độ phục vụ."""

    _ALLOWED: dict[ServiceMode, frozenset[Action]] = {
        ServiceMode.FULL: frozenset(Action),
        ServiceMode.READ_ONLY: frozenset({Action.VIEW_METADATA, Action.SEARCH, Action.DOWNLOAD}),
        ServiceMode.DOWNLOAD_ONLY: frozenset({Action.DOWNLOAD}),
        ServiceMode.NOT_READY: frozenset(),
    }

    def __init__(self) -> None:
        """Mặc định ở chế độ đầy đủ cho tới khi readiness cập nhật."""
        self._mode = ServiceMode.FULL

    @property
    def mode(self) -> ServiceMode:
        """Chế độ đang áp dụng."""
        return self._mode

    def update(self, mode: ServiceMode) -> None:
        """Cập nhật chế độ sau mỗi lần đánh giá readiness."""
        self._mode = mode

    def assert_allowed(self, action: Action) -> None:
        """Chặn hành động không khả dụng ở chế độ hiện tại."""
        if action not in self._ALLOWED[self._mode]:
            raise ServiceDegradedError(str(self._mode), str(action))

    def reset(self) -> None:
        """Về chế độ đầy đủ, dùng trong test."""
        self._mode = ServiceMode.FULL
