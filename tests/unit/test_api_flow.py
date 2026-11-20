"""Test luồng API end-to-end với profile fake.

Kịch bản đúng như mục Verification của plan: đăng ký tài liệu → upload 2 phiên bản →
duyệt → khai báo quan hệ → truy vấn hai chiều → tìm kiếm → tải → audit, cộng các
trường hợp từ chối quyền và thiếu Idempotency-Key.
"""

from __future__ import annotations

from typing import Any

PDF = "application/pdf"


async def _create_document(client: Any, title: str = "SRS") -> str:
    """Đăng ký tài liệu và trả document_id."""
    response = await client.post(
        "/api/v1/documents",
        json={"title": title, "document_type": "SRS", "collection_id": "PROJECT-A"},
        headers={"Idempotency-Key": f"doc-{title}-0001"},
    )
    assert response.status_code == 201
    return str(response.json()["document_id"])


async def _upload(client: Any, document_id: str, payload: bytes, key: str, label: str) -> Any:
    """Upload một phiên bản."""
    return await client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": ("srs.pdf", payload, PDF)},
        data={"version_label": label},
        headers={"Idempotency-Key": key},
    )


class TestApiFlow:
    """Luồng nghiệp vụ qua HTTP."""

    async def test_health_endpoints(self, app_client: Any) -> None:
        """`/livez` và `/readyz` trả đúng trạng thái sau khi chạy lifespan."""
        assert (await app_client.get("/livez")).json() == {"status": "alive"}
        ready = await app_client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["mode"] == "FULL"

    async def test_health_details_lists_dependencies(self, app_client: Any) -> None:
        """Endpoint chi tiết liệt kê từng phụ thuộc kèm trạng thái."""
        response = await app_client.get("/internal/healthz/deps")
        assert response.status_code == 200
        names = {item["name"] for item in response.json()["dependencies"]}
        assert {"catalog", "object_store", "intent_store", "document_lock"} <= names

    async def test_full_document_lifecycle(self, app_client: Any) -> None:
        """Toàn bộ vòng đời tài liệu qua API."""
        document_id = await _create_document(app_client)
        first = await _upload(app_client, document_id, b"noi dung v1", "ver-key-0001", "1.0")
        second = await _upload(app_client, document_id, b"noi dung v2", "ver-key-0002", "2.0")
        assert first.status_code == 201
        assert second.status_code == 201
        v1 = first.json()["document_version_id"]
        v2 = second.json()["document_version_id"]

        missing_key = await app_client.post(
            f"/api/v1/versions/{v1}/status",
            params={"document_id": document_id},
            json={"status": "Approved"},
        )
        assert missing_key.status_code == 422
        assert "Idempotency-Key" in missing_key.json()["message"]
        approve_first = await app_client.post(
            f"/api/v1/versions/{v1}/status",
            params={"document_id": document_id},
            headers={"Idempotency-Key": f"approve-{v1}"},
            json={"status": "Approved"},
        )
        assert approve_first.status_code == 200
        approve_second = await app_client.post(
            f"/api/v1/versions/{v2}/status",
            params={"document_id": document_id},
            headers={"Idempotency-Key": f"approve-{v2}"},
            json={"status": "Approved"},
        )
        assert approve_second.status_code == 200

        document = await app_client.get(f"/api/v1/documents/{document_id}")
        assert document.json()["current_version_id"] == v2

        relationship = await app_client.post(
            "/api/v1/relationships",
            json={
                "relation_type": "derived_from",
                "source_version_id": v2,
                "target_version_id": v1,
            },
            headers={"Idempotency-Key": "rel-key-0001"},
        )
        assert relationship.status_code == 201

        reverse = await app_client.get(
            f"/api/v1/versions/{v1}/relationships", params={"direction": "incoming"}
        )
        assert reverse.status_code == 200
        assert reverse.json()["items"][0]["relation_type"] == "derived_from"
        assert reverse.json()["items"][0]["source_version_id"] == v2
        assert reverse.json()["items"][0]["target_version_id"] == v1
        assert reverse.json()["items"][0]["direction"] == "incoming"

        search = await app_client.get(
            "/api/v1/search",
            params={
                "document_type": "SRS",
                "status": "Approved",
                "collection_id": "PROJECT-A",
            },
        )
        assert search.status_code == 200
        assert [hit["document_version_id"] for hit in search.json()["hits"]] == [v2]

        download = await app_client.get(
            f"/api/v1/versions/{v2}/download", params={"document_id": document_id}
        )
        assert download.status_code == 200
        assert download.json()["expires_in_seconds"] > 0

        audit = await app_client.get(f"/api/v1/documents/{document_id}/audit")
        actions = [event["action"] for event in audit.json()["items"]]
        assert "document.registered" in actions
        assert actions.count("version.created") == 2
        assert "version.status_changed" in actions
        assert "version.download" in actions

    async def test_duplicate_upload_returns_existing_version(self, app_client: Any) -> None:
        """POC-13: upload lại cùng nội dung không tạo phiên bản mới."""
        document_id = await _create_document(app_client, "DUP")
        first = await _upload(app_client, document_id, b"noi dung", "dup-key-0001", "1.0")
        again = await app_client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("srs.pdf", b"noi dung", PDF)},
            headers={"Idempotency-Key": "dup-key-0002"},
        )
        assert again.status_code == 201
        assert again.json()["created"] is False
        assert again.json()["duplicate_of"] == first.json()["document_version_id"]

    async def test_missing_idempotency_key_rejected(self, app_client: Any) -> None:
        """Endpoint ghi thiếu Idempotency-Key bị từ chối (bất biến I13)."""
        document_id = await _create_document(app_client, "IDEM")
        response = await app_client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("srs.pdf", b"x", PDF)},
        )
        assert response.status_code == 422
        assert response.json()["error"] == "InvalidValueError"

    async def test_duplicate_version_label_conflict(self, app_client: Any) -> None:
        """Nhãn phiên bản trùng trả 409 (bất biến I2)."""
        document_id = await _create_document(app_client, "LABEL")
        await _upload(app_client, document_id, b"a", "label-key-0001", "1.0")
        response = await _upload(app_client, document_id, b"b", "label-key-0002", "1.0")
        assert response.status_code == 409
        assert response.json()["error"] == "VersionLabelConflictError"

    async def test_unknown_document_returns_404(self, app_client: Any) -> None:
        """Tài liệu chưa đăng ký trả 404."""
        response = await app_client.get("/api/v1/documents/DOC-KHONG-TON-TAI")
        assert response.status_code == 404

    async def test_api_does_not_leak_catalog_concepts(self, app_client: Any) -> None:
        """Hợp đồng API không phơi bày khái niệm của OpenMetadata."""
        document_id = await _create_document(app_client, "CLEAN")
        response = await app_client.get(f"/api/v1/documents/{document_id}")
        body = response.text
        for leaked in ("fqn", "fullyQualifiedName", "extension", "entityType"):
            assert leaked not in body


