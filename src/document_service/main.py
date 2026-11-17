"""Điểm vào của Document Service: app factory và CLI.

Khởi động theo mục 10.1: chạy migration schema (chỉ với profile OpenMetadata), rồi mới
đánh dấu `startupz` là ready. Nếu migration thất bại, service **không** nhận việc —
vì custom property chưa đăng ký sẽ làm việc lọc metadata âm thầm sai (POC-19).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from document_service.adapter.inbound.http import health_routes, routes
from document_service.adapter.inbound.http.errors import install_error_handlers
from document_service.adapter.outbound.openmetadata.bootstrap import OmSchemaMigration
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.config import AdapterProfile, get_settings
from document_service.infrastructure.container import ServiceContainer
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)


class ApplicationFactory:
    """Dựng ứng dụng FastAPI từ container."""

    def __init__(self, container: ServiceContainer | None = None) -> None:
        """Nhận container, hoặc tự lấy instance dùng chung."""
        self._container = container or ServiceContainer()

    @property
    def container(self) -> ServiceContainer:
        """Container đang dùng."""
        return self._container

    def create_app(self) -> FastAPI:
        """Dựng ứng dụng với router, handler lỗi và lifespan khởi động."""
        settings = self._container.settings
        application = FastAPI(
            title="Document Service",
            version="0.1.0",
            description="Kho raw data dung chung: Object Storage S3 + OpenMetadata",
            lifespan=self._lifespan,
        )
        install_error_handlers(application)
        application.include_router(routes.router, prefix=settings.app.api_prefix)
        application.include_router(health_routes.router)
        return application

    @asynccontextmanager
    async def _lifespan(self, application: FastAPI) -> AsyncIterator[None]:
        """Chạy migration schema khi start, dọn tài nguyên khi stop."""
        del application
        await self._run_startup()
        yield
        _LOGGER.info("service stopped")

    async def _run_startup(self) -> None:
        """Chuẩn bị schema catalog rồi đánh dấu startup hoàn tất."""
        settings = self._container.settings
        if settings.app.profile is AdapterProfile.FAKE:
            self._container.health.mark_startup_done()
            _LOGGER.info("starting with the fake profile, skipping catalog migration")
            return
        client = OmHttpClient(settings.catalog, self._container.executor("catalog"))
        await OmSchemaMigration(client, settings.catalog).run_on_startup()
        await client.aclose()
        self._container.health.mark_startup_done()
        _LOGGER.info("catalog schema migration complete")


def create_app() -> FastAPI:
    """App factory cho uvicorn và cho test."""
    return ApplicationFactory().create_app()


app = create_app()


def cli() -> None:
    """Chạy service bằng uvicorn, cấu hình lấy từ configs/app.yml."""
    settings = get_settings()
    uvicorn.run(
        "document_service.main:app",
        host="0.0.0.0",
        port=8080,
        log_level=settings.logging.level.lower(),
    )


if __name__ == "__main__":
    cli()
