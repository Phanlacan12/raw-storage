# ĐỐI SOÁT CODE VỚI THIẾT KẾ

> **Mục đích:** Mỗi module code xong phải đối chiếu với tài liệu thiết kế, ghi lại chỗ khớp, chỗ lệch có lý do và chỗ còn thiếu. Không để lệch âm thầm: lệch thì **hoặc** sửa code, **hoặc** sửa tài liệu, và ghi lý do ngay trong bảng.
> **Trạng thái:** Cập nhật 17/11/2026. `mypy` sạch, `pylint 10.00/10`, **152 test** (6 bỏ qua: 5 test tích hợp cần hạ tầng, 1 test tính duy nhất của biến thể S3 manifest).
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
| B9 | `tests/` | c4-04b mục 13, 14 | **Khớp có khoảng trống** | Xem mục 3: `PolicyDecisionPortContractTest` và `EventPublisherPortContractTest` chưa viết thành bộ riêng |
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

## 3. Còn thiếu và khoảng trống đã biết

| ID | Nội dung | Ảnh hưởng | Xử lý |
|---|---|---|---|
| T1 | **D17 Sync Orchestrator** từng bị bỏ sót: thư mục `adapter/inbound/sync/` chỉ có `__init__.py` | POC-12 không kiểm chứng được | **Đã bổ sung** 17/11/2026: `SourceSyncJob`, `FileSystemSourceConnector`, `SourcePermissionMapper`, `SourceSyncScheduler` + 11 test |
| T2 | `S3ManifestIntentStore` (biến thể A của Q2) từng thiếu, chỉ có sqlite và fake | Q2 không thể chốt bằng số liệu | **Đã bổ sung** cùng ngày và đưa vào contract test |
| T3 | `PolicyDecisionPortContractTest`, `EventPublisherPortContractTest` chưa thành bộ riêng | Hai port này hiện chỉ được phủ gián tiếp qua test use case và API | Viết trước khi tích hợp KB |
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

## 5. Cách cập nhật tài liệu này

1. Xong một module: đối chiếu class/method với `c4-04b` mục 3, 4, 5, 10, 11, các bất biến ở `c4-04` mục 4.2 và thứ tự bước ở `c4-05`.
2. Ghi một dòng vào bảng mục 1 với trạng thái `Khớp` / `Lệch có lý do` / `Thiếu`.
3. Lệch thì thêm dòng vào mục 2 kèm **lý do kỹ thuật**, và sửa lại plan hoặc `docs/c4-0*` cho khớp.
4. Chạy `make test` và `make docs-check` trước khi sang module kế tiếp.
