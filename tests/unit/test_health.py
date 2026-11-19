"""Test health check (docs/c4-04b mục 10).

Khẳng định quan trọng nhất: `/livez` **không** đổi khi phụ thuộc ngoài DOWN, còn
`/readyz` chuyển `ServiceMode` đúng; và health check không tạo entity hay object.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from document_service.adapter.inbound.health.indicators import (
    AdapterHealthIndicator,
    IdpHealthIndicator,
    ReconcileBacklogIndicator,
)
from document_service.adapter.inbound.health.registry import (
    DegradedModeGate,
    HealthCheckRegistry,
    ReadinessPolicy,
)
from document_service.adapter.outbound.fake.in_memory import (
    InMemoryCatalog,
    InMemoryIntentStore,
    InMemoryObjectStore,
)
from document_service.adapter.outbound.openmetadata.entity import OmEntityVersionGuard
from document_service.domain.errors import ServiceDegradedError
from document_service.domain.value import Action
from document_service.infrastructure.container import ServiceContainer
from document_service.infrastructure.health import (
    DependencyKind,
    HealthResult,
    HealthStatus,
    ServiceMode,
)


def _result(name: str, kind: DependencyKind, status: HealthStatus) -> HealthResult:
    """Dựng kết quả health mẫu."""
    return HealthResult(name=name, status=status, kind=kind)


class TestAdapterOwnedHealth:
    """Health check là trách nhiệm của adapter outbound."""

    async def test_adapter_declares_name_and_kind(self) -> None:
        """Adapter tự khai báo tên và nhóm phụ thuộc."""
        store = InMemoryObjectStore()
        result = await store.check_health()
        assert result.name == "object_store"
        assert result.kind is DependencyKind.REQUIRED_FOR_DOWNLOAD
        assert result.status is HealthStatus.UP

    async def test_adapter_down_is_reported(self) -> None:
        """Phụ thuộc sập được báo DOWN qua chính adapter."""
        store = InMemoryObjectStore()
        store.available = False
        store.invalidate_health_cache()
        result = await store.check_health()
        assert result.status is HealthStatus.DOWN

    async def test_indicator_delegates_to_adapter(self) -> None:
        """Indicator ở lớp inbound chỉ ủy quyền, không tự định nghĩa phép thử."""
        catalog = InMemoryCatalog()
        indicator = AdapterHealthIndicator(catalog)
        result = await indicator.check(timeout_seconds=1.0)
        assert indicator.name == "catalog"
        assert result.status is HealthStatus.UP

    async def test_health_check_does_not_write(self) -> None:
        """Health check chỉ đọc: không tạo object nào."""
        store = InMemoryObjectStore()
        await store.check_health()
        assert await store.list_under_prefix("objects/") == []


class TestReadinessPolicy:
    """Suy ra chế độ phục vụ từ nhóm phụ thuộc."""

    def test_full_when_all_up(self) -> None:
        """Mọi phụ thuộc UP thì chế độ đầy đủ."""
        results = (
            _result("catalog", DependencyKind.REQUIRED_FOR_READ, HealthStatus.UP),
            _result("object_store", DependencyKind.REQUIRED_FOR_DOWNLOAD, HealthStatus.UP),
            _result("intent_store", DependencyKind.REQUIRED_FOR_WRITE, HealthStatus.UP),
        )
        assert ReadinessPolicy().evaluate(results) is ServiceMode.FULL

    def test_read_only_when_write_dependency_down(self) -> None:
        """Intent store DOWN thì từ chối ghi, vẫn đọc và tải được."""
        results = (
            _result("catalog", DependencyKind.REQUIRED_FOR_READ, HealthStatus.UP),
            _result("object_store", DependencyKind.REQUIRED_FOR_DOWNLOAD, HealthStatus.UP),
            _result("intent_store", DependencyKind.REQUIRED_FOR_WRITE, HealthStatus.DOWN),
        )
        assert ReadinessPolicy().evaluate(results) is ServiceMode.READ_ONLY

    def test_download_only_when_catalog_down(self) -> None:
        """Catalog DOWN nhưng storage còn thì chỉ cấp file."""
        results = (
            _result("catalog", DependencyKind.REQUIRED_FOR_READ, HealthStatus.DOWN),
            _result("object_store", DependencyKind.REQUIRED_FOR_DOWNLOAD, HealthStatus.UP),
            _result("intent_store", DependencyKind.REQUIRED_FOR_WRITE, HealthStatus.DOWN),
        )
        assert ReadinessPolicy().evaluate(results) is ServiceMode.NOT_READY
        assert (
            ReadinessPolicy().evaluate(results, cached_download=True) is ServiceMode.DOWNLOAD_ONLY
        )

    def test_not_ready_when_storage_down(self) -> None:
        """Storage DOWN thì không phục vụ được gì."""
        results = (
            _result("object_store", DependencyKind.REQUIRED_FOR_DOWNLOAD, HealthStatus.DOWN),
        )
        assert ReadinessPolicy().evaluate(results) is ServiceMode.NOT_READY

    def test_degraded_does_not_block(self) -> None:
        """DEGRADED không chặn: chỉ DOWN mới làm mất chức năng."""
        results = (
            _result("catalog", DependencyKind.REQUIRED_FOR_READ, HealthStatus.DEGRADED),
            _result("object_store", DependencyKind.REQUIRED_FOR_DOWNLOAD, HealthStatus.UP),
            _result("intent_store", DependencyKind.REQUIRED_FOR_WRITE, HealthStatus.UP),
        )
        assert ReadinessPolicy().evaluate(results) is ServiceMode.FULL


class TestRegistryAndGate:
    """Registry tổng hợp và cổng chặn theo chế độ."""

    async def test_liveness_does_not_touch_dependencies(self) -> None:
        """`/livez` không gọi phụ thuộc nào, nên không đổi khi chúng DOWN."""
        registry = HealthCheckRegistry()
        store = InMemoryObjectStore()
        store.available = False
        registry.register(AdapterHealthIndicator(store))
        assert registry.liveness() == {"status": "alive"}

    async def test_not_ready_before_startup(self) -> None:
        """Chưa chạy migration thì chưa sẵn sàng nhận việc."""
        registry = HealthCheckRegistry()
        registry.register(AdapterHealthIndicator(InMemoryObjectStore()))
        report = await registry.readiness(1.0)
        assert report.mode is ServiceMode.NOT_READY

    async def test_ready_after_startup(self) -> None:
        """Sau migration và với phụ thuộc UP thì chế độ đầy đủ."""
        registry = HealthCheckRegistry()
        registry.register(AdapterHealthIndicator(InMemoryObjectStore()))
        registry.register(AdapterHealthIndicator(InMemoryIntentStore()))
        registry.register(AdapterHealthIndicator(InMemoryCatalog()))
        registry.mark_startup_done()
        report = await registry.readiness(1.0)
        assert report.mode is ServiceMode.FULL
        assert report.ready is True

    async def test_backlog_indicator_reports_degraded(self) -> None:
        """Hàng đợi đối soát vượt ngưỡng thì báo DEGRADED."""
        from document_service.domain.model import ProcessingIntent
        from document_service.domain.value import (
            Checksum,
            DocumentId,
            DocumentVersionId,
            IdempotencyKey,
            RequestId,
        )

        intents = InMemoryIntentStore()
        for index in range(3):
            await intents.create(
                ProcessingIntent(
                    request_id=RequestId(f"REQ-{index}"),
                    idempotency_key=IdempotencyKey(f"idem-key-{index}"),
                    document_id=DocumentId("DOC-1"),
                    version_id=DocumentVersionId(f"VER-{index}"),
                    expected_checksum=Checksum.parse("sha256:" + "d" * 64),
                )
            )
        indicator = ReconcileBacklogIndicator(intents, stale_after_seconds=-1, backlog_threshold=2)
        result = await indicator.check(1.0)
        assert result.status is HealthStatus.DEGRADED
        assert "backlog=3" in result.detail

    async def test_idp_indicator_reads_live_verifier(self) -> None:
        """Thay đổi ở verifier được phản ánh trên probe kế tiếp."""
        verifier = AsyncMock(side_effect=[True, False])
        indicator = IdpHealthIndicator(verifier)
        assert (await indicator.check()).status is HealthStatus.UP
        assert (await indicator.check()).status is HealthStatus.DOWN

    def test_gate_blocks_write_in_read_only(self) -> None:
        """Chế độ READ_ONLY chặn hành động ghi, vẫn cho tải."""
        gate = DegradedModeGate()
        gate.update(ServiceMode.READ_ONLY)
        with pytest.raises(ServiceDegradedError):
            gate.assert_allowed(Action.WRITE)
        gate.assert_allowed(Action.DOWNLOAD)

    def test_gate_blocks_everything_when_not_ready(self) -> None:
        """Chế độ NOT_READY chặn mọi hành động."""
        gate = DegradedModeGate()
        gate.update(ServiceMode.NOT_READY)
        for action in (Action.WRITE, Action.DOWNLOAD, Action.SEARCH):
            with pytest.raises(ServiceDegradedError):
                gate.assert_allowed(action)


async def test_health_probe_names_groups_and_storage_failure() -> None:
    """Tám port có danh tính riêng, S3 down chỉ ngừng cấp file và ghi."""
    container = ServiceContainer()
    container.health.mark_startup_done()
    assert isinstance(container.ports.objects, InMemoryObjectStore)
    container.ports.objects.available = False
    report = await container.health.details()
    results = {r.name: r for r in report.results}
    assert len(results) == len(report.results)
    assert {"audit", "outbox", "policies", "intent_store"} <= results.keys()
    assert DependencyKind.REQUIRED_FOR_WRITE in results["object_store"].kinds
    assert DependencyKind.REQUIRED_FOR_WRITE in results["catalog"].kinds
    assert report.mode is ServiceMode.READ_ONLY
    container.gate.update(report.mode, report.download_ready)
    with pytest.raises(ServiceDegradedError):
        container.gate.assert_allowed(Action.DOWNLOAD)
    container.gate.assert_allowed(Action.SEARCH)


def test_missing_write_group_cannot_elect_full_mode() -> None:
    """Một nhóm bắt buộc rỗng không bỏ phiếu UP."""
    assert ReadinessPolicy().evaluate(()) is ServiceMode.NOT_READY
    results = (
        _result("read", DependencyKind.REQUIRED_FOR_READ, HealthStatus.UP),
        _result("download", DependencyKind.REQUIRED_FOR_DOWNLOAD, HealthStatus.UP),
    )
    assert ReadinessPolicy().evaluate(results) is ServiceMode.READ_ONLY


@pytest.mark.parametrize(("observation", "changed"), [(0.9, True), (1.0, False), (1.1, True)])
def test_guard_compares_both_directions(observation: float, changed: bool) -> None:
    """Version guard dùng cho quan sát, bao gồm cả version tăng lẫn giảm."""
    assert OmEntityVersionGuard().changed_unexpectedly(1.0, {"version": observation}) is changed
