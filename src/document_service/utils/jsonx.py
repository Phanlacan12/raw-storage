"""Đọc/ghi JSON ổn định, dùng cho manifest intent, outbox và audit log.

Khóa được sắp xếp để hai lần ghi cùng nội dung cho ra cùng một chuỗi byte, nhờ đó
retry ghi manifest là thao tác idempotent thật sự.
"""

from __future__ import annotations

import json
from typing import Any


class JsonCodec:
    """Bộ mã hoá JSON có thứ tự khóa cố định."""

    def __init__(self, indent: int | None = None) -> None:
        """Chọn mức thụt lề khi ghi."""
        self._indent = indent

    def dumps(self, payload: dict[str, Any]) -> str:
        """Chuyển dict sang chuỗi JSON."""
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=self._indent)

    def dumpb(self, payload: dict[str, Any]) -> bytes:
        """Chuyển dict sang byte JSON, dùng khi ghi lên Object Storage."""
        return self.dumps(payload).encode("utf-8")

    def loads(self, raw: str | bytes) -> dict[str, Any]:
        """Đọc chuỗi hoặc byte JSON thành dict."""
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("JSON payload must be an object")
        return parsed
