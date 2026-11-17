# ĐỐI SOÁT CODE VỚI THIẾT KẾ

> **Mục đích:** Mỗi module code xong phải đối chiếu với tài liệu thiết kế, ghi lại chỗ khớp, chỗ lệch có lý do và chỗ còn thiếu. Không để lệch âm thầm: lệch thì **hoặc** sửa code, **hoặc** sửa tài liệu, và ghi lý do ngay trong bảng.
> **Trạng thái:** Cập nhật 18/11/2026 (lượt 2). `mypy` sạch trên 91 file, `pylint 10.00/10` **không còn cảnh báo nào**, **224 test** (6 bỏ qua: 5 test tích hợp cần hạ tầng, 1 test tính duy nhất của biến thể S3 manifest), **6 ví dụ** trong `examples/` chạy được bằng một lệnh.
> **Ánh xạ module ↔ D1–D18:** [src/README.md](../src/README.md).

## 1. Checkpoint theo module

| # | Module | Phần tử trong docs | Trạng thái | Ghi chú |
|---|---|---|---|---|
| B0 | `configs/*.yml` | c4-04b mục 2 (cấu hình ngoài mã nguồn), mục 11.3 | **Khớp** | 10 file theo khối; thứ tự ưu tiên init → env → `.env` → YAML → mặc định; bí mật chỉ qua env |
| B1 | `config.py`, `utils/`, `infrastructure/container.py`, `main.py` | c4-04b mục 2, 2.1, 2.2 | **Khớp** | `SingletonMeta` dùng `RLock` (xem Lệch L1) |
| B2 | `domain/` | c4-04 mục 4.1–4.3, c4-04b mục 3 | **Khớp** | 8 port là ABC; 4 policy kế thừa `DomainPolicy`; I1–I14 có test |
| B3 | `application/` | c4-04b mục 6, 7; c4-05 luồng 1, 2 | **Khớp có điều chỉnh** | Xem Lệch L2, L3 |
| B4 | `infrastructure/resilience/` | c4-04b mục 11.1–11.5 | **Khớp** | `BackoffStrategy` → `FullJitterBackoff`/`FixedBackoff`; một executor cho mỗi phụ thuộc |
| B5 | `adapter/outbound/openmetadata/` | c4-04b mục 4, 5, 8, 9 | **Khớp, chưa xác minh trên bản thật** | Đường dẫn API theo bảng mục 5 nhưng **chỉ test bằng respx**; phải đối chiếu OpenAPI của bản được chốt |
| B6 | `adapter/outbound/` còn lại | c4-04b mục 9, 10.3, 11.6 | **Khớp** | 3 hiện thực intent store; `PresignedUrlIssuer`/`ProxyStreamer` tách riêng; `MetricsRecorder` theo mục 11.7 |
| B6b | Health ở lớp outbound | c4-04b mục 10.2 | **Khớp** | `HealthProbe` ở `infrastructure/health.py`; mỗi adapter hiện thực `_probe_dependency()`; xem Lệch L4 |
| B7 | `adapter/inbound/` | c4-04b mục 10.4, 12 | **Khớp** | Gồm D17 `sync/` (bổ sung sau rà soát, xem Thiếu T1) |
| B8 | `worker/reconcile.py` | c4-04b mục 7; c4-05 luồng 7 | **Khớp** | `IntentRecoveryJob`, `OrphanObjectScanner`, `DanglingEntityScanner`, CLI |
| B6c | Outbox dispatcher | c4-02 C10, c4-04b mục 11.7; POC-11 | **Khớp** | `SqliteOutbox` + `OutboxEventPublisher` + `WebhookEventSender` + `OutboxDispatcher`; phụ thuộc `events` có executor riêng (xem Lệch L12) |
| B9 | `tests/` | c4-04b mục 13, 14 | **Khớp** | Đủ 6 bộ contract test: catalog (fake + OpenMetadata qua server giả lập), relationship, intent (3 hiện thực), object store (fake + moto), policy decision, event publisher |
| B9b | `examples/` | plan B9b | **Khớp** | 6 ví dụ không cần hạ tầng + 1 ví dụ cần hạ tầng tự in hướng dẫn; `make examples` chạy tuần tự |
| B10 | `deploy/`, `.github/workflows/` | c4-06 mục 6.1, 6.5 | **Khớp** | compose có healthcheck; CI theo khuôn repo mẫu, thêm cổng kiểm tra sơ đồ mermaid |

