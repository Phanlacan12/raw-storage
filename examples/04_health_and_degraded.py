"""Ví dụ 4 — Health check và chế độ suy giảm (mục 10 của docs/c4-04b).

Chạy: uv run python examples/04_health_and_degraded.py

Cho thấy ba điều quan trọng nhất của thiết kế health:

- `/livez` **không** đổi khi phụ thuộc ngoài sập, nên orchestrator không restart vô ích;
- `/readyz` chuyển `ServiceMode` theo **nhóm** phụ thuộc, không theo tên cụ thể;
- API ghi bị chặn bằng `503` kèm `Retry-After` thay vì `500`.
"""

from __future__ import annotations

import asyncio

from _common import api_client, check, heading, line


async def main() -> None:
    """Chạy kịch bản health và suy giảm."""
    async with api_client() as client:
        from document_service.infrastructure.container import ServiceContainer

        container = ServiceContainer()
        object_store = container.ports.objects
        catalog = container.ports.catalog

        heading("1. Mọi phụ thuộc khỏe")
        details = await client.get("/internal/healthz/deps")
        for item in details.json()["dependencies"]:
            line(item["name"], f'{item["status"]} · {item["detail"][:40]}')
        line("service_mode", details.json()["mode"])
        check("chế độ FULL", details.json()["mode"] == "FULL")

        heading("2. Object Storage sập")
        object_store.available = False
        object_store.invalidate_health_cache()
        live = await client.get("/livez")
        ready = await client.get("/readyz")
        line("livez", f"{live.status_code} {live.json()}")
        line("readyz", f"{ready.status_code} {ready.json()}")
        check("livez vẫn 200", live.status_code == 200)
        check("readyz báo không sẵn sàng", ready.status_code == 503)
        check("chế độ NOT_READY", ready.json()["mode"] == "NOT_READY")

        heading("3. API ghi bị chặn đúng cách")
        blocked = await client.post(
            "/api/v1/documents",
            json={"title": "SRS", "document_type": "SRS"},
            headers={"Idempotency-Key": "health-example-0001"},
        )
        line("mã trả về", blocked.status_code)
        line("retry-after", blocked.headers.get("retry-after"))
        line("thông điệp", blocked.json()["message"])
        check("trả 503 chứ không phải 500", blocked.status_code == 503)
        check("có header Retry-After", blocked.headers.get("retry-after") is not None)

        heading("4. Object Storage phục hồi")
        object_store.available = True
        object_store.invalidate_health_cache()
        ready = await client.get("/readyz")
        line("readyz", f"{ready.status_code} {ready.json()}")
        check("trở lại FULL", ready.json()["mode"] == "FULL")
        allowed = await client.post(
            "/api/v1/documents",
            json={"title": "SRS", "document_type": "SRS"},
            headers={"Idempotency-Key": "health-example-0002"},
        )
        check("API ghi hoạt động lại", allowed.status_code == 201)

        heading("5. Health check của adapter là chỉ-đọc")
        before = len(await object_store.list_under_prefix("objects/"))
        result = await catalog.check_health()
        after = len(await object_store.list_under_prefix("objects/"))
        line("catalog health", f"{result.status} · {result.detail}")
        line("số object trước/sau", f"{before}/{after}")
        check("health không tạo thêm dữ liệu", before == after)

        print("\nVí dụ 4 hoàn tất.")


if __name__ == "__main__":
    asyncio.run(main())
