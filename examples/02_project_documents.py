"""Ví dụ 2 — Use case tài liệu dự án phần mềm (mục 2.8 báo cáo).

Chạy: uv run python examples/02_project_documents.py

Dựng đúng kịch bản URD–SRS–SAD của Project A, khai báo quan hệ theo **phiên bản**, rồi
chứng minh ba điều mà POC-05, POC-06 và POC-09 yêu cầu:

- tra cứu được toàn bộ tài liệu của dự án qua một đầu mối;
- từ SRS v2.0 tìm được URD v1.2 và truy vấn ngược cũng đúng;
- tạo SRS v2.1 **không** làm mất quan hệ cũ và không tự đổi đích sang bản mới.
"""

from __future__ import annotations

import asyncio
from typing import Any

from _common import api_client, check, heading, line

PDF = "application/pdf"
COLLECTION = "PROJECT-A"


async def _document(client: Any, document_type: str, title: str) -> str:
    """Đăng ký một tài liệu của Project A."""
    response = await client.post(
        "/api/v1/documents",
        json={"title": title, "document_type": document_type, "collection_id": COLLECTION},
        headers={"Idempotency-Key": f"proj-doc-{document_type.lower()}-0001"},
    )
    return str(response.json()["document_id"])


async def _version(client: Any, document_id: str, label: str, payload: bytes) -> str:
    """Upload một phiên bản và duyệt luôn."""
    created = await client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": (f"{document_id}-{label}.pdf", payload, PDF)},
        data={"version_label": label},
        headers={"Idempotency-Key": f"proj-ver-{document_id}-{label}"},
    )
    version_id = str(created.json()["document_version_id"])
    await client.post(
        f"/api/v1/versions/{version_id}/status",
        params={"document_id": document_id},
        json={"status": "Approved"},
    )
    return version_id


async def _relate(client: Any, relation: str, source: str, target: str) -> None:
    """Khai báo một quan hệ giữa hai phiên bản."""
    response = await client.post(
        "/api/v1/relationships",
        json={
            "relation_type": relation,
            "source_version_id": source,
            "target_version_id": target,
        },
        headers={"Idempotency-Key": f"proj-rel-{source}-{relation}"},
    )
    check(f"khai báo {relation}", response.status_code == 201)


async def main() -> None:
    """Chạy toàn bộ kịch bản dự án."""
    async with api_client() as client:
        heading("1. Tạo ba tài liệu của Project A")
        urd = await _document(client, "URD", "User Requirements Document")
        srs = await _document(client, "SRS", "Software Requirements Specification")
        sad = await _document(client, "SAD", "Software Architecture Document")
        line("URD", urd)
        line("SRS", srs)
        line("SAD", sad)

        heading("2. Tạo các phiên bản")
        urd_v10 = await _version(client, urd, "1.0", b"URD ban dau")
        urd_v12 = await _version(client, urd, "1.2", b"URD cap nhat")
        srs_v10 = await _version(client, srs, "1.0", b"SRS ban dau")
        srs_v20 = await _version(client, srs, "2.0", b"SRS theo URD 1.2")
        sad_v11 = await _version(client, sad, "1.1", b"SAD tham chieu SRS 2.0")
        line("URD v1.0 / v1.2", f"{urd_v10} / {urd_v12}")
        line("SRS v1.0 / v2.0", f"{srs_v10} / {srs_v20}")
        line("SAD v1.1", sad_v11)

        heading("3. Khai báo quan hệ theo phiên bản")
        await _relate(client, "derived_from", srs_v20, urd_v12)
        await _relate(client, "references", sad_v11, srs_v20)

        heading("4. Truy vết từ SRS v2.0")
        outgoing = await client.get(
            f"/api/v1/versions/{srs_v20}/relationships", params={"direction": "outgoing"}
        )
        for item in outgoing.json():
            line(item["relation_type"], f'-> {item["target_version_id"]}')
        check(
            "SRS v2.0 derived_from URD v1.2",
            any(
                item["relation_type"] == "derived_from" and item["target_version_id"] == urd_v12
                for item in outgoing.json()
            ),
        )

        heading("5. Truy vấn ngược từ URD v1.2")
        incoming = await client.get(
            f"/api/v1/versions/{urd_v12}/relationships", params={"direction": "incoming"}
        )
        for item in incoming.json():
            line(item["relation_type"], f'<- {item["target_version_id"]}')
        check(
            "URD v1.2 được SRS v2.0 dẫn xuất",
            any(item["target_version_id"] == srs_v20 for item in incoming.json()),
        )

        heading("6. Tạo SRS v2.1 — quan hệ cũ phải giữ nguyên")
        srs_v21 = await _version(client, srs, "2.1", b"SRS cap nhat nho")
        line("SRS v2.1", srs_v21)
        after = await client.get(
            f"/api/v1/versions/{srs_v20}/relationships", params={"direction": "outgoing"}
        )
        check(
            "quan hệ của v2.0 không bị đổi đích",
            [item["target_version_id"] for item in after.json()] == [urd_v12],
        )
        new_version_edges = await client.get(
            f"/api/v1/versions/{srs_v21}/relationships", params={"direction": "outgoing"}
        )
        check("v2.1 chưa có quan hệ nào", new_version_edges.json() == [])

        heading("7. KB lấy tài liệu Approved của dự án")
        approved = await client.get(
            "/api/v1/search", params={"collection_id": COLLECTION, "status": "Approved"}
        )
        for hit in approved.json()["hits"]:
            line(hit["document_type"], f'{hit["version_label"]} · {hit["document_version_id"]}')
        types = sorted(hit["document_type"] for hit in approved.json()["hits"])
        check("đủ ba loại tài liệu", types == ["SAD", "SRS", "URD"])
        check(
            "mỗi tài liệu đúng một bản hiện hành",
            len(approved.json()["hits"]) == 3,
        )

        print("\nVí dụ 2 hoàn tất.")


if __name__ == "__main__":
    asyncio.run(main())
