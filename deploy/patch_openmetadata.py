"""Sửa hai cấu hình sai của OpenMetadata 1.12.0 để File entity vừa tìm kiếm được vừa
hiện lineage.

Chạy (đã nằm sẵn trong `make compose-ready`):

    uv run python deploy/patch_openmetadata.py

## Vấn đề

Service ghi metadata của mỗi phiên bản vào `extension` — một **object**. OpenMetadata
1.12.0 cấu hình loại `file` sai ở hai chỗ, trong khi loại `directory` đúng cả hai:

1. **Mapping.** `file_search_index` khai `extension` là `keyword` (chuỗi đơn). Ghi một
   object vào đó thất bại với `mapper_parsing_exception`, nên không File nào vào được
   index. Hệ quả: Search API luôn rỗng (POC-19 không đạt), và `getLineage` — vốn tra
   entity qua search index — trả 500, nên tab Lineage không hiện gì.
   `directory_search_index` khai đúng là `flat_object`.

2. **Search settings.** Cấu hình search của loại `file` có một aggregation lên field gốc
   `extension`. Với `flat_object`, field gốc không có `doc_values` nên aggregation đó làm
   mọi `/search/query` trả 500. Loại `directory` không có aggregation này.

Chỉ sửa một trong hai thì luôn hỏng một thứ — đó là lý do trước đây trông như phải
chọn giữa lineage và search. Sửa cả hai thì cả hai cùng chạy.

## Script làm gì

1. Đổi `extension` của `file_search_index` sang `flat_object`. OpenSearch không cho đổi
   kiểu field đã có, nên phải xoá index rồi tạo lại với đúng settings, analyzer, alias
   cũ. Dữ liệu index là bản sao suy ra được; OpenMetadata index lại khi entity được ghi.
2. Bỏ aggregation `extension` khỏi search settings của loại `file`. Việc này cần quyền
   admin, nên script đăng nhập bằng `OM_ADMIN_EMAIL`/`OM_ADMIN_PASSWORD` (mặc định là
   tài khoản admin của docker-compose dev).

Cả hai bước đều idempotent: đã đúng thì bỏ qua.

## Khi nào phải chạy lại

Mapping nằm trong OpenSearch (`deploy/data/opensearch`), settings nằm trong MySQL
(`deploy/data/mysql`), nên cả hai sống qua restart. Phải chạy lại khi xoá `deploy/data`,
khi chạy Reindex trong Settings → Applications của OpenMetadata (nó tạo lại index theo
mapping gốc), hoặc khi nâng phiên bản OpenMetadata.

Môi trường production: đây là thay đổi cấu hình sản phẩm, cần đưa vào quy trình triển
khai OpenMetadata của tổ chức, không chạy tay.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

INDEX = "file_search_index"
TARGET_MAPPING = {"type": "flat_object"}
KEEP_SETTINGS = ("number_of_shards", "number_of_replicas", "analysis", "max_ngram_diff")
ASSET_TYPE = "file"
BAD_AGGREGATION_FIELD = "extension"


def _opensearch() -> str:
    """Địa chỉ OpenSearch, mặc định theo docker-compose của repo."""
    return os.environ.get("OPENSEARCH_URL", "http://localhost:9200").rstrip("/")


def _openmetadata() -> str:
    """Địa chỉ OpenMetadata, dùng chung biến với service."""
    return os.environ.get("DS_CATALOG__BASE_URL", "http://localhost:8585").rstrip("/")


def _call(
    method: str, url: str, body: Any = None, token: str | None = None
) -> tuple[int, dict[str, Any]]:
    """Gọi HTTP JSON, trả (status, payload)."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request) as response:
        raw = response.read()
        return response.status, (json.loads(raw) if raw else {})


def fix_mapping() -> bool:
    """Bước 1: `extension` của file_search_index phải là flat_object."""
    _, current = _call("GET", f"{_opensearch()}/{INDEX}")
    body = current[INDEX]
    mappings = body["mappings"]
    if mappings["properties"].get("extension") == TARGET_MAPPING:
        print("[OK  ] mapping: extension is already flat_object")
        return True

    settings = body["settings"]["index"]
    keep = {name: settings[name] for name in KEEP_SETTINGS if name in settings}
    aliases = {name: {} for name in (body.get("aliases") or {})}
    mappings["properties"]["extension"] = dict(TARGET_MAPPING)

    _call("DELETE", f"{_opensearch()}/{INDEX}")
    _call(
        "PUT",
        f"{_opensearch()}/{INDEX}",
        {"settings": {"index": keep}, "mappings": mappings, "aliases": aliases},
    )
    _, after = _call("GET", f"{_opensearch()}/{INDEX}/_mapping")
    if after[INDEX]["mappings"]["properties"].get("extension") != TARGET_MAPPING:
        print("[FAIL] mapping: extension did not change")
        return False
    print(f"[OK  ] mapping: {INDEX} recreated with extension=flat_object")
    return True


def _admin_token() -> str:
    """Đăng nhập admin; OpenMetadata basic auth nhận mật khẩu dạng base64."""
    email = os.environ.get("OM_ADMIN_EMAIL", "admin@open-metadata.org")
    password = os.environ.get("OM_ADMIN_PASSWORD", "admin")
    _, payload = _call(
        "POST",
        f"{_openmetadata()}/api/v1/users/login",
        {"email": email, "password": base64.b64encode(password.encode()).decode()},
    )
    return str(payload["accessToken"])


def fix_search_settings() -> bool:
    """Bước 2: bỏ aggregation lên field gốc `extension` của loại file."""
    token = _admin_token()
    _, payload = _call(
        "GET", f"{_openmetadata()}/api/v1/system/settings/searchSettings", token=token
    )
    config = payload["config_value"]
    changed = False
    for asset in config.get("assetTypeConfigurations", []):
        if asset.get("assetType") != ASSET_TYPE:
            continue
        kept = [
            item
            for item in asset.get("aggregations", [])
            if item.get("field") != BAD_AGGREGATION_FIELD
        ]
        if len(kept) != len(asset.get("aggregations", [])):
            asset["aggregations"] = kept
            changed = True
    if not changed:
        print("[OK  ] search settings: no root `extension` aggregation on file")
        return True
    _call(
        "PUT",
        f"{_openmetadata()}/api/v1/system/settings",
        {"config_type": "searchSettings", "config_value": config},
        token=token,
    )
    print("[OK  ] search settings: removed root `extension` aggregation on file")
    return True


def main() -> int:
    """Chạy hai bước, dừng ở bước đầu tiên thất bại."""
    try:
        return 0 if fix_mapping() and fix_search_settings() else 1
    except urllib.error.HTTPError as error:
        print(f"[FAIL] {error.code} {error.reason} on {error.url}")
        if error.code in (401, 403):
            print("       Check OM_ADMIN_EMAIL / OM_ADMIN_PASSWORD.")
        return 1
    except urllib.error.URLError as error:
        print(f"[FAIL] cannot reach the stack: {error.reason}")
        print("       Is it up? docker compose -f deploy/docker-compose.yml ps")
        return 1


if __name__ == "__main__":
    sys.exit(main())
