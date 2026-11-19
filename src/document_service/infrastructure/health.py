"""Hợp đồng health check dùng chung cho cả hai phía (docs/c4-04b mục 10.2).

Đặt ở `infrastructure` vì **adapter outbound hiện thực** `HealthProbe`, còn lớp
inbound chỉ tổng hợp qua `HealthIndicator`. Ba nguyên tắc: health check chỉ đọc, có
timeout riêng ngắn, và kết quả được cache theo TTL để probe không thành nguồn tải.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

from document_service.utils.clock import utc_now


class HealthStatus(StrEnum):
    """Ba mức trạng thái của một phụ thuộc."""

    UP = "UP"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"


class DependencyKind(StrEnum):
    """Phụ thuộc này cần cho nhóm chức năng nào."""

    REQUIRED_FOR_WRITE = "required_for_write"
    REQUIRED_FOR_READ = "required_for_read"
    REQUIRED_FOR_DOWNLOAD = "required_for_download"
    OPTIONAL = "optional"


class ServiceMode(StrEnum):
    """Chế độ phục vụ, suy ra từ tổng hợp health (mục 10.4)."""

    FULL = "FULL"
    READ_ONLY = "READ_ONLY"
    DOWNLOAD_ONLY = "DOWNLOAD_ONLY"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True, slots=True)
class HealthResult:
    """Kết quả kiểm tra một phụ thuộc, do chính adapter của nó tạo ra."""

    name: str
    status: HealthStatus
    kind: DependencyKind = DependencyKind.OPTIONAL
    detail: str = ""
    latency_seconds: float = 0.0
    checked_at: datetime = field(default_factory=utc_now)

    extra_kinds: frozenset[DependencyKind] = frozenset()

    @property
    def kinds(self) -> frozenset[DependencyKind]:
        """Các khả năng phục vụ cần phụ thuộc này."""
        return self.extra_kinds | {self.kind}

    @property
    def healthy(self) -> bool:
        """Phụ thuộc còn phục vụ được hay không."""
        return self.status is not HealthStatus.DOWN

    def with_latency(self, latency_seconds: float) -> HealthResult:
        """Bản sao có độ trễ đo được."""
        return replace(self, latency_seconds=latency_seconds)


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Tổng hợp kết quả của nhiều phụ thuộc."""

    results: tuple[HealthResult, ...]
    mode: ServiceMode

    @property
    def ready(self) -> bool:
        """Service có sẵn sàng nhận việc hay không."""
        return self.mode is not ServiceMode.NOT_READY

    @property
    def download_ready(self) -> bool:
        """Storage và các phụ thuộc cấp file hiện còn dùng được."""
        required = [r for r in self.results if DependencyKind.REQUIRED_FOR_DOWNLOAD in r.kinds]
        return bool(required) and all(r.healthy for r in required)

    def as_payload(self) -> dict[str, object]:
        """Payload JSON cho endpoint health."""
        return {
            "mode": str(self.mode),
            "dependencies": [
                {
                    "name": item.name,
                    "status": str(item.status),
                    "kind": str(item.kind),
                    "kinds": sorted(map(str, item.kinds)),
                    "detail": item.detail,
                    "latency_ms": round(item.latency_seconds * 1000, 2),
                    "checked_at": item.checked_at.isoformat(),
                }
                for item in self.results
            ],
        }


class HealthProbe(ABC):
    """Hợp đồng mà **mọi phụ thuộc ngoài** phải tự khai báo.

    Adapter outbound kế thừa lớp này, vì chỉ adapter biết phép thử nào là rẻ và
    chỉ-đọc cho phụ thuộc của nó, và chỉ adapter giữ circuit breaker tương ứng.
    """

    extra_kinds: frozenset[DependencyKind] = frozenset()

    @property
    @abstractmethod
    def dependency_name(self) -> str:
        """Tên phụ thuộc, dùng trong health, log và metric."""

    @property
    @abstractmethod
    def dependency_kind(self) -> DependencyKind:
        """Nhóm chức năng mà phụ thuộc này phục vụ."""

    @abstractmethod
    async def check_health(self) -> HealthResult:
        """Kiểm tra phụ thuộc, không được tạo entity hay object."""