## 2. Lệch có lý do

| ID | Thiết kế nói | Code làm | Lý do |
|---|---|---|---|
| L1 | `SingletonMeta` dùng `threading.Lock` | dùng `threading.RLock` | Khóa không reentrant gây **deadlock thật**: `ServiceContainer.__init__` tạo `SettingsProvider` khi đang giữ khóa. Lỗi này đã làm service treo khi khởi động, phát hiện bằng `faulthandler`. Có test `test_nested_creation_does_not_deadlock` |
| L2 | Use case nhận từng port làm tham số riêng (sơ đồ lớp mục 4) | nhận một `PortBundle` | pylint `max-args=5` của repo mẫu; từng port vẫn truy cập qua thuộc tính cùng tên nên hợp đồng thiết kế không đổi |
| L3 | `UploadIntent` gồm `request_id`, `version_id`, checksum, trạng thái (mục 3.5 báo cáo) | thêm `payload` chứa snapshot phiên bản | Không có snapshot thì sau khi service restart, job phục hồi **không** dựng lại được entity để đăng ký — chính tình huống POC-21 |
| L4 | `ping()` nằm trên port (bản code đầu) | bỏ `ping()` khỏi port, health do `HealthProbe` của adapter | Đúng nguyên tắc ở mục 10.2: chỉ adapter biết phép thử rẻ và chỉ-đọc, và chỉ adapter giữ breaker |
| L5 | `ObjectStorePort` chỉ có `put_immutable` | thêm `put_overwrite(uri, payload)` | Manifest intent phải ghi đè được khi trạng thái đổi. Docstring khoanh rõ: raw file **luôn** đi qua `put_immutable` (bất biến I3); có test idempotent cho `put_immutable` |
| L6 | `AuditEvent` gồm actor, action, target, result | thêm `document_id` | Không có trường này thì audit của phiên bản **không tra được** theo tài liệu, tức POC-14 không đạt. Phát hiện khi chạy luồng end-to-end |
| L7 | Mức Code không nói tới `configs/sync.yml` | thêm khối `sync` | D17 cần khai báo nguồn, chu kỳ và ánh xạ quyền; đã cập nhật lại plan và `configs/README.md` |
| L8 | `ServiceContainer` là điểm wiring duy nhất, gồm cả dựng use case | tách `UseCaseFactory` (`application/factory.py`) | Container chạm ngưỡng 20 public method của pylint. Tách theo trách nhiệm: container lo wiring hạ tầng, factory lo dựng use case; thêm use case mới không làm container phình |
| L9 | Endpoint nhận từng dependency rời | gom `RequestContext`/`WriteContext`/`UploadContext`/`SearchParams` ở `http/context.py` | Endpoint vượt `max-args=5`; context object giữ hợp đồng API ở mục 12 không đổi và làm rõ endpoint nào là đường ghi |
| L10 | Danh sách trường lọc được nằm ở `metadata_builder` và `config` | gom về `domain/metadata_fields.py` | pylint phát hiện trùng lặp thật: hai bản danh sách sẽ lệch nhau khi thêm trường. Nay `config.py` và builder đọc cùng một nguồn |
| L11 | `OmExtensionMapper` chỉ chuyển dict | thêm `to_document_metadata()` | `entity.py` và `search.py` từng dựng `DocumentMetadata` bằng hai đoạn code giống nhau |
| L12 | Sự kiện là một phụ thuộc | tách **hai** phụ thuộc: outbox store và downstream, mỗi bên một `ResilientCallExecutor` (`configs/resilience.yml` có khối `events`) | Ví dụ 06 phơi ra lỗi thật: dùng chung executor thì 3 lần webhook lỗi làm breaker mở, và health của **outbox store** báo `DOWN` dù sqlite hoàn toàn khỏe |
| L13 | `c4-04b` mục 5: `Collection → Directory cấp trên`, Document nằm trong Directory của collection | Directory của tài liệu nằm **trực tiếp dưới thư mục gốc**, collection giữ ở `extension.collection_id` | Bộ contract test round-trip phơi ra lỗi: ghi theo cây `service.root.collection.document_id` nhưng đọc theo `service.root.document_id` → 404. Chọn phương án này vì FQN phải **ổn định khi tài liệu chuyển collection**, và `read_document(document_id)` phải tra được mà không cần biết collection. Directory của collection vẫn được tạo để duyệt cây |

