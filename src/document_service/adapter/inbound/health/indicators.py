"""Indicator ở lớp inbound (docs/c4-04b mục 10.2, 10.3).

Phần lớn phụ thuộc **tự** khai báo health qua `HealthProbe` của adapter, nên ở đây
chỉ còn `AdapterHealthIndicator` ủy quyền sang adapter, cộng hai indicator không có
adapter tương ứng: IdP và hàng đợi đối soát.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from document_service.domain.port import IntentStorePort
from document_service.infrastructure.health import (
    DependencyKind,
    HealthIndicator,
    HealthProbeMixin,
    HealthResult,
)
from document_service.utils.clock import utc_now


class AdapterHealthIndicator(HealthIndicator):
    """Ủy quyền kiểm tra cho adapter của phụ thuộc.

    Nhờ lớp này, thêm một phụ thuộc mới chỉ cần adapter hiện thực
    `_probe_dependency()`, không phải sửa lớp health hay registry.
    """

    def __init__(self, probe: HealthProbeMixin) -> None:
        """Nhận adapter đóng vai HealthProbe."""
        super().__init__(probe.dependency_name, probe.dependency_kind, probe.extra_kinds)
        self._probe_target = probe

    def invalidate_cache(self) -> None:
        """Buộc lần tra chi tiết tiếp theo lấy số liệu trực tiếp."""
        self._probe_target.invalidate_health_cache()

    async def _probe(self) -> HealthResult:
        """Gọi check_health của adapter."""
        return await self._probe_target.check_health()


class IdpHealthIndicator(HealthIndicator):
    """Kiểm tra JWKS của IdP, dùng được bản cache trong thời hạn."""

    def __init__(self, jwks_available: Callable[[], Awaitable[bool]]) -> None:
        """Nhận trạng thái JWKS do lớp security cung cấp."""
        super().__init__(
            "idp",
            DependencyKind.REQUIRED_FOR_READ,
            frozenset({DependencyKind.REQUIRED_FOR_DOWNLOAD}),
        )
        self._jwks_available = jwks_available

    async def _probe(self) -> HealthResult:
        """JWKS còn hiệu lực hay không."""
        return self._up() if await self._jwks_available() else self._down("JWKS unavailable")


class ReconcileBacklogIndicator(HealthIndicator):
    """Theo dõi hàng đợi đối soát: báo DEGRADED khi lệch trạng thái tích tụ."""

    def __init__(
        self,
        intents: IntentStorePort,
        stale_after_seconds: float = 60.0,
        backlog_threshold: int = 20,
    ) -> None:
        """Nhận intent store, ngưỡng tuổi intent và ngưỡng số lượng."""
        super().__init__("reconcile_backlog", DependencyKind.OPTIONAL)
        self._intents = intents
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._threshold = backlog_threshold

    async def _probe(self) -> HealthResult:
        """Đếm intent chưa hoàn tất và tuổi của intent cũ nhất."""
        pending = await self._intents.find_unfinished(self._stale_after)
        if not pending:
            return self._up("backlog=0")
        oldest_age = max((utc_now() - item.updated_at).total_seconds() for item in pending)
        detail = f"backlog={len(pending)} oldest_age={oldest_age:.0f}s"
        if len(pending) >= self._threshold:
            return self._degraded(detail)
        return self._up(detail)
