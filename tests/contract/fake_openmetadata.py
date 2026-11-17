"""Server OpenMetadata giả lập trên respx, đủ để chạy bộ contract test của catalog.

Giữ Directory và File trong dict rồi trả lời đúng các endpoint ở bảng mục 5 của
docs/c4-04b-code-structure.md. Nhờ vậy `MetadataCatalogPortContractTest` chạy được
trên **cả** `InMemoryCatalog` và `OpenMetadataCatalogAdapter`, và phơi ra lỗi ánh xạ
`extension` mà một test mock từng endpoint rời sẽ bỏ sót.

Đây **không** phải bằng chứng bản OpenMetadata thật nhận đúng payload: phần đó thuộc
`tests/integration` và test case POC-19.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx


class FakeOpenMetadataServer:
    """Giả lập Drive Service của OpenMetadata ở mức vừa đủ cho hợp đồng catalog."""

    def __init__(self, base_url: str, version: str = "1.12.0") -> None:
        """Nhận base URL và phiên bản server giả lập."""
        self._base_url = base_url.rstrip("/")
        self._version = version
        self._directories: dict[str, dict[str, Any]] = {}
        self._files: dict[str, dict[str, Any]] = {}
        self._counter = 0

    @property
    def base_url(self) -> str:
        """Base URL của server giả lập."""
        return self._base_url

    def install(self, router: Any) -> None:
        """Gắn mọi route cần thiết vào một respx router."""
        router.get(f"{self._base_url}/api/v1/system/version").mock(
            side_effect=lambda request: httpx.Response(200, json={"version": self._version})
        )
        router.put(f"{self._base_url}/api/v1/drives/directories").mock(
            side_effect=self._put_directory
        )
        router.put(f"{self._base_url}/api/v1/drives/files").mock(side_effect=self._put_file)
        router.get(f"{self._base_url}/api/v1/drives/files").mock(side_effect=self._list_files)
        router.get(f"{self._base_url}/api/v1/search/query").mock(side_effect=self._search)
        router.route(
            method="GET",
            url__startswith=f"{self._base_url}/api/v1/drives/directories/name/",
        ).mock(side_effect=self._get_directory_by_name)
        router.route(
            method="GET", url__startswith=f"{self._base_url}/api/v1/drives/files/name/"
        ).mock(side_effect=self._get_file_by_name)
        router.route(
            method="PATCH", url__startswith=f"{self._base_url}/api/v1/drives/directories/"
        ).mock(side_effect=self._patch_directory)
        router.route(method="PATCH", url__startswith=f"{self._base_url}/api/v1/drives/files/").mock(
            side_effect=self._patch_file
        )

    def _next_id(self, prefix: str) -> str:
        """Sinh id tăng dần cho entity."""
        self._counter += 1
        return f"{prefix}-{self._counter:04d}"

    def _put_directory(self, request: httpx.Request) -> httpx.Response:
        """PUT Directory: tạo mới hoặc cập nhật, **không** xoá File con."""
        payload = json.loads(request.content)
        parent = str(payload.get("parent") or payload.get("service", ""))
        fqn = f"{parent}.{payload['name']}" if parent else str(payload["name"])
        existing = self._directories.get(fqn, {})
        entity = {
            "id": existing.get("id", self._next_id("dir")),
            "name": payload["name"],
            "displayName": payload.get("displayName", ""),
            "description": payload.get("description", ""),
            "fullyQualifiedName": fqn,
            "extension": payload.get("extension", {}),
            "version": float(existing.get("version", 0.0)) + 0.1,
        }
        self._directories[fqn] = entity
        return httpx.Response(200, json=entity)

    def _put_file(self, request: httpx.Request) -> httpx.Response:
        """PUT File: idempotent theo FQN, giữ nguyên id khi ghi lại."""
        payload = json.loads(request.content)
        directory = str(payload.get("directory", ""))
        fqn = f"{directory}.{payload['name']}"
        existing = self._files.get(fqn, {})
        entity = {
            "id": existing.get("id", self._next_id("file")),
            "name": payload["name"],
            "fullyQualifiedName": fqn,
            "directory": directory,
            "fileType": payload.get("fileType", ""),
            "size": payload.get("size", 0),
            "checksum": payload.get("checksum", ""),
            "path": payload.get("path", ""),
            "extension": payload.get("extension", {}),
            "version": float(existing.get("version", 0.0)) + 0.1,
        }
        self._files[fqn] = entity
        return httpx.Response(200, json=entity)

    def _get_directory_by_name(self, request: httpx.Request) -> httpx.Response:
        """GET Directory theo FQN."""
        fqn = self._name_from(request, "/api/v1/drives/directories/name/")
        entity = self._directories.get(fqn)
        if entity is None:
            return httpx.Response(404, json={"message": f"không có {fqn}"})
        return httpx.Response(200, json=entity)

    def _get_file_by_name(self, request: httpx.Request) -> httpx.Response:
        """GET File theo FQN."""
        fqn = self._name_from(request, "/api/v1/drives/files/name/")
        entity = self._files.get(fqn)
        if entity is None:
            return httpx.Response(404, json={"message": f"không có {fqn}"})
        return httpx.Response(200, json=entity)

    def _list_files(self, request: httpx.Request) -> httpx.Response:
        """GET danh sách File theo Directory."""
        params = parse_qs(urlparse(str(request.url)).query)
        directory = params.get("directory", [""])[0]
        items = [item for item in self._files.values() if item["directory"] == directory]
        return httpx.Response(200, json={"data": items})

    def _patch_directory(self, request: httpx.Request) -> httpx.Response:
        """PATCH Directory bằng JSON Patch chỉ gồm `replace` trên `extension`."""
        return self._apply_patch(request, self._directories)

    def _patch_file(self, request: httpx.Request) -> httpx.Response:
        """PATCH File bằng JSON Patch."""
        return self._apply_patch(request, self._files)

    def _apply_patch(
        self, request: httpx.Request, store: dict[str, dict[str, Any]]
    ) -> httpx.Response:
        """Áp JSON Patch lên entity theo id."""
        entity_id = str(request.url).rsplit("/", 1)[-1]
        target = next((item for item in store.values() if item["id"] == entity_id), None)
        if target is None:
            return httpx.Response(404, json={"message": f"không có entity {entity_id}"})
        for operation in json.loads(request.content):
            if operation.get("op") != "replace":
                return httpx.Response(400, json={"message": "chỉ hỗ trợ replace trong test này"})
            field = str(operation["path"]).removeprefix("/extension/")
            target.setdefault("extension", {})[field] = operation["value"]
        target["version"] = float(target.get("version", 0.0)) + 0.1
        return httpx.Response(200, json=target)

    def _search(self, request: httpx.Request) -> httpx.Response:
        """GET search: lọc theo các term trên `extension.<field>`."""
        params = parse_qs(urlparse(str(request.url)).query)
        raw_filter = params.get("query_filter", [""])[0]
        clauses = self._clauses(raw_filter)
        hits = []
        for entity in self._files.values():
            extension = entity.get("extension", {})
            if all(str(extension.get(field, "")) == value for field, value in clauses):
                hits.append({"_source": {"extension": extension}})
        return httpx.Response(200, json={"hits": {"total": {"value": len(hits)}, "hits": hits}})

    def _clauses(self, raw_filter: str) -> list[tuple[str, str]]:
        """Đọc danh sách điều kiện term từ `query_filter`."""
        if not raw_filter:
            return []
        parsed = json.loads(raw_filter)
        must = parsed.get("query", {}).get("bool", {}).get("must", [])
        clauses: list[tuple[str, str]] = []
        for item in must:
            for path, value in item.get("term", {}).items():
                clauses.append((path.removeprefix("extension."), str(value)))
        return clauses

    def _name_from(self, request: httpx.Request, prefix: str) -> str:
        """Lấy FQN từ đường dẫn request."""
        path = urlparse(str(request.url)).path
        return path.split(prefix, 1)[-1]
