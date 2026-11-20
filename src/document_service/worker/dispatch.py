"""Tiến trình C10 phát outbox và chạy lịch đồng bộ nguồn đã cấu hình."""

from __future__ import annotations

import asyncio

from document_service.adapter.outbound.observability.outbox_dispatcher import (
    DispatchReport,
    OutboxDispatcher,
)
from document_service.config import AdapterProfile, get_settings
from document_service.infrastructure.container import ServiceContainer
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)


class OutboxDispatchRunner:
    """Phát các batch theo chu kỳ và đóng sender khi tiến trình dừng."""

    def __init__(self, dispatcher: OutboxDispatcher, interval_seconds: float) -> None:
        self._dispatcher = dispatcher
        self._interval = interval_seconds

    async def run_once(self) -> DispatchReport:
        """Phát tối đa batch_size sự kiện."""
        return await self._dispatcher.run_once()

    async def run_forever(self) -> None:
        """Một lượt lỗi không làm ngừng phát các batch tiếp theo."""
        try:
            if not self._dispatcher.enabled:
                _LOGGER.warning("outbox dispatch disabled")
                return
            while True:
                try:
                    await self.run_once()
                except Exception:
                    _LOGGER.exception("outbox dispatch failed")
                await asyncio.sleep(self._interval)
        finally:
            await self._dispatcher.aclose()


async def _run(container: ServiceContainer) -> None:
    dispatcher = container.outbox_dispatcher()
    scheduler = container.source_sync_scheduler()
    async with asyncio.TaskGroup() as jobs:
        if dispatcher is not None:
            runner = OutboxDispatchRunner(dispatcher, container.settings.events.interval_seconds)
            jobs.create_task(runner.run_forever())
        jobs.create_task(scheduler.run_forever())


def main() -> None:
    """Chạy worker với cùng cấu hình storage, catalog và SQLite của dịch vụ."""
    if get_settings().app.profile is AdapterProfile.FAKE:
        _LOGGER.warning("dispatch worker requires durable storage")
        return
    asyncio.run(_run(ServiceContainer()))


if __name__ == "__main__":
    main()