class HealthProbeMixin(HealthProbe):
    """Phần dùng chung của mọi HealthProbe: cache TTL, đo độ trễ, bắt lỗi.

    Lớp con chỉ hiện thực `_probe_dependency()`.
    """

    def __init__(self, cache_ttl_seconds: float = 5.0) -> None:
        """Nhận TTL cache kết quả health."""
        self._health_cache_ttl = cache_ttl_seconds
        self._health_cached: HealthResult | None = None

    @abstractmethod
    async def _probe_dependency(self) -> HealthResult:
        """Phép thử cụ thể, rẻ và chỉ đọc."""

    async def check_health(self) -> HealthResult:
        """Trả kết quả còn trong TTL, hoặc thăm dò lại và đo độ trễ."""
        cached = self._health_cached
        if cached is not None and self._health_fresh(cached):
            return cached
        started = utc_now()
        try:
            result = await self._probe_dependency()
        except Exception as error:  # phụ thuộc ngoài có thể phát bất kỳ lỗi nào
            result = self.health_down(str(error))
        latency = (utc_now() - started).total_seconds()
        self._health_cached = result.with_latency(latency)
        return self._health_cached

    def set_health_cache_ttl(self, seconds: float) -> None:
        """Áp TTL vận hành cho adapter và bỏ bản cache cấu hình trước."""
        self._health_cache_ttl = seconds
        self.invalidate_health_cache()

    def invalidate_health_cache(self) -> None:
        """Bỏ cache, dùng trong test và sau khi cấu hình đổi."""
        self._health_cached = None

    def health_up(self, detail: str = "") -> HealthResult:
        """Kết quả UP của phụ thuộc này."""
        return self._health_result(HealthStatus.UP, detail)

    def health_degraded(self, detail: str) -> HealthResult:
        """Kết quả DEGRADED của phụ thuộc này."""
        return self._health_result(HealthStatus.DEGRADED, detail)

    def health_down(self, detail: str) -> HealthResult:
        """Kết quả DOWN của phụ thuộc này."""
        return self._health_result(HealthStatus.DOWN, detail)

    def _health_result(self, status: HealthStatus, detail: str) -> HealthResult:
        """Dựng HealthResult với tên và nhóm của phụ thuộc này."""
        return HealthResult(
            name=self.dependency_name,
            status=status,
            kind=self.dependency_kind,
            extra_kinds=self.extra_kinds,
            detail=detail,
        )

    def _health_fresh(self, result: HealthResult) -> bool:
        """Kết quả cache còn hiệu lực hay không."""
        age = (utc_now() - result.checked_at).total_seconds()
        return age < self._health_cache_ttl


class HealthIndicator(ABC):
    """Base class của indicator ở lớp inbound: áp timeout và chuẩn hoá kết quả."""

    def __init__(
        self, name: str, kind: DependencyKind, extra_kinds: frozenset[DependencyKind] = frozenset()
    ) -> None:
        """Nhận tên và nhóm phụ thuộc."""
        self._extra_kinds = extra_kinds
        self._name = name
        self._kind = kind

    @property
    def name(self) -> str:
        """Tên phụ thuộc."""
        return self._name

    @property
    def kind(self) -> DependencyKind:
        """Nhóm phụ thuộc."""
        return self._kind

    @abstractmethod
    async def _probe(self) -> HealthResult:
        """Lấy kết quả health, thường là ủy quyền cho adapter."""

    async def check(self, timeout_seconds: float = 2.0) -> HealthResult:
        """Chạy phép kiểm tra với timeout ngắn, lỗi hoặc quá hạn là DOWN."""
        started = utc_now()
        try:
            result = await asyncio.wait_for(self._probe(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            result = self._down(f"timeout sau {timeout_seconds:.2f}s")
        except Exception as error:  # phụ thuộc ngoài có thể phát bất kỳ lỗi nào
            result = self._down(str(error))
        latency = (utc_now() - started).total_seconds()
        return replace(result, latency_seconds=latency, extra_kinds=self._extra_kinds)

    def _up(self, detail: str = "") -> HealthResult:
        """Kết quả UP."""
        return HealthResult(name=self._name, status=HealthStatus.UP, kind=self._kind, detail=detail)

    def _degraded(self, detail: str) -> HealthResult:
        """Kết quả DEGRADED."""
        return HealthResult(
            name=self._name, status=HealthStatus.DEGRADED, kind=self._kind, detail=detail
        )

    def _down(self, detail: str) -> HealthResult:
        """Kết quả DOWN."""
        return HealthResult(
            name=self._name, status=HealthStatus.DOWN, kind=self._kind, detail=detail
        )
