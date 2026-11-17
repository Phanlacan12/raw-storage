"""Tiện ích dùng chung cho các ví dụ.

Mọi ví dụ chạy với profile `fake` nên **không cần hạ tầng**: không OpenMetadata,
không Object Storage, không database. Ví dụ cần hạ tầng thật được đánh số 07 và tự
báo khi thiếu biến môi trường.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx


def use_fake_profile() -> None:
    """Bật profile fake trước khi import container, và tắt màu log cho dễ đọc."""
    os.environ.setdefault("DS_APP__PROFILE", "fake")
    os.environ.setdefault("DS_LOGGING__LEVEL", "WARNING")
    os.environ.setdefault("NO_COLOR", "1")


def reset_container() -> None:
    """Xoá mọi singleton để mỗi ví dụ chạy trên trạng thái sạch."""
    from document_service.utils.singleton import SingletonMeta

    SingletonMeta.clear()


@asynccontextmanager
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    """Client HTTP gọi trực tiếp vào ứng dụng FastAPI qua ASGI.

    Dùng ASGI thay vì dựng uvicorn để ví dụ chạy được bằng một lệnh `python`.
    """
    use_fake_profile()
    reset_container()
    from document_service.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://document-service.local", timeout=10.0
        ) as client:
            yield client


def heading(title: str) -> None:
    """In tiêu đề một bước."""
    print(f"\n=== {title} ===")


def line(label: str, value: object) -> None:
    """In một dòng kết quả."""
    print(f"  {label:<34} {value}")


def check(label: str, condition: bool) -> None:
    """In kết quả kiểm tra và dừng ví dụ nếu sai."""
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}")
    if not condition:
        raise AssertionError(f"example failed at step: {label}")
