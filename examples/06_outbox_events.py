"""Ví dụ 6 — Phát sự kiện cho downstream và phát hiện sự kiện thất lạc (POC-11).

Chạy: uv run python examples/06_outbox_events.py

Dựng một webhook receiver bằng thư viện chuẩn, rồi cho thấy:

- sự kiện luôn vào outbox bền vững trước, nên **không mất** khi downstream lỗi;
- downstream trả 503 thì sự kiện vẫn nằm trong hàng đợi và được thử lại;
- mọi bản ghi chưa phát đều đếm được — đó là cách phát hiện sự kiện thất lạc;
- health của publisher báo `DEGRADED` khi hàng đợi còn tồn.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from _common import check, heading, line, reset_container, use_fake_profile

RECEIVED: list[dict[str, Any]] = []
STATE = {"status_code": 503}


class WebhookHandler(BaseHTTPRequestHandler):
    """Receiver webhook tối giản, trả mã do kịch bản điều khiển."""

    def do_POST(self) -> None:  # noqa: N802 - tên do BaseHTTPRequestHandler quy định
        """Nhận một sự kiện và trả mã trạng thái hiện tại."""
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        status = int(STATE["status_code"])
        if status < 400:
            RECEIVED.append(json.loads(body))
        self.send_response(status)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format: str, *args: Any) -> None:
        """Tắt log mặc định của http.server."""
        del format, args


async def main() -> None:
    """Chạy kịch bản outbox và dispatcher."""
    use_fake_profile()
    reset_container()

    from document_service.adapter.outbound.observability.outbox import (
        OutboxDispatcher,
        OutboxEventPublisher,
        SqliteOutbox,
        WebhookEventSender,
    )
    from document_service.adapter.outbound.sqlite_support import SqliteDatabase
    from document_service.config import DependencyResiliencePolicy, EventSettings
    from document_service.domain.model import DomainEvent
    from document_service.domain.value import DocumentId, DocumentVersionId
    from document_service.infrastructure.resilience.executor import ResilientCallExecutor

    server = HTTPServer(("127.0.0.1", 0), WebhookHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    webhook = f"http://127.0.0.1:{server.server_port}/events"

    try:
        with tempfile.TemporaryDirectory(prefix="raw-storage-outbox-") as temp_dir:
            database = SqliteDatabase(str(Path(temp_dir) / "events.sqlite"))
            outbox = SqliteOutbox(database)
            executor = ResilientCallExecutor(
                "events",
                DependencyResiliencePolicy(
                    max_attempts=1, base_delay_seconds=0.01, total_timeout_seconds=3.0
                ),
            )
            publisher = OutboxEventPublisher(outbox, executor)
            settings = EventSettings(
                enabled=True, webhook_urls=[webhook], batch_size=10, max_attempts=3
            )
            # Executor **riêng** cho downstream: breaker của webhook không được ảnh
            # hưởng health của outbox store, vì đó là hai phụ thuộc khác nhau.
            sender = WebhookEventSender(
                settings,
                ResilientCallExecutor(
                    "events-downstream",
                    DependencyResiliencePolicy(
                        max_attempts=1, base_delay_seconds=0.01, total_timeout_seconds=3.0
                    ),
                ),
            )
            dispatcher = OutboxDispatcher(outbox, sender, settings)

            heading("1. Ghi sự kiện vào outbox")
            document_id = DocumentId("DOC-EVENT-0001")
            version_id = DocumentVersionId("VER-EVENT-0001")
            for event_type in ("version.created", "version.approved", "access.changed"):
                await publisher.publish(
                    DomainEvent(
                        event_type=event_type,
                        document_id=document_id,
                        version_id=version_id,
                        payload={"actor": "example"},
                    )
                )
            line("webhook", webhook)
            line("sự kiện chờ phát", await outbox.pending_count())
            check("ba sự kiện nằm trong outbox", await outbox.pending_count() == 3)

            heading("2. Downstream đang lỗi (503)")
            STATE["status_code"] = 503
            failed = await dispatcher.run_once()
            line("gửi thành công", failed.sent)
            line("sẽ thử lại", failed.retried)
            line("còn chờ", failed.pending)
            check("không mất sự kiện nào", failed.pending == 3)
            check("downstream chưa nhận được gì", len(RECEIVED) == 0)
            pending = await outbox.pending(10)
            line("số lần đã thử của sự kiện đầu", pending[0].attempts)
            line("lỗi cuối", pending[0].last_error[:60])

            heading("3. Health báo hàng đợi còn tồn")
            publisher.invalidate_health_cache()
            health = await publisher.check_health()
            line("trạng thái", f"{health.status} · {health.detail}")
            check("health DEGRADED khi còn tồn", str(health.status) == "DEGRADED")

            heading("4. Downstream phục hồi (200)")
            STATE["status_code"] = 200
            ok = await dispatcher.run_once()
            line("gửi thành công", ok.sent)
            line("còn chờ", ok.pending)
            for event in RECEIVED:
                line(event["event_type"], event["document_version_id"])
            check("phát hết hàng đợi", ok.pending == 0)
            check("downstream nhận đủ ba sự kiện", len(RECEIVED) == 3)
            check(
                "giữ đúng thứ tự",
                [event["event_type"] for event in RECEIVED]
                == ["version.created", "version.approved", "access.changed"],
            )

            heading("5. Health trở lại bình thường")
            publisher.invalidate_health_cache()
            health = await publisher.check_health()
            line("trạng thái", f"{health.status} · {health.detail}")
            check("health UP khi outbox trống", str(health.status) == "UP")
            await sender.aclose()

            print("\nVí dụ 6 hoàn tất.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    asyncio.run(main())
