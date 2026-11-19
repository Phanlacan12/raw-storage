"""Ví dụ 1 — Vòng đời một tài liệu qua API, không cần hạ tầng.

Chạy: uv run python examples/01_quickstart.py

Đi qua đúng các bước ở mục Verification của plan: đăng ký tài liệu → upload 2 phiên
bản → duyệt → kiểm tra bản hiện hành → tải → đọc audit.
"""

from __future__ import annotations

import asyncio

from _common import api_client, check, heading, line

PDF = "application/pdf"


async def main() -> None:
    """Chạy toàn bộ kịch bản."""
    async with api_client() as client:
        heading("1. Check that the service is ready")
        live = await client.get("/livez")
        ready = await client.get("/readyz")
        line("livez", live.json())
        line("readyz", ready.json())
        check("service is in FULL mode", ready.json()["mode"] == "FULL")

        heading("2. Register a document")
        created = await client.post(
            "/api/v1/documents",
            json={
                "title": "Software Requirements Specification",
                "document_type": "SRS",
                "collection_id": "PROJECT-A",
                "access_policy": {"classification": "internal"},
            },
            headers={"Idempotency-Key": "quickstart-doc-0001"},
        )
        document_id = created.json()["document_id"]
        line("document_id", document_id)
        check("document creation returns 201", created.status_code == 201)

        heading("3. Upload two versions")
        first = await client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("srs.pdf", b"noi dung phien ban 1", PDF)},
            data={"version_label": "1.0"},
            headers={"Idempotency-Key": "quickstart-ver-0001"},
        )
        second = await client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("srs.pdf", b"noi dung phien ban 2", PDF)},
            data={"version_label": "2.0"},
            headers={"Idempotency-Key": "quickstart-ver-0002"},
        )
        v1 = first.json()["document_version_id"]
        v2 = second.json()["document_version_id"]
        line("v1.0", v1)
        line("v2.0", v2)
        check("the two versions have different IDs", v1 != v2)
        check("ID does not contain version_label", "1.0" not in v1 and "2.0" not in v2)

        heading("4. Re-upload the same content (de-duplication)")
        duplicate = await client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("srs.pdf", b"noi dung phien ban 2", PDF)},
            headers={"Idempotency-Key": "quickstart-ver-0003"},
        )
        line("created", duplicate.json()["created"])
        line("duplicate_of", duplicate.json()["duplicate_of"])
        check("no new version created", duplicate.json()["created"] is False)

        heading("5. Resend with the same Idempotency-Key")
        replay = await client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("srs.pdf", b"noi dung hoan toan khac", PDF)},
            headers={"Idempotency-Key": "quickstart-ver-0002"},
        )
        line("document_version_id", replay.json()["document_version_id"])
        check("returns the same previous version", replay.json()["document_version_id"] == v2)

        heading("6. Approve a version")
        await client.post(
            f"/api/v1/versions/{v1}/status",
            params={"document_id": document_id},
            headers={"Idempotency-Key": f"approve-{v1}"},
            json={"status": "Approved"},
        )
        approve = await client.post(
            f"/api/v1/versions/{v2}/status",
            params={"document_id": document_id},
            headers={"Idempotency-Key": f"approve-{v2}"},
            json={"status": "Approved"},
        )
        document = await client.get(f"/api/v1/documents/{document_id}")
        line("v2.0 status", approve.json()["status"])
        line("current_version_id", document.json()["current_version_id"])
        check("current version is v2.0", document.json()["current_version_id"] == v2)

        heading("7. Search and download")
        found = await client.get(
            "/api/v1/search",
            params={
                "document_type": "SRS",
                "status": "Approved",
                "collection_id": "PROJECT-A",
            },
        )
        line("result count", found.json()["total_hits"])
        hit_ids = [h["document_version_id"] for h in found.json()["hits"]]
        check("returns Approved versions only", hit_ids == [v2])
        download = await client.get(
            f"/api/v1/versions/{v2}/download", params={"document_id": document_id}
        )
        line("download link", download.json()["url"])
        line("expires in (seconds)", download.json()["expires_in_seconds"])
        check("download link has an expiry", download.json()["expires_in_seconds"] > 0)

        heading("8. Audit trail of the document")
        audit = await client.get(f"/api/v1/documents/{document_id}/audit")
        for event in audit.json()["items"]:
            line(event["action"], f'{event["result"]} · {event["detail"][:40]}')
        actions = [event["action"] for event in audit.json()["items"]]
        check("audit records every action", actions.count("version.created") == 2)

        print("\nExample 1 complete.")


if __name__ == "__main__":
    asyncio.run(main())
