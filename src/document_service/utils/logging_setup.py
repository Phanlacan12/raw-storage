"""Thiết lập log: màu, định dạng, handler và mức log.

Đây là tiện ích kỹ thuật thuần, không mang khái niệm nghiệp vụ. Audit log nghiệp vụ
nằm ở adapter/outbound/observability và chỉ *dùng* formatter ở đây.

Hai chế độ:
- `TerminalFormatter`: cho người đọc trên terminal, có màu khi đầu ra là TTY.
- `JsonLogFormatter`: một dòng JSON mỗi bản ghi, dùng khi chạy thật để log tập trung
  thu được (mục 11.7 của docs/c4-04b-code-structure.md).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, ClassVar, TextIO

from document_service.utils.singleton import SingletonMeta

RESERVED_RECORD_KEYS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class LogPalette:
    """Mã màu ANSI dùng cho log trên terminal."""

    RESET = "\033[0m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    LEVEL_COLORS: ClassVar[dict[int, str]] = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[1;41m",
    }

    @classmethod
    def supports_color(cls, stream: TextIO | None = None) -> bool:
        """Cho biết có nên bật màu hay không.

        Tôn trọng NO_COLOR và FORCE_COLOR, và tắt màu khi đầu ra không phải TTY để
        log trong CI hay file không lẫn ký tự điều khiển.
        """
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("FORCE_COLOR"):
            return True
        target = stream or sys.stderr
        return bool(getattr(target, "isatty", lambda: False)())

    @classmethod
    def paint(cls, text: str, color: str, enabled: bool) -> str:
        """Bọc chuỗi trong mã màu nếu màu đang bật."""
        if not enabled or not color:
            return text
        return f"{color}{text}{cls.RESET}"

    @classmethod
    def level_color(cls, levelno: int) -> str:
        """Màu tương ứng mức log."""
        return cls.LEVEL_COLORS.get(levelno, "")


class TerminalFormatter(logging.Formatter):
    """Định dạng log một dòng, dễ đọc, có màu theo mức log."""

    def __init__(self, use_color: bool | None = None) -> None:
        """Chọn bật màu, mặc định tự phát hiện theo TTY."""
        super().__init__(datefmt="%H:%M:%S")
        self._use_color = LogPalette.supports_color() if use_color is None else use_color

    def format(self, record: logging.LogRecord) -> str:
        """Dựng dòng log gồm thời gian, mức, logger, nội dung và trường phụ."""
        timestamp = LogPalette.paint(self.formatTime(record), LogPalette.DIM, self._use_color)
        level = LogPalette.paint(
            f"{record.levelname:<8}", LogPalette.level_color(record.levelno), self._use_color
        )
        name = LogPalette.paint(record.name, LogPalette.BOLD, self._use_color)
        line = f"{timestamp} {level} {name} · {record.getMessage()}"
        extras = _extra_fields(record)
        if extras:
            rendered = " ".join(f"{key}={value}" for key, value in sorted(extras.items()))
            line = f"{line} {LogPalette.paint(rendered, LogPalette.DIM, self._use_color)}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


class JsonLogFormatter(logging.Formatter):
    """Định dạng mỗi bản ghi thành một dòng JSON cho log tập trung."""

    def format(self, record: logging.LogRecord) -> str:
        """Dựng payload JSON gồm trường chuẩn và trường phụ."""
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Lấy các trường do người gọi truyền qua `extra=`."""
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in RESERVED_RECORD_KEYS and not key.startswith("_")
    }


class LoggingConfigurator(metaclass=SingletonMeta):
    """Cấu hình logging cho cả tiến trình, đúng một lần."""

    def __init__(self) -> None:
        """Chưa cấu hình gì khi mới khởi tạo."""
        self._configured = False

    @property
    def configured(self) -> bool:
        """Cho biết logging đã được cấu hình chưa."""
        return self._configured

    def configure(self, level: str = "INFO", json_format: bool = False) -> None:
        """Gắn một handler duy nhất lên root logger với formatter đã chọn."""
        if self._configured:
            return
        formatter: logging.Formatter = JsonLogFormatter() if json_format else TerminalFormatter()
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(formatter)
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(level.upper())
        self._configured = True

    def reset(self) -> None:
        """Bỏ cấu hình để test chạy độc lập."""
        logging.getLogger().handlers.clear()
        self._configured = False


def get_logger(name: str) -> logging.Logger:
    """Lấy logger theo tên module, sau khi bảo đảm logging đã được cấu hình."""
    configurator = LoggingConfigurator()
    if not configurator.configured:
        configurator.configure()
    return logging.getLogger(name)
