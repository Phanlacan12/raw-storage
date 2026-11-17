"""MetricsRecorder: bộ chỉ số bắt buộc ở mục 11.7 của docs/c4-04b-code-structure.md.

Giữ chỉ số trong bộ nhớ theo tiến trình, đủ để vận hành đọc qua endpoint health và để
test khẳng định hành vi. Khi triển khai thật, thay bằng Prometheus client mà không đổi
chỗ gọi: các lớp khác chỉ dùng `MetricsRecorder`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from document_service.infrastructure.resilience.executor import ExecutorRegistry
from document_service.utils.singleton import SingletonMeta


@dataclass(slots=True)
class DependencyMetrics:
    """Chỉ số của một phụ thuộc."""

    calls: int = 0
    failures: int = 0
    retries: int = 0
    retry_rejected: int = 0
    latencies: list[float] = field(default_factory=list)

    def percentile(self, fraction: float) -> float:
        """Phân vị độ trễ, 0.0 nếu chưa có số liệu."""
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return ordered[index]


class MetricsRecorder(metaclass=SingletonMeta):
    """Thu thập chỉ số phụ thuộc, chế độ phục vụ và hàng đợi đối soát."""

    def __init__(self) -> None:
        """Khởi tạo bộ chỉ số rỗng."""
        self._dependencies: dict[str, DependencyMetrics] = {}
        self._service_mode = "FULL"
        self._intent_backlog = 0

    def record_call(self, dependency: str, latency_seconds: float, failed: bool = False) -> None:
        """Ghi một lời gọi phụ thuộc kèm độ trễ."""
        metrics = self._dependencies.setdefault(dependency, DependencyMetrics())
        metrics.calls += 1
        metrics.latencies.append(latency_seconds)
        if failed:
            metrics.failures += 1

    def record_retry(self, dependency: str, rejected: bool = False) -> None:
        """Ghi một lần retry, hoặc một lần retry bị budget từ chối."""
        metrics = self._dependencies.setdefault(dependency, DependencyMetrics())
        if rejected:
            metrics.retry_rejected += 1
        else:
            metrics.retries += 1

    def set_service_mode(self, mode: str) -> None:
        """Ghi chế độ phục vụ hiện tại."""
        self._service_mode = mode

    def set_intent_backlog(self, count: int) -> None:
        """Ghi số intent chưa hoàn tất."""
        self._intent_backlog = count

    def snapshot(self) -> dict[str, object]:
        """Toàn bộ chỉ số hiện tại, gồm trạng thái breaker đọc từ executor."""
        breakers = {
            name: str(executor.breaker.state)
            for name, executor in ExecutorRegistry().all_executors().items()
        }
        budgets = {
            name: executor.budget.rejected_count
            for name, executor in ExecutorRegistry().all_executors().items()
        }
        return {
            "service_mode": self._service_mode,
            "intent_retry_pending_count": self._intent_backlog,
            "circuit_breaker_state": breakers,
            "retry_budget_rejected_total": budgets,
            "dependency_call_duration": {
                name: {
                    "calls": metrics.calls,
                    "failures": metrics.failures,
                    "retries": metrics.retries,
                    "p50": round(metrics.percentile(0.5), 4),
                    "p95": round(metrics.percentile(0.95), 4),
                }
                for name, metrics in self._dependencies.items()
            },
        }

    def reset(self) -> None:
        """Xoá chỉ số, dùng trong test."""
        self._dependencies.clear()
        self._service_mode = "FULL"
        self._intent_backlog = 0
