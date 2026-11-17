"""IdempotencyGuard: bảo đảm retry của client không tạo phiên bản trùng (bất biến I13).

Theo sequence ở mục 6 của docs/c4-04b-code-structure.md: trước khi làm bất cứ việc
gì, tra intent theo idempotency key; nếu lượt trước đã Completed thì trả lại kết quả
cũ thay vì xử lý lại.
"""

from __future__ import annotations

from dataclasses import dataclass

from document_service.domain.errors import ConcurrencyConflictError
from document_service.domain.model import UploadIntent
from document_service.domain.port import IntentStorePort
from document_service.domain.value import IdempotencyKey, IntentState


@dataclass(frozen=True, slots=True)
class ReplayDecision:
    """Kết quả tra khóa chống lặp."""

    intent: UploadIntent | None
    is_replay: bool

    @property
    def can_proceed(self) -> bool:
        """Được phép xử lý mới hay không."""
        return not self.is_replay


class IdempotencyGuard:
    """Tra và chặn các lượt gọi lặp theo `Idempotency-Key`."""

    def __init__(self, intents: IntentStorePort) -> None:
        """Nhận intent store làm nơi lưu trạng thái bền vững."""
        self._intents = intents

    async def inspect(self, key: IdempotencyKey) -> ReplayDecision:
        """Xem khóa đã được dùng chưa và lượt trước kết thúc thế nào."""
        existing = await self._intents.find_by_idempotency_key(key)
        if existing is None:
            return ReplayDecision(intent=None, is_replay=False)
        if existing.state is IntentState.COMPLETED:
            return ReplayDecision(intent=existing, is_replay=True)
        if existing.state is IntentState.FAILED:
            return ReplayDecision(intent=existing, is_replay=False)
        raise ConcurrencyConflictError(
            f"idempotency_key {key} đang được xử lý ở trạng thái {existing.state}"
        )
