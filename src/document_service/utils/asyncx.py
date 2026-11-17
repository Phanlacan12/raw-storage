"""Tiện ích bất đồng bộ dùng chung.

Chủ yếu để gọi thư viện đồng bộ (boto3, sqlite3) từ code async mà không chặn event
loop, theo quyết định ở plan: không thêm aioboto3.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Iterable, TypeVar

T = TypeVar("T")


class ThreadOffloader:
    """Chạy hàm đồng bộ trên thread pool của event loop."""

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Gọi hàm đồng bộ và chờ kết quả."""
        if kwargs:
            return await asyncio.to_thread(lambda: func(*args, **kwargs))
        return await asyncio.to_thread(func, *args)


class ConcurrencyLimiter:
    """Giới hạn số coroutine chạy song song."""

    def __init__(self, max_concurrency: int) -> None:
        """Khởi tạo với số lượng tối đa."""
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def run(self, factory: Callable[[], Awaitable[T]]) -> T:
        """Chạy một coroutine trong giới hạn đồng thời."""
        async with self._semaphore:
            return await factory()

    async def gather(self, factories: Iterable[Callable[[], Awaitable[T]]]) -> list[T]:
        """Chạy nhiều coroutine, vẫn tôn trọng giới hạn đồng thời."""
        return list(await asyncio.gather(*(self.run(factory) for factory in factories)))
