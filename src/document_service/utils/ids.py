"""Sinh định danh không trùng cho tài liệu, phiên bản và request.

Dùng ULID-like (thời gian + ngẫu nhiên) để ID sắp xếp được theo thời điểm tạo mà
không phụ thuộc cách đặt version_label, theo khuyến nghị mục 3.6 của báo cáo.
"""

from __future__ import annotations

import secrets
import time
from typing import Protocol

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(number: int, length: int) -> str:
    """Mã hoá số nguyên sang chuỗi Crockford base32 có độ dài cố định."""
    digits = []
    for _ in range(length):
        number, remainder = divmod(number, len(_ALPHABET))
        digits.append(_ALPHABET[remainder])
    return "".join(reversed(digits))


class IdGenerator(Protocol):
    """Giao diện sinh định danh."""

    def new_id(self, prefix: str = "") -> str:
        """Sinh một định danh mới."""


class UlidGenerator:
    """Sinh ID dạng ULID rút gọn: 10 ký tự thời gian + 16 ký tự ngẫu nhiên."""

    def new_id(self, prefix: str = "") -> str:
        """Sinh ID mới, có thể kèm tiền tố để dễ đọc trong log."""
        timestamp = _encode(int(time.time() * 1000), 10)
        randomness = _encode(secrets.randbits(80), 16)
        value = f"{timestamp}{randomness}"
        return f"{prefix}-{value}" if prefix else value


class SequentialIdGenerator:
    """Sinh ID tăng dần, chỉ dùng trong test để kết quả đoán được."""

    def __init__(self, start: int = 1) -> None:
        """Bắt đầu từ một số cho trước."""
        self._counter = start

    def new_id(self, prefix: str = "") -> str:
        """Sinh ID kế tiếp."""
        value = f"{self._counter:08d}"
        self._counter += 1
        return f"{prefix}-{value}" if prefix else value
