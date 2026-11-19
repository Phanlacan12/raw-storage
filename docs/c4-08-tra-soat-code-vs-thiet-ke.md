# ĐỐI SOÁT CODE VỚI THIẾT KẾ

> **Mục đích:** Mỗi module code xong phải đối chiếu với tài liệu thiết kế, ghi lại chỗ khớp, chỗ lệch có lý do và chỗ còn thiếu. Không để lệch âm thầm: lệch thì **hoặc** sửa code, **hoặc** sửa tài liệu, và ghi lý do ngay trong bảng.
> **File này là nguồn sự thật duy nhất cho lượt refactor theo [c4-09 LLD](c4-09-lld.md).** Agent sửa code đọc đầu việc ở [mục 2b.1](#2b1-bảng-công-việc); agent đối soát ghi phán quyết vào đó và vào [mục 8](#8-sổ-đối-soát). Giao thức ở [mục 6](#6-giao-thức-đối-soát-bằng-agent). Điều kiện đóng lượt ở [mục 7](#7-ma-trận-đầy-đủ-tính-năng): mọi phần tử C1–C13, D1–D26, I1–I18, POC-01…28 phải có trạng thái, không dòng nào trống.
> **Tiến độ hiện tại, 20/11/2026.** B1–B18 đã nghiệm thu theo các gate ở mục 8. Với Docker và `redis:7.4-alpine` dựng qua `docker compose up -d redis`, toàn suite đạt **347 passed, 5 skipped**: 8 case B17 trước đó skip vì thiếu Redis nay chạy thật và pass, chỉ còn 5 skip của `tests/integration/` chờ OpenMetadata + S3 ở hạ tầng khác. **POC-26 (hai tiến trình cùng duyệt một tài liệu) kiểm chứng đạt** trên Redis thật. B20 đã nghiệm thu (GB20, 20/11) — test kiến trúc viết lại bằng AST, 7 luật, 3 phá xác nhận đỏ. Còn lại: B21, GT, G2.
> **Lượt 3 khác hai lượt trước ở chỗ:** hai lượt đầu đối chiếu code với tài liệu như tài liệu đang có. Lượt này đối chiếu **cả hai** với đề bài, nên tìm ra lỗi ở phía tài liệu (đã sửa, xem [README mục 6](README.md#6-lịch-sử-rà-soát)) và **20 điểm lệch ở phía code** (mục 2b). Vì vậy một số dòng trước đây ghi `Khớp` nay đổi trạng thái: không phải code thay đổi, mà là tiêu chuẩn đối chiếu đã đúng hơn.
> **Ánh xạ module ↔ D1–D18:** [src/README.md](../src/README.md).

## Tiến độ lượt refactor theo LLD

| Bước | Trạng thái hiện tại | Công việc tiếp theo |
|---|---|---|
| B1–B11 | Đã nghiệm thu | Xem từng ID ở mục 2b.1 và từng gate ở mục 8 |
| B12 | Đã nghiệm thu GB12 lần 2 | 312 test qua; cache hết TTL, sai người, proxy và tài liệu mất đều được kiểm |
| B13–B14 | Đã nghiệm thu | 57 test tập trung qua; toàn suite 321 passed, 5 skipped, pylint 10.00/10 |
| B15, B19 | Đã nghiệm thu | 322 passed, 5 skipped; sáu ví dụ chạy thành công |
| B16 | **Đã nghiệm thu (GB16+18, 20/11)** | 332 passed, 5 skipped; upload stream + multipart, source stream từ `Path`, test không parse nội dung |
| B17 | **Đã nghiệm thu (GB17, 20/11) — Redis thật xác nhận 13/13** | `RedisDocumentLock` theo LLD mục 12; contract 5 case × 2 backend + 3 case Redis-specific = 13 pass trên Redis thật; POC-26 đã đạt |
| B18 | **Đã nghiệm thu (GB16+18, 20/11)** | Deadline qua ContextVar không đổi port, hai `OmHttpClient` tách catalog/lineage, bỏ bọc hai lớp, `_VersionIndex` TTL + `forget`, sync key gồm `document_id`, bỏ executor `idp` |
| B20 | **Đã nghiệm thu (GB20, 20/11)** | 7 luật AST ở `TestWritePathRules` (tự phát hiện `WriteUseCase` qua `ast.Subscript`, so thứ tự qua `lineno`, bề mặt 8 ABC, cổng docs↔src ở chế độ warn); `make test` 342 passed/13 skipped (350/5 với `DS_LOCK__REDIS_URL`), pylint 10/10; 3 phá (_record, lifecycle.transition, thứ tự `intents.create`) xác nhận đỏ rồi xanh lại sau revert; luật 7 chạy không phát warning — allow-list đã phủ hết tên lạ |
| B21 | **Đã nghiệm thu (GB21, 20/11)** | X56 D27 thêm + đồng bộ `c4-04b`/`c4-02`/`c4-04`/`c4-09`/`src/README.md`; X57 residue c4-06 dọn ngay; luật 7 strict assert pass | X56 đóng (D27 "Hạ tầng xuyên suốt" có mặt ở `c4-03` mục 3.2, `c4-07` mục 1.4, `src/README.md` mục ánh xạ); mục 16 `c4-09` phản ánh đủ vào `c4-04b` (chữ ký port 5/5, endpoint ghi `Page[AuditEvent]`/`list[RelatedEdge]+direction`/`GET /documents/{id}/versions`/`Idempotency-Key` bắt buộc đều có); `OmPermissionResultFilter` và `ConnectionPool` còn mention ở dạng ghi chú lịch sử (c4-04b:598, :1047); `IdP JWKS executor` đã gỡ khỏi 11.3 (chỉ còn `IdpHealthIndicator` ở mục 10.3 — đúng); luật 7 strict assert pass; `make test` 342/13 (350/5 với Redis); `make docs-check` 0 broken. **Mở X57**: `c4-06-deployment.md:35` vẫn hiển thị `upload_intent` ở node SQLite, phải đổi sang `processing_intent` cho khớp B9a |
| GT, G2 | Chưa thực hiện | Đối soát bất biến → đóng lượt |

Thay đổi trong thư mục tạm được tích hợp và nghiệm thu theo thứ tự của kế hoạch. Trạng thái `Đã sửa` trong mục 2b.1 dành cho các ID đã có kết luận gate.

## 1. Checkpoint theo module

Bảng dưới ghi checkpoint của lượt triển khai nền trước refactor (18/11/2026). Các mã B trong bảng này thuộc lượt nền, **không** trùng với B1–B21 ở bảng tiến độ đầu sổ. Cột **Trạng thái** đã được cập nhật sau lượt refactor theo c4-09: các dòng từng ghi `Lệch` nay là `Khớp sau refactor` với tham chiếu sang ID đã đóng ở mục 2b.1. Nhật ký lệch cũ (L1–L13) giữ ở mục 2.

| # | Module | Phần tử trong docs | Trạng thái | Ghi chú |
|---|---|---|---|---|
| — | *Các bước B1–B21 của lượt refactor theo c4-09 ghi vào đây khi gate tương ứng chạy; trạng thái từng ID ở mục 2b.1* | | | |
| B0 | `configs/*.yml` | c4-04b mục 2 (cấu hình ngoài mã nguồn), mục 11.3 | **Khớp** | 10 file theo khối; thứ tự ưu tiên init → env → `.env` → YAML → mặc định; bí mật chỉ qua env |
| B1 | `config.py`, `utils/`, `infrastructure/container.py`, `main.py` | c4-04b mục 2, 2.1, 2.2 | **Khớp** | `SingletonMeta` dùng `RLock` (xem Lệch L1) |
| B2 | `domain/` | c4-04 mục 4.1–4.3, c4-04b mục 3 | **Khớp sau refactor** | 8 port là ABC; 6 policy kế thừa `DomainPolicy`; I1–I14 có test. X1 đã đóng ở B4 (RelatedEdge), X2 đã đóng ở B2 (bản Draft loại bỏ không ghi `approved_by`), I16 đã đóng ở B4; I15/I17/I18 ngoài phạm vi (D23/D25). Chi tiết ở mục 2b.1 |
| B3 | `application/` | c4-04b mục 6, 7; c4-05 luồng 1, 2 | **Khớp sau refactor** | Lệch L2, L3 vẫn giữ làm nhật ký hiện thực. X3 đã đóng ở B9 (intent `StatusChangePending` + `StatusChangeSaga`), X4 đã đóng ở B7 (audit from→to), X5 đã đóng ở B6 (checksum đọc lại từ storage). Chi tiết ở mục 2b.1 |
| B4 | `infrastructure/resilience/` | c4-04b mục 11.1–11.5 | **Khớp** | `BackoffStrategy` → `FullJitterBackoff`/`FixedBackoff`; một executor cho mỗi phụ thuộc |
| B5 | `adapter/outbound/openmetadata/` | c4-04b mục 4, 5, 8, 9 | **Khớp, chưa xác minh trên bản thật** | Đường dẫn API theo bảng mục 5; test bằng respx + fake server có routes lineage (B5 thêm). `OmLineageRelationshipStore` đã vào contract parametrize (X39 đóng). Vẫn phải đối chiếu OpenAPI của bản OpenMetadata thật trong POC-19 |
| B6 | `adapter/outbound/` còn lại | c4-04b mục 9, 10.3, 11.6 | **Khớp** | 3 hiện thực intent store; `PresignedUrlIssuer`/`ProxyStreamer` tách riêng; `MetricsRecorder` theo mục 11.7 |
| B6b | Health ở lớp outbound | c4-04b mục 10.2 | **Khớp** | `HealthProbe` ở `infrastructure/health.py`; mỗi adapter hiện thực `_probe_dependency()`; xem Lệch L4 |
| B7 | `adapter/inbound/` | c4-04b mục 10.4, 12 | **Khớp sau refactor** | X6 đã đóng ở B8 (`/status` dùng `WriteCtx`), X7 đã đóng ở B16 (upload stream + multipart), X10 đã đóng ở B14 (`Page[T]` + con trỏ cho audit và relationships), X47 đã đóng ở B14 (endpoint `/documents/{id}/versions`). Nhóm endpoint của D23/D24/D25 vẫn ngoài phạm vi (đã chốt). Chi tiết ở mục 2b.1 |
| B8 | `worker/reconcile.py` | c4-04b mục 7; c4-05 luồng 7 | **Khớp** | `IntentRecoveryJob`, `OrphanObjectScanner`, `DanglingEntityScanner`, CLI |
| B6c | Outbox dispatcher | c4-02 C10, c4-04b mục 11.7; POC-11 | **Khớp sau refactor** | `SqliteOutbox` + `OutboxEventPublisher` + `WebhookEventSender` + `OutboxDispatcher` đã tách 3 file ở B1; `worker/dispatch.py` là tiến trình chạy chu kỳ (X8 đóng ở B15). B1 cũng tách `outbox` và `audit` thành hai executor riêng khỏi `intent_store` |
| B9 | `tests/` | c4-04b mục 13, 14 | **Khớp** | Đủ 6 bộ contract test: catalog (fake + OpenMetadata qua server giả lập), relationship, intent (3 hiện thực), object store (fake + moto), policy decision, event publisher |
| B9b | `examples/` | plan B9b | **Khớp** | 6 ví dụ không cần hạ tầng + 1 ví dụ cần hạ tầng tự in hướng dẫn; `make examples` chạy tuần tự |
| B10 | `deploy/`, `.github/workflows/` | c4-06 mục 6.1, 6.5 | **Khớp sau khi sửa tài liệu** | compose có healthcheck; CI theo khuôn repo mẫu, thêm cổng kiểm tra sơ đồ mermaid. Trước 19/11 sơ đồ 6.1 vẽ `document-service`, `reconciler`, `intent-store`, `mock-downstream` như container compose trong khi compose chỉ có 4 container hạ tầng — **tài liệu sai, không phải code sai**, đã sửa. Còn thiếu thật: IdP thử nghiệm (PoC đang dùng `AUTHENTICATION_PROVIDER=basic`, POC-04 chưa chạy được) và mock downstream (POC-11) |

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


## 2b. Sổ công việc — lệch giữa code và thiết kế

Đây là **nguồn sự thật duy nhất** cho lượt refactor theo [c4-09 LLD](c4-09-lld.md). Agent sửa code đọc bảng này (lọc theo cột `Bước`); agent đối soát ghi vào nó. Giao thức ở [mục 6](#6-giao-thức-đối-soát-bằng-agent).

**Trạng thái hợp lệ — chỉ năm giá trị, không mô tả tự do:**

`Chưa sửa` → `Đang sửa (Bx)` → `Chờ đối soát (Bx)` → `Đã sửa (Bx, GBx)`, hoặc bị gate bác về `Chưa sửa`.

**Quy ước tên gate:** `G0`/`G1` là hai gate của Phần A (LLD ↔ C4, LLD ↔ code nền); `GB1`…`GB21` là gate của từng bước refactor; `GT` là gate test ↔ bất biến; `G2` là gate đối soát bốn chiều đóng lượt. Giá trị thứ năm là `Ngoài phạm vi (đã chốt)`, chỉ dùng cho những gì người dùng đã quyết hoãn.

**Chỉ agent đối soát được ghi `Đã sửa`.** Agent sửa code chỉ được chuyển sang `Chờ đối soát`.

### 2b.1. Bảng công việc

| ID | Nhóm | Vấn đề | Bước | Trạng thái | Bằng chứng | Gate |
|---|---|---|---|---|---|---|
| X1 | 1 | Quan hệ chiều vào bị đảo hai đầu cạnh; response không có `direction` | B4 | Đã sửa (B4, GB4) | `lineage.py:151`, `test_relationship_store_contract.py:50–53` | GB4 |
| X2 | 1 | `mark_obsolete` ghi `approved_at`/`approved_by` cả khi loại bỏ bản Draft | B2 | Đã sửa (B2, GB2) | `model.py:143` lưu riêng người và lúc loại bỏ. `test_invariants.py:320` và `test_catalog_contract.py:173–177` kiểm đọc lại cả entity cũ thiếu trường. | GB2 |
| X3 | 1 | Lượt duyệt không có intent `StatusChangePending`; lỗi giữa đường để lại hai bản `Approved` | B9a, B9b, B9c | Đã sửa (B9, GB9) | `status_change_saga.py:83`, `test_invariants.py:369` kiểm lỗi PATCH thứ hai, lỗi audit sau commit và replay sau lượt duyệt mới | GB9a, GB9b, GB9c |
| X4 | 1 | Audit chuyển trạng thái thiếu trạng thái **trước** | B7 | Đã sửa (B7, GB7) | `approve_version.py:99` và `:106` ghi trước/sau. `test_invariants.py:245,300,325` kiểm ba chuyển trạng thái và phiên bản bị thay thế. | GB7 |
| X5 | 1 | Checksum không được đối chiếu với giá trị đọc lại từ storage | B6 | Đã sửa (B6, GB6) | `application/orchestration/upload_saga.py:93`, `tests/unit/test_reconcile.py:150`, `tests/contract/test_object_store_contract.py:104` | GB6 |
| X6 | 1 | `POST /versions/{id}/status` dùng `ReadCtx` nên không bắt `Idempotency-Key` | B8 | Đã sửa (B8, GB8) | `routes.py:148`, `test_api_flow.py:68` và `:76` | GB8 |
| X7 | 2 | Upload buffer toàn bộ file trong RAM ở hai lớp; không multipart | B16 | Đã sửa (B16, GB16) | `upload_handler.py:103` dùng `SpooledUploadBody`; `s3_store.py:107` chia hai nhánh `_put_small`/`_put_multipart`; `s3_store.py:170` abort trong `except`; `test_upload_handler.py:64` chứng không có `payload` bytes | GB16 |
| X8 | 2 | Không tiến trình nào gọi `OutboxDispatcher.run_once()` | B15 | Đã sửa (B15, GB15) | `worker/dispatch.py:32`, `test_event_publisher_contract.py:232` kiểm vòng lặp và đóng sender | GB15 |
| X9 | 2 | Chỉ có khóa trong tiến trình; chạy nhiều instance là mất I4/I5 | B17 | Đã sửa (B17, GB17) | `redis_lock.py:53` `class RedisDocumentLock(DocumentLockPort, OutboundAdapter)` + `DependencyKind.REQUIRED_FOR_WRITE` ở `redis_lock.py:66`; Lua CAS-extend/CAS-release `redis_lock.py:34-41` + `register_script` ở `redis_lock.py:76-77`; token `UlidGenerator().new_id(prefix="LCK")` `redis_lock.py:85`; mất lease → `asyncio.wait(..., FIRST_COMPLETED)` + `op_task.cancel()` + `ConcurrencyConflictError` `redis_lock.py:98-111`; nhả khóa Lua CAS trong `finally` qua `_release_key` `redis_lock.py:113-118` + `_release_key` dùng Lua script `redis_lock.py:135-142`; health chỉ `PING` không bọc `_call`, URL cắt password `redis_lock.py:144-150`; contract test 5 case × 2 param `tests/contract/test_document_lock_contract.py` (in_memory xanh, redis skip) | GB17 |
| X10 | 2 | `GET .../relationships` và `.../audit` không phân trang | B14 | Đã sửa (B14, GB14) | `test_relationship_store_contract.py:106`; kiểm độc lập đường HTTP và contract | GB14 |
| X11 | 2 | `SearchPage.filtered` đặt `total_hits` thành số phần tử của trang | B3 | Đã sửa (B3, GB3) | `dto.py:121`, `schemas.py:193`. Các assert ở `test_search_page.py:23–25` giữ tổng 17 và cursor, kiểm số hiển thị 0 hoặc 1. | GB3 |
| X12 | 3 | D23 Metadata Schema & Validation chưa có | — | Ngoài phạm vi (đã chốt) | [c4-09 mục 2.2](c4-09-lld.md#22-lớp--file--thành-phần--bất-biến) | — |
| X13 | 3 | D24 Collection Manager chưa có; `ensure_collection` không có người gọi | B13 (một phần) | Đã sửa (B13, GB13) | `test_catalog_contract.py:261`; kiểm độc lập đường HTTP và contract | GB13 |
| X14 | 3 | D25 Retention & Deletion chưa có | — | Ngoài phạm vi (đã chốt) | [c4-09 mục 2.2](c4-09-lld.md#22-lớp--file--thành-phần--bất-biến) | — |
| X15 | 3 | Provenance `MetadataSource`/`MetadataChange` chưa có | — | Ngoài phạm vi (đã chốt) | [c4-09 mục 13](c4-09-lld.md#13-bất-biến-i1i18--lớp--test) | — |
| X16 | 3 | `FILTERABLE_FIELDS` thiếu `owner` và khả năng tìm theo tên; POC-02 sẽ trượt dù `assert_filterable` pass | B13 | Đã sửa (B13, GB13) | `test_catalog_contract.py:269`; kiểm độc lập đường HTTP và contract | GB13 |
| X17 | 4 | `changed_unexpectedly` so `<` nên chỉ phát hiện version tụt | B12 | Đã sửa (B12, GB12) | `src/document_service/adapter/outbound/openmetadata/entity.py:312`, `tests/unit/test_health.py:241` (version giảm, bằng và tăng) | GB12 |
| X18 | 4 | Nhánh `FAILED` của `IdempotencyGuard` không bao giờ tới đích vì `UNIQUE` chặn | B10 | Đã sửa (B10, GB10) | `idempotency.py:46`, `test_invariants.py:228` | GB10 |
| X19 | 4 | `register_document` không kiểm tra collection tồn tại | B13 | Đã sửa (B13, GB13) | `test_invariants.py:658`; kiểm độc lập đường HTTP và contract | GB13 |
| X20 | 4 | `document_id` qua query param chưa có trong hợp đồng API | — | Đã sửa (tài liệu) | [c4-09 mục 10](c4-09-lld.md#10-hợp-đồng-api-công-khai) | — |
| X21 | 4 | `CachingPolicyDecision.invalidate` không được gọi từ code production | B11 | Đã sửa (B11, GB11) | `access_policy.py` gọi invalidate sau patch; `test_policy_decision_contract.py:249` | GB11 |
| X22 | 2 | Hai adapter OpenMetadata không dùng `_call`; executor `relationship_store` không thấy traffic nên breaker vô nghĩa | B18 | Đã sửa (B18, GB18) | `container.py:222,231` dựng hai `OmHttpClient` riêng cho `catalog` và `relationship_store`; `lineage.py:120` adapter nhận executor `relationship_store`; `lineage.py:128,155,177,185` gọi `_call` cho mọi edge | GB18 |
| X23 | 2 | `S3ManifestIntentStore` bọc executor hai lần; retry nhân nhau | B18 | Đã sửa (B18, GB18) | `s3_manifest_store.py:148-156` không còn `_call`; chỉ ủy nhiệm `self._objects.put_overwrite/put_immutable` (nơi retry duy nhất) | GB18 |
| X24 | 1 | `adapter/outbound` import `document_service.application`; test kiến trúc không có luật chặn chiều này | B1 | Đã sửa (B1, GB1) | Hai adapter dùng `domain.metadata_builder` (`catalog_adapter.py:30`, `in_memory.py:25`). Ba biến thể import sai đều làm assert ở `test_architecture_rules.py:101` đỏ. | GB1 |
| X25 | 2 | `request_budget_seconds` không ai đọc; deadline không lan truyền từ inbound | B18 | Đã sửa (B18, GB18) | `deadline.py:66-82` ContextVar + set/reset; `executor.py:94` đọc `get_current_deadline()` khi `deadline=None`; `main.py:46-50,74-77` middleware set/reset mỗi request theo `app.request_budget_seconds`; chữ ký 8 port không đổi; `test_resilience.py:231` chứng picks up | GB18 |
| X26 | 4 | `events`, `audit`, `policies` không có health indicator dù là `HealthProbe` | B12 | Đã sửa (B12, GB12) | `infrastructure/container.py:262`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X27 | 4 | `IdpHealthIndicator(jwks_available=True)` hard-code, không nối với `OidcTokenVerifier` | B12 | Đã sửa (B12, GB12) | `adapter/inbound/security/auth.py:42`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X28 | 2 | `InMemoryDocumentLock` dùng cho cả profile `openmetadata` và khai `REQUIRED_FOR_WRITE` nên readiness luôn báo khóa khỏe | B17 | Đã sửa (B17, GB17) | `container.py:209-213` `_build_locks(self) -> DocumentLockPort` chọn theo `self._settings.lock.kind` (không theo `app.profile`); dùng ở `_build_fake_ports` `container.py:225` và `_build_real_ports` `container.py:267`; `InMemoryDocumentLock.__init__(settings: LockSettings | None)` `in_memory.py:541` để `acquire_timeout_seconds` khớp Redis; executor `document_lock` đăng ký `container.py:189` với `resilience.lock` | GB17 |
| X29 | 1 | `ReadinessPolicy._all_up` trả `True` cho nhóm rỗng; thiếu indicator nhóm ghi vẫn cho `FULL` | B12 | Đã sửa (B12, GB12) | `adapter/inbound/health/registry.py:48`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X30 | 1 | `ApprovalResult.approved` chứa bản vừa bị Obsolete ở nhánh obsolete | B2 | Đã sửa (B2, GB2) | `model.py:239` trả phiên bản thay đổi. `test_invariants.py:316–318` kiểm nhánh loại Draft và trường obsoleted rỗng. | GB2 |
| X31 | 1 | `idempotency_key` của sync không có `document_id`; hai tài liệu cùng nội dung bị coi là replay của nhau (phá I9) | B18 | Đã sửa (B18, GB18) | `source_sync.py:288` khóa = `f"sync-{document_id}-{checksum[:16]}"`; `test_source_sync.py:186` chứng hai tài liệu cùng nội dung → 2 phiên bản | GB18 |
| X32 | 2 | `FileSystemSourceConnector.discover` đọc toàn bộ file vào RAM | B16 | Đã sửa (B16, GB16) | `source_sync.py:53` `SourceFile.path: Path`; `source_sync.py:130-157` `discover()` không gọi `read_bytes`; `source_sync.py:292-301` stream_factory mở `path.open("rb")` theo chunk | GB16 |
| X33 | 2 | `SourceSyncScheduler.run_forever` không bắt exception ngoài `DomainError`; vòng lặp chết im lặng | B18 | Đã sửa (B18, GB18) | `source_sync.py:326-331` `while True` bắt `Exception` + log; `CancelledError` vẫn thoát (là `BaseException`); `test_source_sync.py:220` inject RuntimeError rồi CancelledError, chứng loop sống qua lỗi lạ | GB18 |
| X34 | 4 | `_VersionIndex` cache không TTL, không invalidation | B18 | Đã sửa (B18, GB18) | `lineage.py:55-75` có `ttl_seconds`+`Clock`+`expires_at`; `lineage.py:76` `forget()`; `lineage.py:188-189` `remove()` gọi `forget` cho cả hai endpoint; `test_lineage_cache.py:41,65` kiểm TTL expiry + forget | GB18 |
| X35 | 4 | Sáu knob chết: `app.request_budget_seconds`, `app.service_name`, `storage.multipart_threshold_bytes`, `relationship.sqlite_path`, `security.lock_timeout_seconds`, `health.cache_ttl_seconds` + `health.startup_deadline_seconds` | B12, B16, B17, B18, pre-G2 | Chờ đối soát (G2) | **Mọi knob đã nối**: GB12 nối `cache_ttl_seconds` ở `container.py:300` + `startup_deadline_seconds` ở `main.py:88`. B16/B18 nối `request_budget_seconds` (ContextVar deadline `executor.py:94` + middleware `main.py`), `multipart_threshold_bytes`/`multipart_part_bytes`/`max_upload_bytes` qua đường upload stream. B17 bỏ `security.lock_timeout_seconds`. Trước G2: `app.service_name` nối vào FastAPI title `main.py:69`; `relationship.sqlite_path` nối `container.py:234-237` (dựng `SqliteDatabase` riêng nếu path khác `intent.sqlite_path`) | G2 |
| X36 | 4 | `SettingsProvider` thiếu `reset()`, lệch quy tắc R2 | B1 | Đã sửa (B1, GB1) | `config.py:304` xóa cache, lần đọc kế nạp lại; `test_singleton_and_config.py:136` bắt trường hợp reset vô hiệu | GB1 |
| X37 | 4 | `src/README.md` dòng D14 trỏ sai file | B1 | Đã sửa (B1, GB1) | Đối chiếu D14 ở `src/README.md:41` với định nghĩa `outbox_publisher.py:17`, `outbox_store.py:44`, `outbox_dispatcher.py:105` | GB1 |
| X38 | 4 | `HealthCheckRegistry.details()` chỉ gọi lại `readiness()`; bốn trường của `health` không được truyền vào registry | B12 | Đã sửa (B12, GB12) | `adapter/inbound/health/registry.py:92`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X39 | 1 | `OmLineageRelationshipStore` không có test nào chạy nó, dù nó quyết định Q4 | B5 | Đã sửa (B5, GB5) | `tests/contract/conftest.py:67`, `test_relationship_store_contract.py:43` | GB5 |
| X40 | 4 | Test kiến trúc kiểm bằng substring và danh sách hard-code nên giòn | B20 | Đã sửa (B20, GB20) | `tests/unit/test_architecture_rules.py:261` (`_discover_write_use_cases` xử lý `ast.Subscript`), `:314,325,335,344,353,388,404` (7 luật AST); `_dotted_path` thay `source.index`/substring; 3 kịch bản phá (_record, lifecycle.transition, thứ tự `intents.create`) đều ra đỏ rồi xanh lại sau revert | GB20 |
| X41 | 1 | **Không phát `DomainEvent` nào khi `access_policy` đổi**; cũng không có `document.created`. Đề bài mục 2.5 và 2.6 là Bắt buộc, `c4-05` luồng 5 yêu cầu `access.changed`, `c4-02` liệt kê "thay đổi quyền, thu hồi" trong phạm vi C10. Code chỉ phát `version.created` và `version.{status}` | B11 | Đã sửa (B11, GB11) | `test_policy_decision_contract.py:257` kiểm đúng một document.created và access.changed | GB11 |
| X42 | 1 | **Ba endpoint ghi bắt buộc `Idempotency-Key` rồi bỏ đi**: `POST /documents`, `POST /relationships`, `PATCH access-policy`. Chỉ `CreateVersionUseCase` dùng khóa, nên I13 ("duy nhất toàn cục cho mọi API ghi") không được thực thi cho ba endpoint còn lại | B9a | Đã sửa (B9a, GB9a) | `command_receipt.py:48–69` kiểm kind, fingerprint, trạng thái và nhận khóa trước khi ghi. `test_api_flow.py:177` kiểm cả ba endpoint, replay, xung đột giữa hai thao tác và số lần audit. | GB9a |
| X43 | 1 | `IdempotencyGuard.inspect` chạy **trước** `_authorize_write`: chủ thể không có quyền ghi vẫn nhận được snapshot phiên bản khi replay, và nhận `409` khi khóa đã `Failed` — cả hai đường không kiểm quyền và không ghi audit denied | B10 | Đã sửa (B10, GB10) | `create_version.py:78`, `test_invariants.py:214` | GB10 |
| X44 | 1 | `IntentRecoveryJob` và `StatusChangeSaga.resume` ghi trường kiểm soát (`status`, `current_version_id`) **không qua khóa document**; một lượt phục hồi chạy song song một lượt duyệt mới trên cùng tài liệu có thể phá I4/I5 | B9c | Đã sửa (B9c, GB9c) | `worker/reconcile.py` lấy khóa và đọc lại intent; `test_invariants.py:450` kiểm lock và bản Approved duy nhất | GB9c |
| X45 | 1 | `HealthResult.kind` là **một** giá trị nên không biểu diễn được phụ thuộc thuộc hai nhóm (catalog = WRITE + READ, S3 = WRITE + DOWNLOAD theo `c4-04b` mục 10.3); và nhánh `READ_ONLY` đòi `download_ready` nên **S3 DOWN cho `NOT_READY`** thay vì `READ_ONLY`, trái `c4-04b` mục 10.4 | B12 | Đã sửa (B12, GB12) | `infrastructure/health.py:59`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X46 | 2 | `DOWNLOAD_ONLY` thiếu điều kiện của I11: `c4-04b` mục 10.4 chốt chỉ bật khi policy cache còn TTL và tài liệu không thuộc `require_proxy_download`, hết TTL thì `NOT_READY` thay vì đoán quyền | B12 | Đã sửa (B12, GB12) | `adapter/outbound/policy/policy_decision.py:133`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X47 | 2 | **Không có endpoint liệt kê phiên bản của một tài liệu**; `DocumentResponse` chỉ trả `version_count`, nên không truy xuất được metadata bản `Obsolete` qua API — trái đề bài mục 2.4. `list_versions` đã có và được dùng nội bộ, chỉ thiếu đường ra API | B14 | Đã sửa (B14, GB14) | `test_api_flow.py:231`; kiểm độc lập đường HTTP và contract | GB14 |
| X48 | 4 | `DuplicateContentError` được map sang **`200`** (`errors.py:34`) — một lỗi trả 200 kèm body lỗi; và `DedupPolicy.assert_not_duplicate` **không có người gọi nào** | B10 | Đã sửa (B10, GB10) | `http/errors.py:36`, `test_api_flow.py:223` | GB10 |
| X49 | 4 | `SchemaNotReadyError` không có trong `STATUS_BY_ERROR` nên nhận `400`, trong khi nó nghĩa là service chưa sẵn sàng — phải là `503` | B10 | Đã sửa (B10, GB10) | `http/errors.py:37`, `test_api_flow.py:224` | GB10 |
| X50 | 2 | Executor `idp` được đăng ký (`container.py:185`) mà **không ai `get("idp")`**; `OidcTokenVerifier` không nhận executor nào, nên cả khối `resilience.idp` vô tác dụng. Vi phạm L-EX1 lần thứ hai | B18 | Đã sửa (B18, GB18) | `container.py:186-197` không còn `register("idp", ...)`; `configs/resilience.yml` không còn khối `idp:`; `config.py` không còn trường `idp` trong `ResilienceSettings`; `IdpHealthIndicator` vẫn hoạt động (`container.py:285`, `indicators.py:44`) không cần executor | GB18 |
| X51 | 2 | `SourceSyncScheduler.run_forever` **không có tiến trình nào gọi**; `container.source_sync_scheduler()` không ai dùng, nên `sync.enabled` là knob chết trên thực tế. Cùng họ với X8 | B15 | Đã sửa (B15, GB15) | `worker/dispatch.py:32`, `test_event_publisher_contract.py:232` kiểm vòng lặp và đóng sender | GB15 |
| X52 | 4 | `OutboxEventPublisher` và `StructuredAuditLogger` nhận executor `intent_store` nên `dependency_name` của cả hai là `"intent_store"`; đăng ký health cho `events`/`audit`/`intents` sẽ cho **ba indicator trùng tên** | B12 | Đã sửa (B12, GB12) | `infrastructure/container.py:262`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X53 | 2 | `SearchParams` có field `page_size`/`cursor` nhưng `SearchParamsProvider.__call__` không nhận chúng từ query string, nên **phân trang `/search` không tồn tại trên API** | B14 | Đã sửa (B14, GB14) | `test_api_flow.py:237`; kiểm độc lập đường HTTP và contract | GB14 |
| X54 | 4 | `InMemoryAuditLog` và `AllowAllPolicyDecision` không kế thừa `InMemoryAdapter` nên không là `HealthProbe`; khi B12 đăng ký health cho `events`/`audit`/`policies` thì profile `fake` sẽ thiếu đúng hai indicator so với profile thật | B12 | Đã sửa (B12, GB12) | `adapter/outbound/fake/in_memory.py:494`; `tests/unit/test_health.py:209`, `tests/unit/test_cached_download.py:28`; đường HTTP và hết TTL ở cùng file | GB12 |
| X55 | 3 | Nửa thuộc **D4** của I15 — "tự động trích xuất **chỉ** gồm metadata kỹ thuật, không đọc nội dung tài liệu" (đề bài mục 2.3, `c4-03` D4) — nằm **trong** phạm vi nhưng không ai nhận và không có test | B16 | Đã sửa (B16, GB16) | `upload_handler.py:78` comment "Không gọi thư viện đọc nội dung"; `grep pypdf\|python_magic\|tika\|pdfplumber src/` rỗng; `test_upload_handler.py:88,105` assert `UploadRequest` không có `pages`/`author`/`title_from_content`/`text`/`extracted_text` | GB16 |
| X56 | 4 | `c4-03`/`c4-07` **không có thành phần nào làm cha** cho toàn bộ lớp `infrastructure` (`ServiceContainer`, `ExecutorRegistry`, resilience, health). Đề xuất thêm **D27 Hạ tầng xuyên suốt** | B21 | **Đã sửa (B21, GB21)** | D27 có mặt: `c4-03-component-document-service.md:192` (bảng 3.2), `c4-07-element-catalog.md:77` (mục 1.4), `src/README.md:54` (ánh xạ `infrastructure/container.py`, `infrastructure/health.py`, `infrastructure/resilience/`, `adapter/inbound/health/`); mục 16 `c4-09` phản ánh vào `c4-04b` (xem GB21 ở mục 8); luật 7 strict assert pass | G2 |
| X57 | 4 | `c4-06-deployment.md:35` node SQLite C7 vẫn liệt kê `upload_intent` thay vì `processing_intent` (B9a đổi tên bảng); mâu thuẫn với `c4-09:1381` và `c4-04` | B21 mở lại hoặc gộp vào GT | Đã sửa (B21, GB21) | `docs/c4-06-deployment.md:35` node N6 SQLite đổi `upload_intent` → `processing_intent`; residue rename đã dọn ngay sau GB21 báo (fix inline, không gate riêng) | GT |

**Phân bổ theo bước** — dùng để mở một bước:

| Bước | ID nhận xử lý |
|---|---|
| B1 | X24, X36, X37 |
| B2 | X2, X30 |
| B3 | X11 |
| B4 | X1 |
| B5 | X39 |
| B6 | X5 |
| B7 | X4 |
| B8 | X6 |
| B9a–B9c | X3, X42 (B9a), X44 (B9c) |
| B10 | X18, X43, X48, X49 |
| B11 | X21, X41 |
| B12 | X17, X26, X27, X29, X38, X45, X46, X52, X54, X35 (một phần) |
| B13 | X13 (một phần), X16, X19 |
| B14 | X10, X47, X53 |
| B15 | X8, X51 |
| B16 | X7, X32, X55, X35 (một phần) |
| B17 | X9, X28, X35 (một phần) |
| B18 | X22, X23, X25, X31, X33, X34, X50, X35 (một phần) |
| B19 | — (dọn `examples/run_all.py`) |
| B20 | X40 |
| B21 | X56 + đồng bộ tài liệu |

> **Chỉnh so với plan được duyệt:** plan không gán X26, X27, X29, X30, X38 vào bước nào. X30 vào **B2** (cùng chỗ với `TransitionResult`), bốn ID còn lại vào **B12**, nên B12 từ "sửa guard" thành "guard + health nói thật". Không ID nào bị bỏ.

### 2b.2. Chi tiết từng ID

### Nhóm 1 — sai dữ liệu hoặc mất bất biến. Phải sửa trước khi chạy PoC lấy số liệu

| ID | Thiết kế nói | Code làm | Hệ quả | Nơi sửa |
|---|---|---|---|---|
| **X1** | Truy vấn quan hệ hai chiều trả kèm `direction`, **giữ nguyên** hai đầu cạnh (I16, [c4-05 luồng 4](c4-05-dynamic-views.md#4-kb-tiêu-thụ-bản-approved)) | `query()` với chiều vào gọi `reversed_direction()`: đảo `source`/`target` và giữ nguyên `relation_type`. `RelationshipResponse` **không có** trường `direction` | Truy vấn SRS v2.0 trả về `derived_from: source=SRS v2.0, target=SAD v1.1` — một quan hệ **chưa từng được khai báo**. KB sẽ lưu nó làm nguồn sự thật. POC-06 và POC-09 sẽ được tính là "đạt" trong khi dữ liệu trả ra sai | `domain/model.py` `reversed_direction`, `adapter/outbound/relationship/sqlite_registry.py:60`, `adapter/outbound/openmetadata/lineage.py`, `adapter/inbound/http/schemas.py:138` |
| **X2** | `approved_at`/`approved_by` chỉ ghi khi phiên bản thực sự được duyệt ([c4-04 mục 4.4](c4-04-code-data-model.md#44-nhóm-metadata-và-vị-trí-gắn)) | `mark_obsolete()` ghi `approved_by = approved_by or actor` và `approved_at` kể cả khi chuyển từ `Draft` | Một bản nháp bị loại bỏ sẽ mang metadata nói rằng nó đã được duyệt, bởi chính người loại bỏ nó. Sai dữ liệu lặng lẽ, không có lỗi nào được phát ra | `domain/model.py` `DocumentVersion.mark_obsolete` |
| **X3** | Lượt duyệt ghi intent `StatusChangePending` trước ba lệnh `PATCH`, để job phục hồi hoàn tất lại ([c4-04b mục 7](c4-04b-code-structure.md#7-luồng-gọi-ở-mức-lớp--duyệt-phiên-bản)) | `ApproveVersionUseCase._transition` gọi ba `patch` liên tiếp, **không** ghi intent. `IntentState.STATUS_CHANGE_PENDING` có trong enum nhưng **không nơi nào dùng** | Lỗi ở lệnh thứ hai để lại **hai bản `Approved`** trong catalog cho tới lượt đối soát kế tiếp — mất I4/I5 trong khoảng giữa hai lượt. Đúng tình huống POC-10/22 phải kiểm chứng | `application/usecase/approve_version.py`, `worker/reconcile.py` |
| **X4** | Audit chuyển trạng thái có **cả** trạng thái trước và sau (I12, c4-03 D7, c4-05 luồng 2) | `AuditOutcome.ok(f"-> {status}")`: chỉ trạng thái đích | Không trả lời được câu hỏi lịch sử phát hành của POC-14. Không biết một bản đi từ `Draft` hay từ `Approved` sang `Obsolete` | `application/usecase/approve_version.py` |
| **X5** | Sau khi ghi object, **đọc lại** checksum từ storage và đối chiếu trước khi chốt `Completed` (I10, [c4-05 luồng 1](c4-05-dynamic-views.md#1-upload-và-đăng-ký-phiên-bản)) | `put_immutable` trả `checksum=checksum` — chính giá trị client khai báo. Nhánh `already_existed` cũng trả lại giá trị đó mà không so sánh với object đang có. `UploadSaga._store_object` bỏ qua `PutResult` | I10 không được kiểm tra ở bất kỳ đâu. Một object hỏng hoặc một object cũ cùng key sẽ được đăng ký như hợp lệ | `adapter/outbound/storage/s3_store.py:58`, `application/orchestration/upload_saga.py` |
| **X6** | Mọi API ghi yêu cầu `Idempotency-Key` ([c4-04b mục 12](c4-04b-code-structure.md#12-hợp-đồng-api-công-khai-của-document-service), c4-03 D1) | `POST /versions/{id}/status` khai `ctx: ReadCtx`, nên **không** đi qua `require_idempotency_key` | Client retry một lượt duyệt khi mạng chập sẽ chạy lại toàn bộ chuyển trạng thái. Đây là endpoint bảo vệ I4/I5, tức đúng chỗ cần idempotency nhất | `adapter/inbound/http/routes.py:150` |

### Nhóm 2 — chặn triển khai thật

| ID | Thiết kế nói | Code làm | Hệ quả | Nơi sửa |
|---|---|---|---|---|
| **X7** | Upload đi theo stream, multipart, **không giữ toàn bộ file trong bộ nhớ** ([c4-04b mục 11.6](c4-04b-code-structure.md#116-kết-nối-và-cấu-hình-pool), c4-03 D4) | Buffer toàn bộ ở **hai** lớp: `UploadHandler` gom `b"".join(chunks)`, rồi `put_immutable` gom lại `b"".join([chunk async for chunk in stream])` | RAM của service tỷ lệ với kích thước file nhân số request đồng thời. Một file 2 GB và 5 upload song song là hết bộ nhớ. Không đo được tài nguyên ở [c4-06 mục 6.3](c4-06-deployment.md#63-tài-nguyên-tham-khảo) cho tới khi sửa. Test case POC-28 | `adapter/inbound/http/upload_handler.py:88`, `adapter/outbound/storage/s3_store.py:70` |
| **X8** | C10 là một tiến trình đọc outbox và phát sự kiện ([c4-02](c4-02-container.md), c4-03 D26) | `OutboxDispatcher.run_once()` có đủ và có test, nhưng **không có CLI, scheduler hay `run_forever`** gọi nó. `ServiceContainer.outbox_dispatcher` chỉ dựng đối tượng | Sự kiện được ghi vào `outbox_event` và nằm lại vô thời hạn. Downstream không nhận gì. **POC-11 không thể đạt** cho tới khi có tiến trình chạy nó | thêm entrypoint kiểu `worker/dispatch.py` + target trong `Makefile` |
| **X9** | Từ 2 instance C1 trở lên **bắt buộc** có C13 (Q12, [c4-06 mục 6.5](c4-06-deployment.md#65-yêu-cầu-vận-hành-theo-vùng-triển-khai)) | Chỉ có `InMemoryDocumentLock` trong tiến trình | Hiện tại **chỉ được phép chạy một instance**. Trước đây điều này được ghi là "ngoài phạm vi" (T4); nay nó là một ràng buộc triển khai phải nằm trong tài liệu vận hành, vì chạy 2 instance là mất I4/I5 mà không có lỗi nào báo | `adapter/outbound/` thêm adapter khóa; hoặc ghi rõ giới hạn 1 instance trong hướng dẫn triển khai |
| **X10** | Mọi API danh sách phân trang theo con trỏ (c4-04b mục 12) | `GET /versions/{id}/relationships` và `GET /documents/{id}/audit` trả `list[...]` thuần | Một tài liệu có nhiều nghìn bản ghi audit sẽ trả một response khổng lồ. POC-14 và POC-16 sẽ gặp ngay | `adapter/inbound/http/routes.py`, `domain/port.py` `AuditPort.list_for_document` |
| **X11** | `SearchPage.total_hits` là tổng số kết quả khớp | `filtered()` đặt `total_hits=len(allowed)` — số phần tử của **trang hiện tại sau khi lọc** | `total_hits` đổi theo từng trang, và một trang có thể trả rỗng kèm `next_cursor` khác null. Client không phân trang đúng được | `domain/dto.py:113` |

### Nhóm 3 — phần tử thiết kế chưa hiện thực

Đây là hệ quả của việc bổ sung phần tử cho các yêu cầu "Bắt buộc" ở chương II báo cáo. Không phải code làm sai, mà là **chưa làm**; ghi ra để không bị tính là đã có.

| ID | Phần tử | Trạng thái code | Test case |
|---|---|---|---|
| **X12** | **D23 Metadata Schema & Validation** | Chưa có. `domain/metadata_fields.py` là một danh sách **global**, không theo `document_type`; không có bước validate trường bắt buộc khi tạo phiên bản. `OmCustomPropertyRegistrar.assert_filterable` chỉ kiểm tra property đã đăng ký ở catalog | POC-19, 24 (I18) |
| **X13** | **D24 Collection Manager** | `ensure_collection` có trong `MetadataCatalogPort` và cả hai adapter, nhưng **không nơi nào gọi**: không use case, không endpoint, không ví dụ. Collection hiện chỉ tồn tại như một giá trị `extension.collection_id` | POC-05, 27 |
| **X14** | **D25 Retention & Deletion Manager** | Chưa có. Không có endpoint `DELETE`, không có job retention. `retention_policy` chỉ là một trường được lưu và đọc lại. [c4-05 luồng 5](c4-05-dynamic-views.md#5-thu-hồi-quyền-và-xóa-tài-liệu-đã-cấp) và [luồng 8](c4-05-dynamic-views.md#8-hết-retention-và-xóa-vật-lý) chưa có đường code tương ứng | POC-11, 15, 25 (I17) |
| **X15** | **Provenance metadata** (`MetadataSource`, `MetadataChange`) | Chưa có trường nào. `DocumentMetadata` không ghi nguồn gốc giá trị | POC-24 (I15) |
| **X16** | **Tập trường lọc được phủ đủ POC-02** | `FILTERABLE_FIELDS` = `document_type`, `status`, `classification`, `collection_id`, `version_label`. **Thiếu `owner` và khả năng tìm theo tên/title** mà POC-02 yêu cầu | POC-02, 19 |

Hệ quả cần nhớ với X16: `assert_filterable` sẽ **pass** lúc khởi động trong khi POC-02 vẫn trượt, vì nó chỉ kiểm tra những trường đã khai, không kiểm tra danh sách khai có phủ đủ yêu cầu hay không.

### Nhóm 4 — dọn dẹp và nhất quán nhỏ

| ID | Nội dung | Đề xuất |
|---|---|---|
| **X17** | `OmEntityVersionGuard.changed_unexpectedly` so sánh `current < captured`, chỉ phát hiện được trường hợp `version` **tụt**. Hai `PATCH` đồng thời đều làm version **tăng** nên không phát hiện được | Tài liệu đã sửa để không đòi hỏi quá mức (mục 5 của c4-04b). Code cần đổi kỳ vọng của `OmEntityVersionGuardTest` cho khớp, và POC-22 phải được tính là đạt nhờ khóa |
| **X18** | `IdempotencyGuard.inspect` trả `is_replay=False` cho intent `FAILED`, hàm ý cho xử lý lại; nhưng `upload_intent.idempotency_key` có ràng buộc `UNIQUE` nên `create` luôn ném `ConcurrencyConflictError` → `409` | Chọn một hướng và làm cho rõ: hoặc trả `409` ngay từ `inspect` (bỏ nhánh chết), hoặc định nghĩa cách giải phóng khóa cũ. Hiện tại là một nhánh code không bao giờ chạy tới đích |
| **X19** | `register_document` không gọi `ensure_collection` (T7 cũ) | Giữ quyết định "tạo collection là việc quản trị", nhưng khi đã có D24 thì phải **kiểm tra collection tồn tại** lúc đăng ký tài liệu, thay vì nhận một `collection_id` tự do |
| **X20** | `POST /versions/{id}/status` nhận `document_id` qua **query param**, không có trong hợp đồng API của tài liệu | Đây là hệ quả hợp lý của việc adapter cần `document_id` để dựng FQN. Đã ghi vào c4-04b mục 3; cần bổ sung tham số này vào bảng endpoint ở mục 12 |

### Nhóm 5 — phát hiện thêm khi lập kế hoạch LLD (X22–X40)

Những điểm này chỉ lộ ra khi đọc tới mức wiring và mức method, tức đúng mức mà [c4-09](c4-09-lld.md) mô tả.

| ID | Thiết kế nói | Code làm | Hệ quả | Nơi sửa |
|---|---|---|---|---|
| **X22** | Mỗi phụ thuộc một `ResilientCallExecutor` riêng, chủ sở hữu breaker là lớp thực sự gọi ra ngoài ([c4-09 mục 5.3](c4-09-lld.md#53-bản-đồ-executor--ai-sở-hữu-circuit-breaker-nào)) | `OmLineageRelationshipStore` nhận executor `relationship_store` nhưng mọi lời gọi đi qua `OmHttpClient` dùng executor `catalog`. `OpenMetadataCatalogAdapter` cũng nhận executor rồi không dùng `_call` | Executor `relationship_store` không bao giờ thấy traffic → breaker luôn `CLOSED` → `check_health()` của lineage store đọc một breaker vô nghĩa. Khối `resilience.relationship` trong cấu hình không có tác dụng | `openmetadata/lineage.py`, `openmetadata/catalog_adapter.py`, `infrastructure/container.py` |
| **X23** | Không bọc executor hai lần | `S3ManifestIntentStore._call(lambda: self._objects.put_overwrite(...))` → executor `intent_store` rồi vào `S3ObjectStoreAdapter._call` với executor `object_store` | Số lần retry nhân nhau (3 × 3), hai breaker cùng đếm một lỗi | `intent/s3_manifest_store.py` |
| **X24** | `adapter` không được import `application` | `openmetadata/catalog_adapter.py:27` và `fake/in_memory.py:15` import `CatalogMetadataBuilder` từ `application` | Adapter ngoài cùng phụ thuộc ngược lên tầng trong. Test kiến trúc chỉ kiểm chiều `application → adapter`, không kiểm chiều này | chuyển lớp sang `domain/metadata_builder.py` |
| **X25** | Deadline tạo ở `adapter.inbound` theo timeout của API công khai và truyền xuống mọi lời gọi (`c4-04b` mục 11.3, ràng buộc 1) | `AppSettings.request_budget_seconds` **không nơi nào đọc**; mọi `_call` gọi với `deadline=None` nên mỗi executor tự tạo deadline riêng | Một request chạm ba phụ thuộc có thể chờ tổng bằng tổng ba budget nhân số lần retry, trong khi client đã bỏ đi | `infrastructure/resilience/deadline.py`, `http/context.py`, `executor.py` |
| **X26** | Mỗi phụ thuộc ngoài tiến trình có một indicator | `_register_health` chỉ duyệt 5 port; `events`, `audit`, `policies` bị bỏ dù `OutboxEventPublisher` và `StructuredAuditLogger` đều là `HealthProbe` | `/internal/healthz/deps` không nói gì về outbox và audit | `infrastructure/container.py` |
| **X27** | `IdpHealthIndicator` phản ánh trạng thái JWKS thật | `IdpHealthIndicator(jwks_available=True)` hard-code trong container; không có đường nối tới `OidcTokenVerifier.jwks_available` | Indicator `idp` thuộc nhóm `REQUIRED_FOR_READ` nhưng **không bao giờ** báo sự cố | `infrastructure/container.py`, `security/auth.py` |
| **X28** | Khóa chọn theo `lock.kind`, và khóa trong tiến trình chỉ dùng được với một instance | `_build_real_ports` trả `InMemoryDocumentLock()` giống hệt profile fake, và khai `DependencyKind.REQUIRED_FOR_WRITE` | `/readyz` báo khóa khỏe trong khi thực tế không có khóa phân tán nào. Chạy hai instance là mất I4/I5 **mà không có lỗi nào báo** | `infrastructure/container.py`, `adapter/outbound/lock/` |
| **X29** | `/readyz` chỉ `FULL` khi mọi phụ thuộc `REQUIRED` đều UP | `ReadinessPolicy._all_up` dùng `all(... for ... if kind match)` nên **nhóm rỗng trả `True`** | Thiếu indicator nhóm ghi (đúng tình huống X26, X28) thì service vẫn báo `FULL` và nhận ghi | `adapter/inbound/health/registry.py` |
| **X30** | Tên field nói đúng nội dung | `LifecyclePolicy.transition` nhánh OBSOLETE trả `ApprovalResult(approved=document.obsolete(...))` — field tên `approved` chứa bản vừa bị Obsolete | Người đọc code và người ghi audit đều bị dẫn sai. Audit `from → to` (X4) không dựng được từ cấu trúc này | `domain/model.py`, `domain/policy.py`, `approve_version.py`, `routes.py` |
| **X31** | Hai `Document` khác nhau có thể cùng `checksum` nhưng giữ `document_id` riêng (I9) | `SourceSyncJob._version_command` dựng `IdempotencyKey(f"sync-{checksum[:24]}")` — **không có `document_id`** | Hai tài liệu khác nhau cùng nội dung: tài liệu thứ hai bị `IdempotencyGuard` coi là replay của tài liệu thứ nhất và **không được tạo phiên bản**. Phá đúng I9 | `adapter/inbound/sync/source_sync.py` |
| **X32** | Không giữ toàn bộ file trong bộ nhớ | `SourceFile.payload: bytes`; `FileSystemSourceConnector.discover` gọi `path.read_bytes()` nên "discover" cũng là "load" toàn bộ thư mục nguồn | RAM tỷ lệ với tổng kích thước lô đồng bộ, không chỉ một file | `adapter/inbound/sync/source_sync.py` |
| **X33** | Job nền chạy liên tục | `SourceSyncScheduler.run_forever` không bắt exception ngoài `DomainError` | Một lỗi lạ kết thúc vòng lặp **im lặng**; đồng bộ dừng mà không ai biết | `adapter/inbound/sync/source_sync.py` |
| **X34** | — (lớp không có trong `c4-04b`) | `_VersionIndex` cache `version_id → (uuid, fqn)` không TTL, không invalidation khi `remove()` | Entity bị xóa vẫn còn trong cache; `upsert` sau đó trỏ vào UUID không còn tồn tại | `openmetadata/lineage.py` |
| **X35** | Mọi tham số đọc được của hệ thống nằm ở `configs/` và **được đọc** | Ba knob chết: `StorageSettings.object_prefix` (key hard-code `objects/`), `RelationshipStoreSettings.sqlite_path` (container dùng `intent.sqlite_path` cho cả bốn bảng), `SecuritySettings.lock_timeout_seconds` | Người vận hành đổi chúng rồi tin là đã có tác dụng. Một knob chết tệ hơn không có knob | `domain/value.py`, `infrastructure/container.py`, `configs/` |
| **X36** | Mỗi singleton có `reset()` (quy tắc R2) | `SettingsProvider` chỉ có `reload()`/`replace()` | Lệch quy tắc đã ghi ở `src/README.md` | `config.py` |
| **X37** | Bảng ánh xạ D1–D18 trỏ đúng file | Dòng D14 ghi `OutboxEventPublisher` ở `observability/audit_log.py`; lớp này thực ra ở `observability/outbox.py` | Người đọc tìm sai chỗ; đúng loại lỗi mà cổng tài liệu↔code phải chặn | `src/README.md` |
| **X38** | `/internal/healthz/deps` trả chi tiết từng indicator | `HealthCheckRegistry.details()` chỉ gọi lại `readiness()`; `health.cache_ttl_seconds`, `probe_timeout_seconds`, `startup_deadline_seconds`, `expose_details` không được container truyền vào | Không có đường xem chi tiết; bốn cấu hình là knob chết | `adapter/inbound/health/registry.py`, `infrastructure/container.py` |
| **X39** | `RelationshipStorePortContractTest` chạy trên `OmLineageRelationshipStore` **và** `SqliteRelationshipRegistry` (`c4-04b` mục 13) | Fixture chỉ parametrize `in_memory` và `sqlite`; `OmLineageRelationshipStore` **không xuất hiện trong bất kỳ test hay ví dụ nào** | Lớp quyết định quyết định mở Q4 chưa từng được chạy. Bất kỳ lỗi trong `_from_edge`/`_version_from_fqn` đều chưa bị phát hiện | `tests/contract/fake_openmetadata.py`, `tests/contract/conftest.py` |
| **X40** | Luật kiến trúc được kiểm bằng cấu trúc | `TestWritePathRules` kiểm bằng substring trên source và `source.index()` so thứ tự; `write_use_cases` hard-code 5 tên file | Vỡ khi format lại dòng hay tách helper; một use case ghi mới **không bị kiểm** và không ai biết | `tests/unit/test_architecture_rules.py` |

### Thứ tự sửa

Thứ tự và ràng buộc phụ thuộc giữa các bước nằm ở bảng **Phân bổ theo bước** ở mục 2b.1. Ba ràng buộc thứ tự không được đổi:

1. **B1 trước mọi bước khác** — luật kiến trúc mới (`adapter` không import `application`) sẽ đỏ cho tới khi `CatalogMetadataBuilder` được chuyển sang `domain/`.
2. **B8 trước B9** — B9 cần `idempotency_key` trong `TransitionStatusCommand`; làm ngược lại thì phải sửa command hai lần.
3. **B9 trước B17** — khóa Redis có nhánh "mất lease thì hủy operation", chỉ an toàn khi lượt duyệt dở dang được một intent bền vững phục hồi.

Và một ràng buộc về bằng chứng: **B20 làm cuối**. `TestWritePathRules` dùng substring sẽ vỡ ở B9 và B18; sửa nó sớm thì không chứng minh được nó bắt được gì.

## 3. Còn thiếu và khoảng trống đã biết

| ID | Nội dung | Ảnh hưởng | Xử lý |
|---|---|---|---|
| T1 | **D17 Sync Orchestrator** từng bị bỏ sót: thư mục `adapter/inbound/sync/` chỉ có `__init__.py` | POC-12 không kiểm chứng được | **Đã bổ sung** 17/11/2026: `SourceSyncJob`, `FileSystemSourceConnector`, `SourcePermissionMapper`, `SourceSyncScheduler` + 11 test |
| T2 | `S3ManifestIntentStore` (biến thể A của Q2) từng thiếu, chỉ có sqlite và fake | Q2 không thể chốt bằng số liệu | **Đã bổ sung** cùng ngày và đưa vào contract test |
| T3 | `PolicyDecisionPortContractTest`, `EventPublisherPortContractTest` chưa thành bộ riêng | Hai port này từng chỉ được phủ gián tiếp | **Đã bổ sung** 18/11/2026, cùng `MetadataCatalogPortContractTest` chạy trên server OpenMetadata giả lập |
| T7 | Catalog chưa có `ensure_collection` trong luồng ghi chính | Collection được tạo khi quản trị gọi riêng, chưa tự tạo khi đăng ký tài liệu | Giữ quyết định "tạo collection là việc quản trị". **Cập nhật 19/11:** nhưng khi đã có D24 thì phải kiểm tra collection tồn tại lúc đăng ký, xem X19. Hiện `ensure_collection` không có người gọi nào, xem X13 |
| T4 | Khóa phân tán | Nhiều instance Document Service sẽ **không** giữ được I4/I5 | **Cập nhật 19/11:** không còn là "ngoài phạm vi" mà là **ràng buộc triển khai**: chỉ được chạy một instance C1 cho tới khi có C13. Quyết định Q12 ở [c4-07](c4-07-element-catalog.md#4-quyết-định-kiến-trúc-còn-mở), test case POC-26, xem X9 |
| T5 | Đường dẫn API OpenMetadata | Test bằng respx không chứng minh bản thật nhận đúng payload | Chạy `tests/integration` khi có hạ tầng (POC-19, 20, 22) |
| T6 | C9 Search Gateway, C11 Admin UI, C12 MCP | Ngoài phạm vi đã thống nhất | Chỉ bật nếu PoC cho thấy cần |
| T8 | IdP thử nghiệm trong môi trường PoC | **POC-04 chưa chạy được**: `deploy/docker-compose.yml` đặt `AUTHENTICATION_PROVIDER=basic`, không có IdP | Phải dựng một IdP thử nghiệm (Keycloak hoặc tương đương) trước khi tính POC-04 |
| T9 | Mock downstream nhận webhook | **POC-11 chưa chạy được đầu-cuối** | Dựng một service nhận webhook tối giản, kết hợp với X8 |

## 4. Kết quả có ý nghĩa cho quyết định còn mở

| Quyết định | Dữ liệu từ code và test | Hàm ý |
|---|---|---|
| **Q2 — intent store** | Contract chạy trên 3 hiện thực. SQLite bảo vệ khóa bằng UNIQUE. S3 tạo manifest và index bằng PUT If-None-Match, chỉ phục hồi manifest được index trỏ tới. Test tương thích đọc lại manifest và SQLite cũ sau restart. | Registry database có truy vấn trực tiếp. S3 cần hỗ trợ conditional PUT và vẫn phải quét prefix, manifest mất cuộc tranh khóa có thể tồn tại ngoài index. |
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
| 1 | `uv run pytest` | **223 passed, 6 skipped** (đo lại 19/11/2026) |
| 2 | `make test` (mypy → pytest → pylint) | mypy sạch trên 90 file; pylint **10.00/10**, không còn cảnh báo |
| 3 | Luồng end-to-end qua HTTP với profile fake | Đăng ký → 2 phiên bản → duyệt → quan hệ hai chiều → tìm kiếm lọc tổ hợp → tải → 8 bản ghi audit; `/readyz` = `FULL`, 7 phụ thuộc đều `UP` |
| 4 | Lỗi một phía trong luồng ghi | `test_reconcile.py`: intent → `RetryPending` → job phục hồi → `Completed`, **không** nhân đôi phiên bản |
| 5 | Hai lượt duyệt đồng thời | `test_invariants.py::test_concurrent_approval_keeps_one_approved`: đúng một bản `Approved` |
| 6 | `/livez` khi phụ thuộc DOWN | `test_health.py`: `livez` không đổi; `ReadinessPolicy` chuyển `READ_ONLY`/`DOWNLOAD_ONLY`/`NOT_READY` đúng nhóm phụ thuộc |
| 7 | Test tích hợp | Tự bỏ qua khi thiếu `DS_CATALOG__BASE_URL`/`DS_STORAGE__ENDPOINT` (5 test) — **chưa chạy vì máy chưa có docker** |
| 8 | Cổng CI | Chạy lại script của workflow tại máy: chèn một sơ đồ mermaid lỗi → checker báo `1 diagram lỗi`; cổng đếm dòng → không file nào vượt 1000 dòng (dài nhất: 474). **Workflow trên GitHub chưa chạy** vì repo còn ở máy local |
| 9 | Cô lập singleton | Chạy `pytest` hai lượt, lượt hai đảo thứ tự file: kết quả giống nhau |
| 10 | `make docs-check` | **33 sơ đồ, 0 lỗi** trên toàn bộ `docs/` sau lượt sửa 19/11/2026; kiểm tra link nội bộ của mọi README và `docs/*.md`: không link nào trỏ tới file thiếu |
| 12 | Đối chiếu tên lớp trong `docs/c4-04b` với `src/` (19/11/2026) | **12 tên lớp trong tài liệu không tồn tại trong mã nguồn**: `JdbcRegistryIntentStore`, `JdbcRelationshipRegistry`, `OmPermissionResultFilter`, `BackoffCalculator`, 6 lớp `*Controller`, 4 lớp `*HealthIndicator` riêng theo phụ thuộc. Tài liệu đã sửa; cần thêm cổng CI để không lặp lại |
| 13 | Đối chiếu bảng endpoint của `docs/c4-04b` mục 12 với router thật | Thiếu `GET /documents/{id}` trong tài liệu; `POST /internal/reconcile/run` có trong tài liệu mà không có trong code (reconcile là CLI); `POST /versions/{id}/status` nhận thêm query `document_id`. Tài liệu đã sửa |
| 11 | `make examples` | 6 ví dụ chạy hết, mỗi bước in `[OK  ]`; ví dụ 07 in hướng dẫn dựng hạ tầng khi thiếu biến môi trường. Bước này cũng nằm trong `python_package.yaml` nên ví dụ không mục theo thời gian |

## 6. Giao thức đối soát bằng agent

Lần rà soát 19/11/2026 cho thấy bảng ở mục 1 từng ghi `Khớp` cho những module thực ra lệch — vì người viết code cũng là người tự đối soát, và tiêu chuẩn đối soát khi đó sai. Từ lượt refactor theo [c4-09](c4-09-lld.md), **người phán quyết không phải người viết code**.

### 6.1. Hai vai

| Vai | Được làm | Không được làm |
|---|---|---|
| **Agent sửa** (`Fx`) | Đọc mục LLD của bước + các dòng ID của bước mình ở [mục 2b.1](#2b1-bảng-công-việc); sửa code và test; chạy `make test`; chuyển trạng thái ID sang `Chờ đối soát (Bx)` | Không tự ghi `Đã sửa`. Không chạm ID của bước khác. Không sửa `c4-01`…`c4-07` — lệch tài liệu thì báo lại để người điều phối quyết |
| **Agent đối soát** (`Gx`) | Đọc LLD + code + test; phán quyết từng ID; ghi `Đã sửa (Bx, Gx)` kèm `file:dòng`; ghi một dòng vào [mục 8](#8-sổ-đối-soát) | **Chỉ đọc code.** Không sửa code, không sửa test. Không dùng tài liệu làm bằng chứng rằng code đúng |

### 6.2. Luồng một bước

```text
mở bước Bx  →  Fx đọc mục 2b.1 (lọc Bước = Bx) + mục LLD tương ứng
            →  Fx sửa code + test, make test xanh, đổi trạng thái → "Chờ đối soát (Bx)"
            →  /code-review trên diff của Bx
            →  Gx đối soát: ghi "Đã sửa (Bx, Gx)" + bằng chứng, hoặc bác về "Chưa sửa"
            →  Gx ghi một dòng vào mục 8
            →  chỉ khi không còn ID nào ở "Chờ đối soát" mới mở bước kế
```

### 6.3. Bốn quy tắc cho agent đối soát

1. **Bằng chứng hoặc không đạt.** `Đã sửa` mà không chỉ được `file:dòng` thì ghi `Chưa sửa`.
2. **Test phải thật sự chặn.** Với mỗi ID, chỉ ra dòng assert **sẽ đỏ** nếu lỗi quay lại. Test chỉ kiểm sự tồn tại của một thuộc tính thì không tính.
3. **Không nhận lệch mới.** Nếu bước làm phát sinh lệch mới ở file đã chạm, gate mở một ID mới (X41, X42…) ở mục 2b.1 với trạng thái `Chưa sửa` — không im lặng bỏ qua.
4. **Phạm vi đúng một bước.** Agent nhận danh sách file đã sửa và mục LLD tương ứng, không nhận cả repo.

### 6.4. Khi hoàn thành một module (quy tắc R3 cũ, vẫn áp dụng)

1. Đối chiếu class/method vừa viết với [c4-09](c4-09-lld.md) mục tương ứng, bất biến ở [c4-04 mục 4.2](c4-04-code-data-model.md#42-bất-biến-phải-được-code-thực-thi), và thứ tự bước ở [c4-05](c4-05-dynamic-views.md).
2. Ghi một dòng vào bảng mục 1 với trạng thái `Khớp` / `Lệch có lý do` / `Thiếu`, kèm cột `Gate`.
3. Lệch thì thêm dòng vào mục 2 kèm **lý do kỹ thuật**, và sửa lại `c4-09` hoặc `c4-0*` cho khớp.
4. Chạy `make test` và `make docs-check` trước khi sang module kế tiếp.
5. Mỗi lượt rà soát, đối chiếu thêm **ba thứ mà hai lượt đầu bỏ sót**: (a) một yêu cầu "Bắt buộc" ở chương II báo cáo có phần tử nào nhận trách nhiệm hay không, (b) tên lớp ở `c4-04b` và `c4-09` có tồn tại trong `src/` hay không, (c) một phần tử có bị vẽ ở hai mức C4 với hai vai trò khác nhau hay không. Trạng thái `Khớp` chỉ có nghĩa khi tiêu chuẩn đối chiếu đúng.

---

## 7. Ma trận đầy đủ tính năng

**Điều kiện đóng lượt refactor.** Mọi dòng phải ở một trong hai trạng thái: `Đã hiện thực` kèm `file` làm bằng chứng, hoặc `Ngoài phạm vi (đã chốt)` kèm lý do. **Một dòng trống là lượt chưa đóng được.**

Ký hiệu: `(Bx)` = sẽ đạt ở bước Bx; `có sẵn` = sản phẩm/hạ tầng cung cấp.

### 7.1. Container C1–C13

| ID | Container | Trạng thái | Nơi hiện thực |
|---|---|---|---|
| C1 | Document Service | Đã hiện thực | `src/document_service/`, `main.py` |
| C2 | Catalog Application | Có sẵn | OpenMetadata 1.12.0, `deploy/docker-compose.yml` |
| C3 | Catalog Metadata DB | Có sẵn | `mysql:8.0.35` trong compose |
| C4 | Catalog Search Index | Có sẵn | `opensearch:2.19.0` trong compose |
| C5 | Catalog Ingestion | Ngoài phạm vi (đã chốt) | Tùy chọn, chỉ dùng khảo sát nguồn — [c4-02 mục 2.6](c4-02-container.md#26-container-tùy-chọn-và-điều-kiện-kích-hoạt) |
| C6 | Object Storage S3 | Có sẵn | `seaweedfs:3.68` trong compose; `storage/s3_store.py` |
| C7 | Service State Store | Đã hiện thực | `adapter/outbound/sqlite_support.py` (4 bảng); biến thể A ở `intent/s3_manifest_store.py` |
| C8 | Reconciliation Worker | Đã hiện thực | `worker/reconcile.py`, `make reconcile` |
| C9 | Search / Query Gateway | Ngoài phạm vi (đã chốt) | Tùy chọn; lọc quyền hiện ở D18 |
| C10 | Outbox Dispatcher | **Một phần** → **(B15)** | Lớp có ở `observability/outbox.py`; **thiếu tiến trình chạy** — X8 |
| C11 | Admin / Business UI | Ngoài phạm vi (đã chốt) | Tùy chọn |
| C12 | MCP Server adapter | Ngoài phạm vi (đã chốt) | Tùy chọn |
| C13 | Distributed Lock | **(B17)** | `adapter/outbound/lock/redis_lock.py` + `redis` trong compose — X9 |

### 7.2. Component D1–D26

| ID | Thành phần | Trạng thái | Nơi hiện thực |
|---|---|---|---|
| D1 | API Layer | Đã hiện thực | `http/routes.py` (10 endpoint), `schemas.py`, `context.py`, `dependencies.py`, `errors.py` |
| D2 | Authentication | Đã hiện thực | `security/auth.py` |
| D3 | Authorization / PDP | Đã hiện thực | `policy/policy_decision.py`, `AccessPolicy.permits` |
| D4 | Upload Handler | Đã hiện thực; **(B16)** chuyển sang stream | `http/upload_handler.py`, `utils/hashing.py` |
| D5 | Checksum & Dedup | Đã hiện thực | `domain/policy.py::DedupPolicy` |
| D6 | Version Manager | Đã hiện thực | `domain/policy.py::VersionPolicy` |
| D7 | Lifecycle Manager | Đã hiện thực; **(B2, B7, B9)** | `domain/policy.py::LifecyclePolicy`, `usecase/approve_version.py` |
| D8 | Relationship Manager | Đã hiện thực; **(B4)** trả `direction` | `domain/policy.py::RelationshipPolicy`, `usecase/relationships.py` |
| D9 | Access Policy Manager | Đã hiện thực; **(B11)** thu hồi có hiệu lực ngay | `usecase/search_documents.py::UpdateAccessPolicyUseCase` |
| D10 | Download Issuer | Đã hiện thực | `usecase/issue_download.py`, `storage/download.py` |
| D11 | Intent & Idempotency | Đã hiện thực; **(B9)** thêm `IntentKind` và `StatusChangeSaga` | `application/orchestration/` |
| D12 | Catalog Adapter | Đã hiện thực | `adapter/outbound/openmetadata/` (16 lớp) |
| D13 | Storage Adapter | Đã hiện thực; **(B6, B16)** | `storage/s3_store.py` |
| D14 | Outbox Writer | Đã hiện thực; **(B11)** thiếu sự kiện `access.changed` và `document.created` — X41 | `observability/outbox.py::OutboxEventPublisher`, `SqliteOutbox` |
| D15 | Reconcile Runner | Đã hiện thực; **(B9c)** hai nhánh phục hồi | `worker/reconcile.py` |
| D16 | Audit Logger | Đã hiện thực; **(B7, B14)** | `observability/audit_log.py` |
| D17 | Sync Orchestrator | Đã hiện thực; **(B16, B18)** | `adapter/inbound/sync/source_sync.py` |
| D18 | Search Query Service | Đã hiện thực; **(B3, B13)** | `usecase/search_documents.py`, `openmetadata/search.py` |
| D19 | Relationship Store Adapter | Đã hiện thực; **(B5)** có test, **(B18)** executor riêng | `relationship/sqlite_registry.py`, `openmetadata/lineage.py` |
| D20 | State Store Adapter | Đã hiện thực | `sqlite_support.py`, `intent/`, `observability/` |
| D21 | Policy Decision Adapter | Đã hiện thực; **(B11)** `invalidate` lên port | `policy/policy_decision.py` |
| D22 | Document Lock Adapter | Một phần; **(B17)** | `fake/in_memory.py::InMemoryDocumentLock`, `lock/redis_lock.py` (B17) |
| D23 | Metadata Schema & Validation | **Ngoài phạm vi (đã chốt)** | Chỗ cắm: `domain/metadata_fields.py`, `OmCustomPropertyRegistrar.assert_filterable` |
| D24 | Collection Manager | **Ngoài phạm vi (đã chốt)**; **(B13)** có `find_collection` làm chỗ cắm | Chỗ cắm: `MetadataCatalogPort.ensure_collection` |
| D25 | Retention & Deletion Manager | **Ngoài phạm vi (đã chốt)** | Chỗ cắm: `Document.retention_policy`, `CatalogMetadataBuilder.document_fields` |
| D26 | Outbox Dispatcher | Một phần; **(B15)** | `observability/outbox.py::OutboxDispatcher`, `worker/dispatch.py` (B15) |

### 7.3. Bất biến I1–I18

| # | Trạng thái | Test chặn |
|---|---|---|
| I1 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:130` `test_version_id_independent_of_label` (assert `"1.0" not in str(version_id)`); `tests/unit/test_invariants.py:646` `test_version_id_is_immutable_value` (gán lại raise) (phủ mạnh) |
| I2 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:141` `test_duplicate_label_rejected` (raise `VersionLabelConflictError`); `tests/unit/test_api_flow.py:155` `test_duplicate_version_label_conflict` (HTTP 409) (phủ mạnh) |
| I3 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:154` `test_old_version_content_preserved` (head bản cũ vẫn trả size `len(b"v1")`); `tests/contract/test_object_store_contract.py:82` `test_put_is_idempotent` (ghi đè vẫn đọc ra nội dung ban đầu) (phủ mạnh) |
| I4 | Đã hiện thực; **GT phủ mạnh**; **(B9)** phục hồi khi patch lỗi | `tests/unit/test_invariants.py:246` `test_single_approved_version` (assert `len(approved) == 1`, `current_version_id == second`); `tests/unit/test_invariants.py:291` `test_concurrent_approval_keeps_one_approved` (asyncio.gather → `len(approved) == 1`); `tests/unit/test_invariants.py:492` `test_cannot_approve_twice`; `tests/unit/test_invariants.py:401` `test_recovery_finishes_second_patch_under_document_lock` (phủ mạnh) |
| I5 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:246` `test_single_approved_version` (assert `obsoleted_from is APPROVED`, audit `"Approved -> Obsolete"`, `obsoleted.version_id == first`); `tests/unit/test_invariants.py:291` `test_concurrent_approval_keeps_one_approved` (phủ mạnh) |
| I6 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:551` `test_relationship_target_not_rebound` (raise `RelationshipRebindError`); `tests/unit/test_invariants.py:584` `test_relationship_survives_new_version`; `tests/contract/test_relationship_store_contract.py:92` `test_new_version_does_not_rebind`; `tests/unit/test_architecture_rules.py:344` `test_declare_relationship_checks_rebind` (phủ mạnh) |
| I7 | Đã hiện thực; **GT phủ mạnh**; **(B5)** chạy trên ba hiện thực | `tests/contract/test_relationship_store_contract.py:36` `test_outgoing_query`; `:44` `test_incoming_query_keeps_declared_endpoints`; `:56` `test_filter_by_relation_type`; `:72` `test_both_direction_returns_two_edges`; `tests/unit/test_invariants.py:519` `test_relationship_is_bidirectional` (phủ mạnh) |
| I8 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:169` `test_same_content_does_not_create_version` (assert `duplicate is True`, `version_id == first`); `tests/unit/test_api_flow.py` `test_duplicate_upload_returns_existing_version` (phủ mạnh) |
| I9 | Đã hiện thực; **GT phủ mạnh**; **(B18)** sửa idempotency key sync | `tests/unit/test_invariants.py:184` `test_same_checksum_different_documents` (cùng checksum, khác `document_id`, `created is True`); `tests/unit/test_source_sync.py:186` `test_two_documents_same_content_are_not_replays_of_each_other` (phủ mạnh) |
| I10 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:622` `test_storage_uri_matches_version` (assert `version_id in uri.key`, `document_id in uri.key`, hậu tố `/source`); `tests/contract/test_catalog_contract.py:150` `test_list_versions_round_trip` (assert `loaded.storage_uri == version.storage_uri`); `tests/unit/test_reconcile.py:149` `test_checksum_mismatch_blocks_catalog_and_recovery` (phủ mạnh) |
| I11 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:635` `test_restricted_by_default` (assert `classification == "restricted"`, `permits(outsider, DOWNLOAD) is False`); `tests/contract/test_policy_decision_contract.py:131` `test_unmapped_document_is_restricted` (assert `decision.allowed is False`); `tests/unit/test_source_sync.py:89` `test_unmapped_source_is_restricted` (phủ mạnh) |
| I12 | Đã hiện thực; **GT phủ mạnh**; **(B7)** thêm trạng thái trước, **(B20)** AST | `tests/unit/test_invariants.py:321` `test_audit_records_status_change` (assert `"version.status_changed" in actions`, detail `"Draft -> Approved"`); `tests/unit/test_invariants.py:215` `test_unauthorized_replay_is_denied_and_audited`; `tests/unit/test_architecture_rules.py:325` `test_write_use_cases_record_audit` (AST chặn WriteUseCase không gọi `_record`, GB20 đã phá-và-revert xác nhận đỏ) (phủ mạnh) |
| I13 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:200` `test_replay_same_idempotency_key` (assert `replayed is True`, `version_id == first`); `tests/contract/test_intent_store_contract.py:117` `test_concurrent_same_key_rejected_or_single` (gather → chỉ một thắng); `tests/unit/test_api_flow.py:145` `test_missing_idempotency_key_rejected` (phủ mạnh) |
| I14 | Đã hiện thực; **GT phủ mạnh** | `tests/unit/test_invariants.py:374` `test_latest_differs_from_current_approved` (assert `latest.version_id != current_version_id`); `tests/contract/test_catalog_contract.py:185` `test_patch_document_fields_sets_current_version`; `tests/unit/test_reconcile.py:235` `test_dangling_current_version_detected` (DanglingEntityScanner phát hiện lệch I4/I14) (phủ mạnh) |
| I15 | **Chia hai nửa.** Nửa D23 (`MetadataSource`/`MetadataChange`) **ngoài phạm vi (đã chốt)**. Nửa **D4** — "tự động trích xuất chỉ gồm metadata kỹ thuật, không đọc nội dung" — **trong phạm vi**, hiện không ai nhận → **(B16)** | X55 |
| I16 | Đã hiện thực; **GT phủ mạnh**; **(B4)** | `tests/contract/test_relationship_store_contract.py:44` `test_incoming_query_keeps_declared_endpoints` (assert `direction is INCOMING`, `source_version_id == SAD_V11`, `target_version_id == SRS_V20` — không đảo hai đầu); `:36` `test_outgoing_query` (assert `direction is OUTGOING`); `tests/unit/test_invariants.py:519` `test_relationship_is_bidirectional` (phủ mạnh) |
| I17 | **Ngoài phạm vi (đã chốt)** — phụ thuộc D25 | — |
| I18 | **Ngoài phạm vi (đã chốt)** — phụ thuộc D23 | — |

### 7.4. Test case PoC-01…28

| Mã | Trạng thái | Ghi chú |
|---|---|---|
| POC-01 | Đã có test | `test_api_flow.py`, `test_object_store_contract.py` |
| POC-02 | Một phần → **(B13, B14)** | Lọc tổ hợp có test; thiếu `owner`, tìm theo tên và `version_label` (X16); phân trang `/search` chưa nối vào query (X53) |
| POC-03 | Đã có test | `test_invariants.py` |
| POC-04 | **Chặn** — thiếu IdP | PoC dùng `AUTHENTICATION_PROVIDER=basic`; T8 |
| POC-05 | Đã có test | `examples/02_project_documents.py` |
| POC-06 | Một phần → **(B4, B5)** | Chiều quan hệ đang sai (X1); lineage chưa có test (X39) |
| POC-07 | Đã có test | `test_invariants.py` (current approved), `examples/01` |
| POC-08 | Đã có test | `test_reconcile.py` |
| POC-09 | Một phần → **(B4, B5)** | Như POC-06 |
| POC-10 | Một phần → **(B9)** | Thiếu ca "lỗi ở lệnh patch thứ hai" — X3 |
| POC-11 | **Chặn** → **(B11, B15)** | Không tiến trình phát sự kiện (X8); **không có sự kiện `access.changed`** để downstream biết quyền đã đổi (X41); thiếu mock downstream (T9) |
| POC-12 | Đã có test | `test_source_sync.py`, `examples/05` |
| POC-13 | Đã có test | `test_invariants.py` |
| POC-14 | Một phần → **(B14)** | Audit tra được theo tài liệu; thiếu phân trang (X10); thiếu endpoint liệt kê phiên bản để truy lịch sử bản `Obsolete` (X47) |
| POC-15 | Chưa kiểm chứng | **Khôi phục file là năng lực của C6** (S3 Versioning, Object Lock), không phải một method của `ObjectStorePort` — xem `c4-09` bảng phạm vi container. POC-15 là **thủ tục vận hành**, kiểm chứng trên S3 thật; phần xóa theo retention thuộc D25 (ngoài phạm vi) |
| POC-16 | Chưa kiểm chứng | Cần dữ liệu đủ lớn và hạ tầng thật |
| POC-17 | Một phần | Lọc quyền kết quả có ở `SearchPage.filtered`; cần đo trên bản thật |
| POC-18 | Đã có test | `test_intent_store_contract.py`, `test_reconcile.py` |
| POC-19 | Chưa chạy | `tests/integration/test_real_infrastructure.py`, cần docker |
| POC-20 | Chưa chạy | Cần OpenMetadata thật — `CatalogBypassGuardTest` chưa có |
| POC-21 | Đã có test | `test_reconcile.py`, `test_health.py` |
| POC-22 | Một phần → **(B17)** | Một instance có test; nhiều instance cần C13 |
| POC-23 | Một phần → **(B11)** | Thu hồi quyền chưa có hiệu lực ngay — X21 |
| POC-24 | **Ngoài phạm vi (đã chốt)** | Phụ thuộc D23 |
| POC-25 | **Ngoài phạm vi (đã chốt)** | Phụ thuộc D25 |
| POC-26 | **Đã kiểm chứng (20/11/2026)** | Hai tiến trình cùng duyệt một tài liệu — 13/13 test lock contract pass trên `redis:7.4-alpine` qua `docker compose up -d redis` + `DS_LOCK__REDIS_URL=redis://localhost:6379/0` |
| POC-27 | **Ngoài phạm vi (đã chốt)** | Phụ thuộc D24 |
| POC-28 | **(B16)** | Đo RAM theo kích thước file và số request đồng thời |

### 7.5. Yêu cầu "Bắt buộc" ở chương II đề bài

| Nhóm chức năng (mục 2.2 đề bài) | Trạng thái |
|---|---|
| Lưu trữ raw data | Đã hiện thực. **Khôi phục file**: năng lực của C6 (S3 Versioning/Object Lock) + thủ tục vận hành, kiểm ở POC-15 — không phải API của service. **Vòng đời/xóa file ngoài phạm vi** (D25) |
| Tổ chức tài liệu theo collection | **Ngoài phạm vi (đã chốt)** (D24); `collection_id` vẫn lưu và lọc được |
| Metadata chuẩn và mở rộng | Đã hiện thực. **Kiểm tra hợp lệ theo loại tài liệu** và **provenance** (`MetadataSource`/`MetadataChange`) **ngoài phạm vi** (D23, X15). Ràng buộc "trích xuất tự động chỉ gồm metadata kỹ thuật, không đọc nội dung" **trong phạm vi** ở **(B16)** — X55 |
| Phiên bản và trạng thái | Đã hiện thực. **Truy xuất lịch sử bản `Obsolete`** cần endpoint liệt kê phiên bản ở **(B14)** — X47 |
| Liên kết theo phiên bản | Đã hiện thực; chiều quan hệ sửa ở **(B4)** |
| Tìm kiếm | Đã hiện thực; tập trường lọc mở rộng ở **(B13)** |
| Phân quyền đầu-cuối | Đã hiện thực; thu hồi tức thì ở **(B11)**; thứ tự kiểm quyền trước idempotency ở **(B10)** — X43 |
| Tích hợp — API, sự kiện | API đã hiện thực; **tiến trình phát sự kiện ở (B15)**; **sự kiện thay đổi quyền ở (B11)** — X41. Idempotency cho 3 endpoint ghi còn lại ở **(B9a)** — X42 |
| Audit | Đã hiện thực; trạng thái trước ở **(B7)**, phân trang ở **(B14)** |

---

## 8. Sổ đối soát

Mỗi lần một agent đối soát chạy, một dòng. Chưa có dòng nào nghĩa là chưa gate nào chạy.

| Gate | Bước | Phạm vi | Verdict | Số lệch mở thêm | Ngày |
|---|---|---|---|---|---|
| **G0** | Phần A | `c4-09` ↔ `c4-01`…`c4-07` ↔ chương II đề bài | **KHÔNG ĐẠT** → đã sửa `c4-09`, mở ID mới | 9 (X41–X47, X55, X56) | 19/11/2026 |
| **G1** | Phần A | `c4-09` ↔ `src/` (bản nền) | **KHÔNG ĐẠT** → đã sửa 17 phát biểu trong `c4-09`, mở ID mới | 7 (X48–X54) | 19/11/2026 |
| **GB9a (X42)** | B9a | Receipt cho ba endpoint ghi | **Đạt X42**. 9 test API qua. Phần migration và ba backend có đối soát riêng. | 0 | 19/11/2026 |
| **GB9a (storage)** | B9a | Migration và phân loại intent | Đạt. 26 test contract và tương thích chạy độc lập, gồm restart SQLite cũ và manifest thiếu kind. | 0 | 19/11/2026 |
| **GB9b/GB9c** | B9b/B9c | X3, X44 | Đạt. Kiểm độc lập code và test phục hồi PATCH thứ hai, audit lỗi sau commit, replay và khóa theo document. Full suite 301 passed, 5 skipped, pylint 10.00/10. | 0 | 19/11/2026 |
| **GB10/GB11** | B10/B11 | X18, X43, X48, X49, X21, X41 | Đạt. Đọc độc lập luồng kiểm quyền/replay/invalidate, 44 test tập trung và full suite 305 passed, 5 skipped, pylint 10.00/10. Kiểm thu hồi quyền trên hai cache độc lập. | 0 | 19/11/2026 |
| **GB12 (lần 1)** | B12 | Health/readiness và cache quyền tải | **Đang sửa sau đối soát**. 311 test qua, 5 bỏ qua; make test thất bại ở pylint R1711. Cần kiểm việc bỏ cache cũ khi tài liệu mất hoặc quyền bị từ chối và xác nhận đường HTTP DOWNLOAD_ONLY. | 0 | 19/11/2026 |
| **GB12 (lần 2)** | B12 | X17, X26, X27, X29, X38, X45, X46, X52, X54; X35 phần health | **Đạt**. 312 passed, 5 skipped, pylint 10.00/10. Đọc code và test HTTP cache quyền, expiry, sai chủ thể, proxy và bỏ cache khi tài liệu mất. | 0 | 19/11/2026 |
| **GB13/GB14** | B13/B14 | X10, X13 một phần, X16, X19, X47, X53 | **Đạt**. Đọc code collection, cursor, SQL keyset/offset và endpoint versions; 57 test tập trung qua. Full suite 321 passed, 5 skipped, pylint 10.00/10. | 0 | 19/11/2026 |
| **GB15/GB19** | B15/B19 | X8, X51 và khám phá ví dụ | **Đạt**. Đọc điểm vào worker, retry và close, chạy độc lập 14 test event. Full suite 322 passed, 5 skipped, pylint 10.00/10; sáu ví dụ qua. | 0 | 19/11/2026 |
| **GB1** | B1 | X24, X36, X37 và tách module | **Chưa đạt X24** do luật chưa nhận import tương đối. X36 và X37 đạt. `make test` 280 passed, 6 skipped, pylint 10.00/10. | 0 | 19/11/2026 |
| **GB4** | B4 | X1 | Đạt. API và ba store giữ hai đầu cạnh khi truy vấn incoming. | 0 | 19/11/2026 |
| **GB5** | B5 | X39 | Đạt. Chạy độc lập 21 case trên in-memory, SQLite và OmLineage với HTTP giả lập. | 0 | 19/11/2026 |
| **GB1 (lần 2)** | B1 | X24 và các module tách | **Đạt**. Test bắt cả import tuyệt đối và tương đối, cho phép import domain. So với HEAD, AST của 13 lớp được tách giữ nguyên. | 0 | 19/11/2026 |
| **GB3** | B3 | X11 qua DTO và schema trả về của /search | **Đạt**. Test qua hai trường hợp lọc hết và lọc một phần trang. | 0 | 19/11/2026 |
| **GB2** | B2 | X2, X30 | **Đạt**. Contract và test bất biến xác nhận thông tin duyệt, loại bỏ và kết quả chuyển trạng thái. | 0 | 19/11/2026 |
| **GB7** | B7 | X4 | **Đạt**. Audit chứa đủ trạng thái trước/sau cho phiên bản đích và bản cũ bị thay thế. | 0 | 19/11/2026 |
| **GB8** | B8 | X6 | Đạt. Thiếu khóa trả 422 theo hợp đồng các endpoint ghi (plan cũ ghi 400), có khóa duyệt thành công. Hai test HTTP chạy độc lập. | 0 | 19/11/2026 |
| **GB6** | B6 | X5 | Đạt. Đối soát độc lập trên 20 ca object store và recovery, gồm object S3 cũ lưu checksum khai báo sai. | 0 | 19/11/2026 |
| **GB16+18** | B16/B18 | X7, X22, X23, X25, X31, X32, X33, X34, X50, X55 | **Đạt cả 10 ID**. `uv run pytest` 332 passed, 5 skipped (delta +10 so với baseline 322). Đọc độc lập: upload stream + multipart abort, hai `OmHttpClient` tách catalog/relationship_store, bỏ hai-lớp `_call` ở manifest, ContextVar deadline + middleware không đổi chữ ký port, khóa sync có `document_id`, FS connector không đọc RAM, `run_forever` sống qua lỗi lạ, cache lineage có TTL + `forget`, executor `idp` đã gỡ, không còn thư viện parse nội dung. Không chạm ID bước khác. | 0 | 19/11/2026 |
| **GB20** | B20 | X40 | **Đạt**. 7 luật AST ở `TestWritePathRules` tự phát hiện `WriteUseCase` (gồm `ast.Subscript` `WriteUseCase[Cmd,Res]`), kiểm bằng tập dotted-path của `ast.Call` + `lineno`; bề mặt 8 ABC đóng băng; luật 7 (cổng docs↔src) chạy chế độ warn — 0 warning. 3 phá đã xác nhận đỏ với tên class trong message rồi revert xanh: (A) `_record`→`_NO_record` ở `approve_version.py` làm `test_write_use_cases_record_audit` fail với `['approve_version.py:ApproveVersionUseCase']`; (B) `lifecycle.transition`→`lifecycle.NO_transition` làm `test_approve_version_goes_through_lifecycle_policy` fail và dotted-path liệt kê `self._policies.lifecycle.NO_transition`; (C) đảo thứ tự `intents.create` xuống sau `_run_saga` làm `test_write_use_cases_write_intent_before_external_calls` fail với `CreateVersionUseCase: intents.create ở dòng 116 … lời gọi phụ thuộc ngoài TRƯỚC: [('self._run_saga', 115)]`. Sau revert: `make test` 342 passed/13 skipped (350/5 với `DS_LOCK__REDIS_URL=redis://localhost:6379/0`), pylint 10.00/10. | 0 | 20/11/2026 |
| **GB21** | B21 | X56 + đồng bộ tài liệu | **Đạt một phần**. X56 đóng: D27 "Hạ tầng xuyên suốt" có mặt `c4-03:192`, `c4-07:77`, `src/README.md:54`. Đồng bộ mục 16 `c4-09` → `c4-04b`: 5/5 chữ ký port đã phản ánh (`findCollection` `:368`, `query→List~RelatedEdge~ + PageRequest` `:380`, `ProcessingIntent`+`findUnfinished(Duration,IntentKind)` `:394-399`, `PolicyDecisionPort.invalidate` `:405`, `AuditPort.listForDocument→Page~AuditEvent~` `:418`); bảng endpoint mục 12 có `GET /documents/{id}/versions` (B14) `:1211` trả `Page[VersionResponse]`, `/search` với `page_size`/`cursor`/`owner`/`version_label` `:1216`, `/relationships` trả `list[RelatedEdge]+direction` `:1214`, `/audit` trả `Page[AuditEvent]` `:1218`, `/versions/{id}/status` `Idempotency-Key` bắt buộc `:1212`. `OmPermissionResultFilter` còn mention dạng ghi chú lịch sử (`:598`), `ConnectionPool` còn mention với chú "không phải lớp tự viết" (`:1047`), `IdP JWKS executor` đã gỡ khỏi 11.3 (chỉ còn `IdpHealthIndicator` ở 10.3). Grep `BB[0-9]` trong c4-08 rỗng; `POST /internal/reconcile` trong c4-04b rỗng. `UploadIntent`/`upload_intent` không còn ở c4-02/c4-03/c4-04/c4-04b/c4-05/c4-07; ở c4-09 chỉ còn ở hai dòng so sánh lịch sử (`:396`, `:2042`) và một dòng giải thích đổi tên (`:1381`) — chấp nhận. c4-09 mục 5.3 đã bỏ dòng IdP (chỉ còn ghi chú L-EX1 lần 2 ở idp đã gỡ ở B18), 15.5 luật 4 ghi marker `_saga` không dấu chấm, mục 14 nối 4 knob `health.yml`. Luật 7 strict assert `assert not missing` tại `tests/unit/test_architecture_rules.py:421`; `ALLOWLIST_EXTERNAL` không chứa `Checksum`; chạy riêng pass. `make test` 342 passed/13 skipped; `make docs-check` 0 broken. **Mở X57**: `c4-06:35` còn `upload_intent` ở node SQLite — không chặn đóng B21 nhưng phải sửa trước GT/G2. | 1 (X57) | 20/11/2026 |
| **GT** | — | I1–I18 (I15/I17/I18 ngoài phạm vi D23/D25) | **ĐẠT**. 15/15 bất biến trong phạm vi (I1–I14, I16) **phủ mạnh**: mỗi bất biến chỉ được ít nhất một assert hành vi cụ thể. Phá tinh thần: xóa `storage.key` prefix sẽ làm `test_storage_uri_matches_version:622` đỏ (I10); đảo hai đầu cạnh chiều vào sẽ làm `test_incoming_query_keeps_declared_endpoints:44` đỏ (I16); bỏ `assert_target_not_rebound` sẽ làm `test_relationship_target_not_rebound:551` và `test_declare_relationship_checks_rebind:344` cùng đỏ (I6); trả `duplicate=False` cho cùng checksum làm `test_same_content_does_not_create_version:169` đỏ (I8). I12 có thêm lớp AST ở `test_architecture_rules.py:325` chặn use case ghi quên `_record` — GB20 đã xác nhận ba phá-rồi-revert. `make test` 342 passed, 13 skipped; pylint 10.00/10. I15/I17/I18 giữ nguyên trạng thái ngoài phạm vi (I15 còn X55 chờ B16 nửa D4). | 0 | 20/11/2026 |
| **GB17** | B17 | X9, X28 | **Đạt cả 2 ID**. `uv run pytest` 339 passed, 13 skipped (delta +7 passed, +8 skipped so với baseline GB16+18 là 332/5). Đọc độc lập: `RedisDocumentLock` vị trí + `DependencyKind.REQUIRED_FOR_WRITE`, Lua CAS-extend/CAS-release qua `register_script`, token ULID `prefix="LCK"`, `asyncio.wait FIRST_COMPLETED` + hủy `op_task` + `ConcurrencyConflictError` khi mất lease, Lua CAS-release trong `finally`, `_probe_dependency` chỉ `PING` không bọc `_call` với URL cắt password; container `_build_locks(self) -> DocumentLockPort` chọn theo `lock.kind` dùng ở cả `_build_fake_ports`/`_build_real_ports`, `InMemoryDocumentLock(LockSettings \| None)` khớp timeout; executor `document_lock` + `resilience.lock`. Contract test 5 case × 2 param thấy đủ ở `--collect-only`; in_memory xanh, redis skip vì thiếu `DS_LOCK__REDIS_URL` (không có Docker trên máy). Fixture đọc `REDIS_URL` ở mức module trước `clean_env` autouse. Case 5 fail-fast với `acquire_timeout_seconds=0.1` → `ConcurrencyConflictError` cho cả hai hiện thực. `grep lock_timeout_seconds src/ configs/ tests/` rỗng. `make examples` 6/6 qua. **Sau khi dựng Docker trên máy**: chạy lại với `DS_LOCK__REDIS_URL=redis://localhost:6379/0` ra **347 passed, 5 skipped** — 8 case Redis trước đó chạy thật và pass (5 contract redis + 3 Redis-specific: PTTL thật, lease expiry tự mở, CAS-release token lạ không xoá key người khác). POC-26 đạt. | 0 | 20/11/2026 |

### Chi tiết hai gate của Phần A

**G0 — phủ phần tử và yêu cầu.** Phủ D1–D26 và I1–I18 là **đủ**. Lệch tìm được:

- **Bốn yêu cầu Bắt buộc không ai nhận trách nhiệm**: idempotency cho 3/5 endpoint ghi (X42), sự kiện thay đổi quyền (X41), nửa D4 của I15 (X55), và truy xuất lịch sử bản `Obsolete` (X47).
- **Năm mâu thuẫn chưa khai báo** với `c4-02`/`c4-04b`: nhóm `DependencyKind` (X45), điều kiện I11 của `DOWNLOAD_ONLY` (X46), khóa trong job phục hồi (X44), chữ ký port, danh sách endpoint — hai cái cuối là lệch tài liệu, đã bổ sung vào `c4-09` mục 16.
- `c4-09` thiếu tuyên bố phạm vi container (C3, C4, C5, C9, C11, C12 không xuất hiện) → đã thêm bảng phạm vi ở mục "Quy ước đọc".
- Bảng 2.2 của `c4-09` không đóng và lớp `infrastructure` không có cha (X56) → đã thêm D27 và bảng lớp không gắn với một D cụ thể.

**G1 — bản nền.** 17/20 phát biểu hiện trạng **đúng**. Ba phát biểu sai, đã sửa trong `c4-09`:

| Phát biểu sai | Sự thật |
|---|---|
| "`object_prefix` không ai đọc" | Có người đọc: `worker/reconcile.py:196`. Vấn đề thật là **hai nguồn sự thật tách nhau** — `StorageUri.for_version` hard-code `objects/`, nên đổi cấu hình làm job quét đi tìm sai chỗ trong khi đường ghi không đổi. Nguy hiểm hơn một knob chết vì nó có tác dụng một nửa |
| "I12 chỉ được phủ bằng substring" | I12 **có** test hành vi thật (`test_invariants.py:273-293`). Thứ chỉ được phủ bằng substring là **luật kiến trúc** "mọi `WriteUseCase` gọi `_record`" |
| "`mark_obsolete` ghi `approved_by` **và** `approved_at`" | Chỉ `approved_by` bị ghi. `approved_at = self.approved_at or when` với `when=None` ở mọi người gọi nên không ghi gì — nhưng là một cái bẫy chờ nổ |

Cộng bốn con số đếm sai (5 enum không phải 6, 11 model không phải 9, 6 executor không phải 7, sáu assert substring không phải ba), hai mã HTTP sai trong cây lỗi (X48, X49), và vài chỗ thiếu nhãn `(Bx)` — tất cả đã sửa.