## 3. Còn thiếu và khoảng trống đã biết

| ID | Nội dung | Ảnh hưởng | Xử lý |
|---|---|---|---|
| T1 | **D17 Sync Orchestrator** từng bị bỏ sót: thư mục `adapter/inbound/sync/` chỉ có `__init__.py` | POC-12 không kiểm chứng được | **Đã bổ sung** 17/11/2026: `SourceSyncJob`, `FileSystemSourceConnector`, `SourcePermissionMapper`, `SourceSyncScheduler` + 11 test |
| T2 | `S3ManifestIntentStore` (biến thể A của Q2) từng thiếu, chỉ có sqlite và fake | Q2 không thể chốt bằng số liệu | **Đã bổ sung** cùng ngày và đưa vào contract test |
| T3 | `PolicyDecisionPortContractTest`, `EventPublisherPortContractTest` chưa thành bộ riêng | Hai port này từng chỉ được phủ gián tiếp | **Đã bổ sung** 18/11/2026, cùng `MetadataCatalogPortContractTest` chạy trên server OpenMetadata giả lập |
| T7 | Catalog chưa có `ensure_collection` trong luồng ghi chính | Collection được tạo khi quản trị gọi riêng, chưa tự tạo khi đăng ký tài liệu | Quyết định sau khảo sát: tạo collection là việc quản trị, không nên nằm trong đường ghi tài liệu |
| T4 | Khóa phân tán | Nhiều instance Document Service sẽ **không** giữ được I4/I5 | Đã nêu là ngoài phạm vi; hiện chỉ có `InMemoryDocumentLock` trong tiến trình |
| T5 | Đường dẫn API OpenMetadata | Test bằng respx không chứng minh bản thật nhận đúng payload | Chạy `tests/integration` khi có hạ tầng (POC-19, 20, 22) |
| T6 | C9 Search Gateway, C11 Admin UI, C12 MCP | Ngoài phạm vi đã thống nhất | Chỉ bật nếu PoC cho thấy cần |

## 4. Kết quả có ý nghĩa cho quyết định còn mở

| Quyết định | Dữ liệu từ code và test | Hàm ý |
|---|---|---|
| **Q2 — intent store** | `IntentStorePortContractTest` chạy trên 3 hiện thực. `SqliteRegistryIntentStore` **đạt** test hai request đồng thời cùng `idempotency_key` nhờ ràng buộc `UNIQUE`. `S3ManifestIntentStore` **bỏ qua** test đó: API S3 chuẩn không có phép ghi có điều kiện dùng được trên mọi sản phẩm tương thích, nên hai lượt ghi index đều thành công và lượt sau ghi đè lượt trước | Nghiêng về **registry database**. Nếu vẫn muốn manifest trên S3, phải chấp nhận cửa sổ trùng khóa hoặc thêm cơ chế khóa ngoài — đúng điều mục 3.5 báo cáo yêu cầu kiểm chứng |
| **Q2 — chi phí đối soát** | `S3ManifestIntentStore.find_unfinished` phải `list_objects` toàn bộ prefix, chi phí tăng theo tổng số intent đã từng ghi | Thêm một lý do nữa nghiêng về registry |
| **Q4 — relationship store** | `RelationshipStorePortContractTest` chạy trên fake và `SqliteRelationshipRegistry`, cả hai **đạt** truy vấn hai chiều theo `relation_type`. `OmLineageRelationshipStore` đã viết nhưng **chỉ** kiểm chứng được trên hạ tầng thật | Chưa chốt. Test tích hợp sẽ quyết định; nếu Lineage API không truy vấn ngược theo loại quan hệ thì đổi binding, không sửa use case |
| **Q3 — tìm kiếm** | `OmSearchQueryBuilder` lọc bằng `query_filter` trên `extension.<field>`. Một lỗi thật đã được test bắt: dict không được JSON-encode nên server nhận chuỗi dấu nháy đơn | Đường API khả thi; khả năng **thực sự lọc được** vẫn phải đo ở POC-19 |

## 4b. Lỗi thật mà test và ví dụ đã bắt được

