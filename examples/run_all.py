"""Chạy tuần tự mọi ví dụ không cần hạ tầng (01–06).

Chạy: uv run python examples/run_all.py

Dừng ngay ở ví dụ đầu tiên thất bại và trả mã khác 0, nên dùng được như một bài kiểm
tra khói sau khi sửa code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Chạy lần lượt các ví dụ, trả mã lỗi của ví dụ đầu tiên thất bại."""
    folder = Path(__file__).resolve().parent
    examples = [
        path.name
        for path in sorted(folder.glob("[0-9][0-9]_*.py"))
        if not path.name.endswith("_real.py")
    ]
    for name in examples:
        print(f"\n{'=' * 70}\n>>> {name}\n{'=' * 70}")
        completed = subprocess.run(
            [sys.executable, str(folder / name)], cwd=str(folder), check=False
        )
        if completed.returncode != 0:
            print(f"\nExample {name} failed (exit code {completed.returncode}).")
            return completed.returncode
    print(f"\n{'=' * 70}\nAll {len(examples)} examples finished.\n{'=' * 70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
