"""Endpoint health (mục 10.4 của docs/c4-04b-code-structure.md).

`/livez` **không** chạm phụ thuộc ngoài, để một sự cố của catalog không làm orchestrator
restart hàng loạt pod. `/readyz` tổng hợp theo nhóm phụ thuộc và cập nhật
`DegradedModeGate`. `/internal/healthz/deps` chi tiết, chỉ dùng trong mạng nội bộ.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from document_service.adapter.inbound.http.dependencies import get_container
from document_service.infrastructure.container import ServiceContainer

router = APIRouter()
ContainerDep = Annotated[ServiceContainer, Depends(get_container)]


@router.get("/livez")
async def livez(container: ContainerDep) -> dict[str, str]:
    """Chỉ báo tiến trình còn phục vụ được."""
    return container.health.liveness()


@router.get("/startupz")
async def startupz(container: ContainerDep) -> JSONResponse:
    """Cho biết migration schema đã hoàn tất chưa."""
    payload = container.health.startup()
    status = 200 if payload.get("status") == "ready" else 503
    return JSONResponse(status_code=status, content=payload)


@router.get("/readyz")
async def readyz(container: ContainerDep) -> JSONResponse:
    """Tổng hợp health và cập nhật chế độ phục vụ."""
    timeout = container.settings.health.probe_timeout_seconds
    report = await container.health.readiness(timeout)
    container.gate.update(report.mode)
    status = 200 if report.ready else 503
    return JSONResponse(status_code=status, content={"mode": str(report.mode)})


@router.get("/internal/healthz/deps")
async def health_details(container: ContainerDep) -> Any:
    """Chi tiết từng phụ thuộc, kèm độ trễ và trạng thái."""
    if not container.settings.health.expose_details:
        return JSONResponse(status_code=404, content={"error": "disabled"})
    timeout = container.settings.health.probe_timeout_seconds
    report = await container.health.details(timeout)
    container.gate.update(report.mode)
    return report.as_payload()
