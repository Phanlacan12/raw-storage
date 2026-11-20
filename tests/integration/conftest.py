"""Fixture riêng cho test tích hợp: giữ lại biến môi trường trỏ tới hạ tầng thật.

`tests/conftest.py` có fixture autouse `clean_env` xoá mọi biến `DS_*` để test đơn vị
không phụ thuộc máy chạy. Nhưng `skipif` của `test_real_infrastructure.py` đọc
`DS_CATALOG__BASE_URL` ở lúc **collect**, còn fixture chạy **sau** đó — nên test được
thu nhận rồi chạy mà không còn credential, và fail với `401 Token not present` hoặc
`Unable to locate credentials`.

File này ghi đè `clean_env` thành no-op cho riêng thư mục `tests/integration/`, nên
biến môi trường do `deploy/.env` cấp đi được tới adapter.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clean_env() -> None:
    """Không xoá biến môi trường: test tích hợp cần đúng chúng để nối hạ tầng thật."""
    return None