async def test_write_commands_replay_once_and_reject_key_reuse(app_client: Any) -> None:
    """Ba endpoint dùng chung không gian khóa, audit chỉ ghi ở lần thực hiện đầu."""
    documents = "/api/v1/documents"
    key = {"Idempotency-Key": "register-once"}
    body = {"title": "Spec"}
    first = await app_client.post(documents, headers=key, json=body)
    repeat = await app_client.post(documents, headers=key, json=body)
    assert first.status_code == repeat.status_code == 201
    assert first.json() == repeat.json()
    assert (await app_client.post(documents, headers=key, json={"title": "New"})).status_code == 409
    doc = first.json()["document_id"]
    policy_url = f"{documents}/{doc}/access-policy"
    policy = {"classification": "public"}
    assert (await app_client.patch(policy_url, headers=key, json=policy)).status_code == 409
    policy_key = {"Idempotency-Key": "policy-once"}
    for _ in range(2):
        assert (
            await app_client.patch(policy_url, headers=policy_key, json=policy)
        ).status_code == 200
    upload = await _upload(app_client, doc, b"data", "register-once", "v1")
    assert upload.status_code == 409
    edge = {
        "source_version_id": "VER-A",
        "target_version_id": "VER-B",
        "relation_type": "references",
    }
    edge_key = {"Idempotency-Key": "relation-once"}
    for _ in range(2):
        assert (
            await app_client.post("/api/v1/relationships", headers=edge_key, json=edge)
        ).status_code == 201
    edge["target_version_id"] = "VER-C"
    assert (
        await app_client.post("/api/v1/relationships", headers=edge_key, json=edge)
    ).status_code == 409
    audit = (await app_client.get(f"{documents}/{doc}/audit")).json()["items"]
    assert [item["action"] for item in audit].count("document.registered") == 1
    assert [item["action"] for item in audit].count("document.access_policy_changed") == 1


def test_error_response_for_duplicate_conflict_and_catalog_schema() -> None:
    """Các lỗi miền trả mã chặn ghi và mã phụ thuộc chưa sẵn sàng."""
    from document_service.adapter.inbound.http.errors import DomainErrorTranslator
    from document_service.domain.errors import DuplicateContentError, SchemaNotReadyError

    translator = DomainErrorTranslator()
    assert translator.to_response(DuplicateContentError()).status_code == 409
    assert translator.to_response(SchemaNotReadyError()).status_code == 503


async def test_paging_search_versions_and_audit(app_client: Any) -> None:
    """API trả ba trang riêng biệt và từ chối cursor hỏng."""
    doc = await _create_document(app_client)
    for index in range(3):
        await _upload(app_client, doc, bytes([index]), f"page-upload-{index}", str(index))
    for path, items, identity in [
        (f"/api/v1/documents/{doc}/versions", "items", "document_version_id"),
        ("/api/v1/search", "hits", "document_version_id"),
        (f"/api/v1/documents/{doc}/audit", "items", "target_id"),
    ]:
        params = {"page_size": 1}
        seen = []
        for _ in range(5):
            response = await app_client.get(path, params=params)
            assert response.status_code == 200
            data = response.json()
            assert len(data[items]) == 1
            seen.append(data[items][0][identity])
            if data["next_cursor"] is None:
                break
            params["cursor"] = data["next_cursor"]
        assert len(set(seen)) == len(seen) >= 3
        assert data["next_cursor"] is None
        invalid = await app_client.get(path, params={"cursor": "!"})
        assert invalid.status_code == 422
