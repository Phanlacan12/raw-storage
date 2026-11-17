"""Tiện ích thao tác đường dẫn cục bộ, dùng cho sqlite và dữ liệu tạm."""

from __future__ import annotations

from pathlib import Path


class LocalPaths:
    """Chuẩn bị đường dẫn cục bộ trước khi mở file."""

    def ensure_parent(self, path: str | Path) -> Path:
        """Tạo thư mục cha nếu chưa có và trả về đường dẫn đầy đủ."""
        resolved = Path(path).expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def ensure_dir(self, path: str | Path) -> Path:
        """Tạo thư mục nếu chưa có và trả về đường dẫn."""
        resolved = Path(path).expanduser()
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved
