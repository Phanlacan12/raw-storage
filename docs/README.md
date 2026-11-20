# C4 MODEL — KHO LƯU TRỮ VÀ QUẢN LÝ RAW DATA DÙNG CHUNG

> **Nguồn gốc:** Mô hình hóa từ [bao-cao-kho-raw-data.md](bao-cao-kho-raw-data.md) — Đề xuất xây dựng kho lưu trữ và quản lý tài liệu dùng chung.
> **Trạng thái:** Kiến trúc tham chiếu ở mức **logic**. Mô hình này **không** chứng minh rằng mọi phần tử đã có sẵn trong catalog; các phần tử có nhãn `Cần PoC` phải được kiểm chứng theo Phụ lục B của báo cáo trước khi phê duyệt triển khai.
> **Quyết định đã chốt (17/11/2026):** catalog hiện thực là **OpenMetadata** (quyết định Q1). Mức Code được vẽ theo OpenMetadata; DataHub chỉ còn là đối chứng tài liệu ở L2 và ở mục 3.7 báo cáo.
> **Ngày lập:** 17/11/2026. **Rà soát kiến trúc và cập nhật:** 19/11/2026, xem [mục 6](#6-lịch-sử-rà-soát).

> **Lưu ý khi đọc bản 19/11/2026:** mô hình đã bổ sung phần tử cho những yêu cầu "Bắt buộc" ở chương II báo cáo mà trước đó không có phần tử nào nhận trách nhiệm — D23 kiểm tra hợp lệ metadata, D24 quản trị collection, D25 retention và xóa, C7 nâng thành Service State Store, C13 khóa phân tán. **Đây là thiết kế, chưa phải mã nguồn đã có**; trạng thái hiện thực xem [c4-08](c4-08-tra-soat-code-vs-thiet-ke.md).

## 1. Bộ tài liệu

| Mức C4 | Tài liệu | Nội dung |
|---|---|---|
| — | [README.md](README.md) | Quy ước ký hiệu, trạng thái phần tử, cách đọc |
| **L1 — Context** | [c4-01-context.md](c4-01-context.md) | Kho raw data trong bối cảnh người dùng và hệ thống xung quanh |
| **L2 — Container** | [c4-02-container.md](c4-02-container.md) | Các container bên trong kho: Document Service, reconciler, outbox dispatcher, Metadata Catalog, Object Storage, Service State Store, gateway, khóa phân tán |
| **L3 — Component** | [c4-03-component-document-service.md](c4-03-component-document-service.md) | Thành phần bên trong Document Service, C8 và C10; ranh giới ghi metadata |
| **L4 — Code (dữ liệu)** | [c4-04-code-data-model.md](c4-04-code-data-model.md) | Mô hình dữ liệu logic, máy trạng thái, bất biến, quy ước object key |
| **L4 — Code (mã nguồn)** | [c4-04b-code-structure.md](c4-04b-code-structure.md) | **Hiện thực theo OpenMetadata:** cấu trúc package, sơ đồ lớp lõi/port, adapter OpenMetadata, ánh xạ sang API OpenMetadata, hợp đồng API, bộ test |
| **LLD — bản thi công** | [c4-09-lld.md](c4-09-lld.md) | Chữ ký method đầy đủ, sequence ở mức method, ERD của C7, bản đồ executor, đường đi của `Deadline`, ánh xạ bất biến → lớp → test, quy ước code |
| Dynamic | [c4-05-dynamic-views.md](c4-05-dynamic-views.md) | Luồng động: upload, duyệt, tra cứu/tải, thu hồi, đồng bộ, phục hồi lỗi |
| Deployment | [c4-06-deployment.md](c4-06-deployment.md) | Triển khai PoC một máy và triển khai on-premise |
| Index | [c4-07-element-catalog.md](c4-07-element-catalog.md) | Danh mục toàn bộ phần tử, ánh xạ mục báo cáo và test case PoC, quyết định còn mở |
| Đối soát | [c4-08-tra-soat-code-vs-thiet-ke.md](c4-08-tra-soat-code-vs-thiet-ke.md) | Code đã hiện thực tới đâu, lệch chỗ nào và vì sao, kết quả kiểm chứng đã chạy |

Thứ tự đọc khuyến nghị: L1 → L2 → Dynamic → L3 → L4 (dữ liệu rồi mã nguồn) → LLD → Deployment. Người viết code đọc [c4-09](c4-09-lld.md); `c4-04b` trả lời *vì sao tách như vậy*, `c4-09` trả lời *viết gì*. Người ra quyết định chỉ cần L1, L2 và bảng quyết định còn mở ở [c4-07](c4-07-element-catalog.md).

## 2. Quy ước ký hiệu

Sơ đồ vẽ bằng **Mermaid flowchart** thay vì cú pháp `C4Context` để bảo đảm render ổn định trên GitHub, VS Code và trình xem Markdown nội bộ. Quy ước C4 vẫn được giữ nguyên:

- Mỗi node ghi `[Loại phần tử]` ở dòng thứ hai: `Person`, `External System`, `Container`, `Component`, `Datastore`.
- Dòng thứ ba (nếu có) ghi công nghệ dự kiến hoặc trạng thái.
- Mũi tên liền `-->` là **đường chính, bắt buộc**; mũi tên nét đứt `-.->` là đường **tùy chọn / phụ thuộc kết quả PoC / chỉ dành cho đối tượng đã được cấp quyền**.
- Nhãn mũi tên ghi hành động và giao thức, dạng `hành động [giao thức]`.
- Biên hệ thống (`subgraph`) ứng với **boundary** trong C4: `Kho raw data` là system boundary; bên trong là container boundary.

### Màu và trạng thái phần tử

| Nhãn trạng thái | Ý nghĩa | Lớp style |
|---|---|---|
| `Có sẵn` | Chức năng sản phẩm/hạ tầng cung cấp, chỉ cần cấu hình | `builtin` |
| `Tự phát triển` | Phải tự xây dựng, tính vào công phát triển ở mục 5.3 báo cáo | `custom` |
| `Cần PoC` | Khả năng đáp ứng chưa được xác nhận, phụ thuộc kết quả Phụ lục B | `poc` |
| `Tùy chọn` | Chỉ bổ sung nếu PoC chứng minh là cần thiết | `optional` |
| `Ngoài phạm vi` | Thuộc giai đoạn sau, vẽ để thể hiện ranh giới | `outscope` |

Khai báo style dùng chung trong các sơ đồ:

```text
classDef builtin  fill:#E8F4FD,stroke:#2E7FB8,color:#0B3C5D
classDef custom   fill:#FFF3E0,stroke:#E08A1E,color:#5C3A00
classDef poc      fill:#FDECEC,stroke:#C0392B,color:#5C1A14
classDef optional fill:#F3F0FB,stroke:#7A5FB8,color:#33265C
classDef outscope fill:#F2F2F2,stroke:#9E9E9E,color:#4A4A4A,stroke-dasharray:4 3
classDef person   fill:#EAF7EE,stroke:#2E8B57,color:#14402A
```

## 3. Kiểm tra sơ đồ trước khi commit

Mọi block Mermaid trong thư mục này phải parse sạch. Script và hướng dẫn: [tools/README.md](tools/README.md), chạy bằng [tools/check-mermaid.mjs](tools/check-mermaid.mjs). Chạy bằng `make docs-check`. Lần kiểm tra ngày 19/11/2026: **56 sơ đồ, 0 lỗi**.

Ba quy tắc viết sơ đồ đã rút ra từ lỗi thực tế:

1. **Không dùng dấu `;`** trong text của `sequenceDiagram` — mermaid hiểu là dấu kết thúc câu lệnh và báo lỗi parse.
2. **Luôn bọc nhãn trong dấu nháy kép**: `A["text"]` và `-->|"text"|`, để ký tự `(`, `[`, `·`, `/` không phá cú pháp.
3. **Xuống dòng bằng `<br/>`**, kiểu generic trong `classDiagram` viết `List~string~`.

## 4. Nguyên tắc mô hình hóa đã áp dụng

Năm nguyên tắc dưới đây lấy từ mục 1.4 và mục 3 của báo cáo, và là lý do tách container như ở L2:

1. **Tách nơi lưu file khỏi nơi quản lý metadata.** Object Storage và Metadata Catalog là hai container độc lập; không container nào là nguồn sự thật duy nhất cho cả hai loại dữ liệu.
2. **Một đường ghi duy nhất cho dữ liệu kiểm soát.** File, `status`, `access_policy`, `current_version_id` và quan hệ chỉ được ghi qua Document Service. Catalog chỉ nhận ghi trực tiếp với metadata mô tả (mục 3.5 báo cáo).
3. **Không giả định giao dịch nguyên tử.** Object Storage và Catalog không có ACID chung, nên mô hình bắt buộc có `Service State Store` và `Reconciliation Worker` như phần tử hạng nhất, không phải chi tiết hiện thực. Điều này đúng cho **cả** luồng upload và luồng chuyển trạng thái: một lượt duyệt gồm ba lệnh ghi xuống catalog và cũng cần intent để phục hồi.
4. **Độc lập sản phẩm.** Mọi truy cập catalog đi qua một lớp adapter; mọi truy cập storage chỉ dùng API S3 chuẩn. Nhờ đó thay OpenMetadata ↔ DataHub hoặc thay sản phẩm storage không làm đổi các container còn lại. Quy tắc nghiệp vụ — kể cả **lọc quyền kết quả tra cứu** — nằm ở `domain`, không ở adapter, để đổi sản phẩm không làm mất quy tắc.
5. **Một phần tử có đúng một cha.** Thứ đã là container ở L2 thì không được vẽ lại thành component bên trong container khác ở L3. C8 và C10 là tiến trình riêng, nên ở L3 chúng có biên riêng chứ không nằm trong biên của C1.

## 5. Giới hạn của mô hình

- Phần tử `Metadata Catalog` được mô hình hóa theo **vai trò**; sản phẩm đã chốt là OpenMetadata (Q1), DataHub chỉ còn là đối chứng tài liệu.
- `C7 Service State Store` chứa bốn loại trạng thái: intent, quan hệ (nếu Q4 chọn registry), audit, outbox. Biến thể manifest trên S3 chỉ phục vụ được schema intent, nên đó là **phương án dự phòng hẹp**, không phải một kiến trúc tương đương; chốt sau POC-18, 21, 22.
- `Search/Query Gateway`, `Admin UI`, `MCP Server` là container **tùy chọn**: chỉ xuất hiện trong kiến trúc cuối nếu PoC cho thấy cần (POC-16, 17, 19, 20). Việc **lọc quyền kết quả tra cứu** thì không tùy chọn — nó luôn xảy ra, ở D18 trong C1 hoặc ở C9.
- `C13 Distributed Lock` là tùy chọn **chỉ khi** chạy một instance C1; từ hai instance trở lên nó là bắt buộc (Q12).
- Mức Code (`c4-04b`) lạc hậu nhanh nhất. Tên lớp ở đó là hợp đồng thiết kế và phải có cổng CI đối chiếu với `src/`; lần rà soát 19/11/2026 tìm ra 12 tên lớp không còn tồn tại trong mã nguồn. [c4-09](c4-09-lld.md) mục 15.6 định nghĩa cổng đó.
- `c4-09` mô tả **trạng thái đích**. Mỗi phần tử chưa có trong `src/` được gắn nhãn `(Bx)` theo bước refactor sẽ tạo ra nó; trạng thái thật ở [c4-08](c4-08-tra-soat-code-vs-thiet-ke.md) mục 2b. Đọc `c4-09` mà bỏ nhãn đó sẽ tưởng hệ thống đã có những thứ chưa viết.
- Chuẩn hóa nội dung sang Markdown, OCR, tìm kiếm toàn văn, chunking/embedding/RAG **ngoài phạm vi**; chỉ vẽ ở L1 để thể hiện ranh giới và điểm nối cho giai đoạn sau.

## 6. Lịch sử rà soát

### 19/11/2026 — rà soát kiến trúc, đối chiếu đề bài và mã nguồn

Sửa ba nhóm lỗi. Mọi thay đổi đều nằm trong các tài liệu C4; đề bài [bao-cao-kho-raw-data.md](bao-cao-kho-raw-data.md) **không** bị sửa.

**Nhóm A — nhất quán giữa các mức C4**

| # | Lỗi | Đã sửa thành |
|---|---|---|
| A1 | C8 và C10 vừa là container ở L2 vừa là component D15/D14 bên trong C1 ở L3 | Ba biên riêng ở [c4-03](c4-03-component-document-service.md); D15 thuộc C8, D26 thuộc C10, D14 đổi tên thành Outbox Writer (ghi outbox trong request) |
| A2 | Không có datastore nào cho audit, outbox và bảng quan hệ, trong khi mô hình vẫn khẳng định "trạng thái nằm ở C7" | C7 nâng thành **Service State Store** với 4 schema; đưa vào [c4-06](c4-06-deployment.md) mục 6.2, 6.3, 6.4, 6.5 và phạm vi backup |
| A3 | C7 "một phần tử hai biến thể" trong khi biến thể A nằm *bên trong* C6 | Nói rõ biến thể A chỉ phục vụ schema intent, là phương án dự phòng hẹp |
| A4 | D18 bị gắn nhãn tùy chọn, trái mục 2.6 báo cáo | D18 **bắt buộc**; chỉ việc tách thành C9 là tùy chọn |
| A5 | Lớp adapter ở L3 chỉ có catalog và storage, không khớp L4 | Thêm D19 relationship store, D20 state store, D21 policy, D22 lock |
| A6 | "Khóa phân tán" là phụ thuộc ngoài tiến trình nhưng không có phần tử nào, trong khi deployment vẫn vẽ nhiều instance | Thêm **C13 Distributed Lock**, quyết định Q12, test case POC-26 |
| A7 | [c4-06](c4-06-deployment.md) còn nhánh DataHub và vẽ service/reconciler như container compose | Sơ đồ 6.1 vẽ đúng stack thật: 4 container hạ tầng + 3 tiến trình trên máy, và đánh dấu hai khoảng trống IdP/mock downstream |

**Nhóm B — ngữ nghĩa mô hình dữ liệu**

| # | Lỗi | Đã sửa thành |
|---|---|---|
| B1 | Sơ đồ 4.8 vẽ `supersedes` ngược chiều (bản cũ supersedes bản mới) | Đảo chiều cạnh và viết rõ quy ước chiều cho cả ba loại quan hệ |
| B2 | Cardinality `Document 1 → 1..* DocumentVersion` trái với API đăng ký tài liệu trước, phiên bản sau | Đổi thành `0..*` |
| B3 | `Relationship` có `relationship_id` không dùng; audit được mô tả là "C7 + log" | Dùng khoá tự nhiên ba thành phần; audit nói rõ lưu ở C7 **và** đẩy sang log |
| B4 | Không có bất biến nào về chiều quan hệ khi truy vấn hai chiều | Thêm I16 |

**Nhóm C — yêu cầu "Bắt buộc" của đề bài chưa có chủ**

| Yêu cầu | Mục đề bài | Phần tử mới |
|---|---|---|
| Kiểm tra hợp lệ metadata; bộ bắt buộc/tùy chọn theo loại tài liệu | 2.2, 2.3 | **D23**, `DocumentTypeSchema`, bất biến I18, POC-24 |
| Phân biệt metadata thủ công / đồng bộ / trích xuất và truy nguồn gốc | 2.3 | `MetadataChange`, `MetadataSource`, bất biến I15, POC-24 |
| Tổ chức tài liệu theo collection | 2.2, 2.8 | **D24** và nhóm endpoint `/collections`, POC-27 |
| Vòng đời file: retention, thu hồi, xóa, khôi phục | 2.2, 2.5, 2.6 | **D25**, [luồng 8](c4-05-dynamic-views.md#8-hết-retention-và-xóa-vật-lý), bất biến I17, POC-25 |
| Tìm theo tên và owner (POC-02) | 2.2 | Mở rộng tập trường bắt buộc lọc được ở [c4-04b mục 8](c4-04b-code-structure.md#8-tìm-kiếm-nơi-rủi-ro-tập-trung) |
| Không giữ toàn bộ file trong bộ nhớ | 2.7, 11.6 | Nêu thành ràng buộc kiểm chứng được, POC-28 |

**Nhóm D — trôi tên lớp ở mức Code:** 12 tên lớp trong [c4-04b](c4-04b-code-structure.md) không tồn tại trong `src/` đã được sửa về tên thật (`Jdbc*` → `Sqlite*`, các `*Controller` → router thật, `OmPermissionResultFilter` → `SearchPage.filtered`, 6 indicator riêng → `AdapterHealthIndicator`, `BackoffCalculator` → `BackoffStrategy`), cùng chữ ký port và danh sách endpoint. Thêm cổng CI thứ tư: tên lớp trong tài liệu phải tồn tại trong mã nguồn.