| # | Lỗi | Phát hiện bởi | Hệ quả nếu không sửa |
|---|---|---|---|
| 1 | Deadlock khi khởi động do khóa singleton không reentrant | chạy thử service, truy vết bằng `faulthandler` | Service treo ngay khi start, không có log lỗi |
| 2 | `query_filter` gửi dict thay vì chuỗi JSON | `test_openmetadata_catalog.py` | Search API nhận chuỗi nháy đơn, mọi truy vấn lọc đều sai |
| 3 | Audit của phiên bản không tra được theo tài liệu | chạy luồng end-to-end | POC-14 không đạt |
| 4 | FQN của Directory tài liệu khác nhau giữa ghi và đọc | `test_catalog_contract.py` (round-trip) | Mọi `read_document` trả 404 trên OpenMetadata thật |
| 5 | 404 của catalog rò lên thành lỗi hạ tầng | `test_catalog_contract.py` | API trả 400/500 thay vì 404 |
| 6 | Fake catalog tìm kiếm theo entity, bỏ qua metadata đã đăng ký | `test_catalog_contract.py` | Test search cho kết quả sai lệch so với bản thật |
| 7 | Outbox store và downstream dùng chung executor | `examples/06_outbox_events.py` | Breaker của webhook làm health của outbox báo DOWN, service bị coi là không sẵn sàng oan |
| 8 | Fake catalog ghi đè Document làm mất phiên bản | `examples/05_source_sync.py` qua test đồng bộ | Đồng bộ lượt hai làm mất lịch sử phiên bản |

## 5. Kết quả kiểm chứng đã chạy (18/11/2026)

| # | Nội dung | Kết quả |
|---|---|---|
| 0 | `conda env rawstorage` + `uv sync --frozen` | Sạch; `uv run python -V` → **3.12.16**; `.python-version` = `3.12` |
| 1 | `uv run pytest` | **180 passed, 6 skipped** |
| 2 | `make test` (mypy → pytest → pylint) | mypy sạch trên 90 file; pylint **10.00/10**, không còn cảnh báo |
| 3 | Luồng end-to-end qua HTTP với profile fake | Đăng ký → 2 phiên bản → duyệt → quan hệ hai chiều → tìm kiếm lọc tổ hợp → tải → 8 bản ghi audit; `/readyz` = `FULL`, 7 phụ thuộc đều `UP` |
| 4 | Lỗi một phía trong luồng ghi | `test_reconcile.py`: intent → `RetryPending` → job phục hồi → `Completed`, **không** nhân đôi phiên bản |
| 5 | Hai lượt duyệt đồng thời | `test_invariants.py::test_concurrent_approval_keeps_one_approved`: đúng một bản `Approved` |
| 6 | `/livez` khi phụ thuộc DOWN | `test_health.py`: `livez` không đổi; `ReadinessPolicy` chuyển `READ_ONLY`/`DOWNLOAD_ONLY`/`NOT_READY` đúng nhóm phụ thuộc |
| 7 | Test tích hợp | Tự bỏ qua khi thiếu `DS_CATALOG__BASE_URL`/`DS_STORAGE__ENDPOINT` (5 test) — **chưa chạy vì máy chưa có docker** |
| 8 | Cổng CI | Chạy lại script của workflow tại máy: chèn một sơ đồ mermaid lỗi → checker báo `1 diagram lỗi`; cổng đếm dòng → không file nào vượt 1000 dòng (dài nhất: 474). **Workflow trên GitHub chưa chạy** vì repo còn ở máy local |
| 9 | Cô lập singleton | Chạy `pytest` hai lượt, lượt hai đảo thứ tự file: kết quả giống nhau |
| 10 | `make docs-check` | **0 diagram lỗi** trên toàn bộ `docs/`; kiểm tra link nội bộ của mọi README và `docs/*.md`: không link nào trỏ tới file thiếu |
| 11 | `make examples` | 6 ví dụ chạy hết, mỗi bước in `[OK  ]`; ví dụ 07 in hướng dẫn dựng hạ tầng khi thiếu biến môi trường. Bước này cũng nằm trong `python_package.yaml` nên ví dụ không mục theo thời gian |

## 6. Cách cập nhật tài liệu này

1. Xong một module: đối chiếu class/method với `c4-04b` mục 3, 4, 5, 10, 11, các bất biến ở `c4-04` mục 4.2 và thứ tự bước ở `c4-05`.
2. Ghi một dòng vào bảng mục 1 với trạng thái `Khớp` / `Lệch có lý do` / `Thiếu`.
3. Lệch thì thêm dòng vào mục 2 kèm **lý do kỹ thuật**, và sửa lại plan hoặc `docs/c4-0*` cho khớp.
4. Chạy `make test` và `make docs-check` trước khi sang module kế tiếp.
