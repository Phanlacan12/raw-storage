"""Cơ chế singleton có kiểm soát (quy tắc R2 trong plan).

Chỉ dùng cho thành phần hạ tầng dùng chung một instance: client, pool, breaker,
budget, registry health, logger, metrics. Tuyệt đối không dùng cho dữ liệu nghiệp
vụ hay trạng thái của một request.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar


class SingletonMeta(type):
    """Metaclass tạo tối đa một instance cho mỗi lớp, an toàn với nhiều thread."""

    _instances: ClassVar[dict[type, Any]] = {}
    # Khóa phải **reentrant**: một singleton có thể tạo singleton khác trong
    # __init__ của nó (ServiceContainer tạo SettingsProvider), và với
    # threading.Lock thường thì lần vào thứ hai trên cùng thread sẽ deadlock.
    _lock: ClassVar[threading.RLock] = threading.RLock()

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        """Trả instance đã có, hoặc tạo mới một lần duy nhất."""
        if cls not in SingletonMeta._instances:
            with SingletonMeta._lock:
                if cls not in SingletonMeta._instances:
                    SingletonMeta._instances[cls] = super().__call__(*args, **kwargs)
        return SingletonMeta._instances[cls]

    @classmethod
    def clear(mcs, target: type | None = None) -> None:
        """Xoá instance đã lưu để test không rò trạng thái giữa các case."""
        with SingletonMeta._lock:
            if target is None:
                SingletonMeta._instances.clear()
            else:
                SingletonMeta._instances.pop(target, None)

    @classmethod
    def has_instance(mcs, target: type) -> bool:
        """Cho biết lớp đã được khởi tạo chưa, dùng trong test và health check."""
        return target in SingletonMeta._instances
