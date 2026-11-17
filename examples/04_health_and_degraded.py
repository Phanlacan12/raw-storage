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

        heading("1. All dependencies healthy")
        details = await client.get("/internal/healthz/deps")
        for item in details.json()["dependencies"]:
            line(item["name"], f'{item["status"]} · {item["detail"][:40]}')
        line("service_mode", details.json()["mode"])
        check("mode is FULL", details.json()["mode"] == "FULL")

        heading("2. Object Storage goes down")
        object_store.available = False
        object_store.invalidate_health_cache()
        live = await client.get("/livez")
        ready = await client.get("/readyz")
        line("livez", f"{live.status_code} {live.json()}")
        line("readyz", f"{ready.status_code} {ready.json()}")
        check("livez still 200", live.status_code == 200)
        check("readyz reports not ready", ready.status_code == 503)
        check("mode is NOT_READY", ready.json()["mode"] == "NOT_READY")

        heading("3. Write APIs are blocked correctly")
        blocked = await client.post(
            "/api/v1/documents",
            json={"title": "SRS", "document_type": "SRS"},
            headers={"Idempotency-Key": "health-example-0001"},
        )
        line("status code", blocked.status_code)
        line("retry-after", blocked.headers.get("retry-after"))
        line("message", blocked.json()["message"])
        check("returns 503, not 500", blocked.status_code == 503)
        check("Retry-After header present", blocked.headers.get("retry-after") is not None)

        heading("4. Object Storage recovers")
        object_store.available = True
        object_store.invalidate_health_cache()
        ready = await client.get("/readyz")
        line("readyz", f"{ready.status_code} {ready.json()}")
        check("back to FULL", ready.json()["mode"] == "FULL")
        allowed = await client.post(
            "/api/v1/documents",
            json={"title": "SRS", "document_type": "SRS"},
            headers={"Idempotency-Key": "health-example-0002"},
        )
        check("write API works again", allowed.status_code == 201)

        heading("5. Adapter health checks are read-only")
        before = len(await object_store.list_under_prefix("objects/"))
        result = await catalog.check_health()
        after = len(await object_store.list_under_prefix("objects/"))
        line("catalog health", f"{result.status} · {result.detail}")
        line("objects before/after", f"{before}/{after}")
        check("health creates no extra data", before == after)

        print("\nExample 4 complete.")


if __name__ == "__main__":
    asyncio.run(main())
