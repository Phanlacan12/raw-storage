# C4 MODEL — KHO LƯU TRỮ VÀ QUẢN LÝ RAW DATA DÙNG CHUNG

> **Nguồn gốc:** Mô hình hóa từ [bao-cao-kho-raw-data.md](bao-cao-kho-raw-data.md) — Đề xuất xây dựng kho lưu trữ và quản lý tài liệu dùng chung.
> **Trạng thái:** Kiến trúc tham chiếu ở mức **logic**. Mô hình này **không** chứng minh rằng mọi phần tử đã có sẵn trong catalog; các phần tử có nhãn `Cần PoC` phải được kiểm chứng theo Phụ lục B của báo cáo trước khi phê duyệt triển khai.
> **Quyết định đã chốt (17/11/2026):** catalog hiện thực là **OpenMetadata** (quyết định Q1). Mức Code được vẽ theo OpenMetadata; DataHub chỉ còn là đối chứng tài liệu ở L2 và ở mục 3.7 báo cáo.
> **Ngày lập:** 17/11/2026.

## 1. Bộ tài liệu

| Mức C4 | Tài liệu | Nội dung |
|---|---|---|
| — | [README.md](README.md) | Quy ước ký hiệu, trạng thái phần tử, cách đọc |
| **L1 — Context** | [c4-01-context.md](c4-01-context.md) | Kho raw data trong bối cảnh người dùng và hệ thống xung quanh |
| **L2 — Container** | [c4-02-container.md](c4-02-container.md) | Các container bên trong kho: Document Service, Metadata Catalog, Object Storage, intent store, gateway, event |
| **L3 — Component** | [c4-03-component-document-service.md](c4-03-component-document-service.md) | Thành phần bên trong Document Service và ranh giới ghi metadata |
| **L4 — Code (dữ liệu)** | [c4-04-code-data-model.md](c4-04-code-data-model.md) | Mô hình dữ liệu logic, máy trạng thái, bất biến, quy ước object key |
| **L4 — Code (mã nguồn)** | [c4-04b-code-structure.md](c4-04b-code-structure.md) | **Hiện thực theo OpenMetadata:** cấu trúc package, sơ đồ lớp lõi/port, adapter OpenMetadata, ánh xạ sang API OpenMetadata, hợp đồng API, bộ test |
| Dynamic | [c4-05-dynamic-views.md](c4-05-dynamic-views.md) | Luồng động: upload, duyệt, tra cứu/tải, thu hồi, đồng bộ, phục hồi lỗi |
| Deployment | [c4-06-deployment.md](c4-06-deployment.md) | Triển khai PoC một máy và triển khai on-premise |
| Index | [c4-07-element-catalog.md](c4-07-element-catalog.md) | Danh mục toàn bộ phần tử, ánh xạ mục báo cáo và test case PoC, quyết định còn mở |

Thứ tự đọc khuyến nghị: L1 → L2 → Dynamic → L3 → L4 (dữ liệu rồi mã nguồn) → Deployment. Người ra quyết định chỉ cần L1, L2 và bảng quyết định còn mở ở [c4-07](c4-07-element-catalog.md).

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

Mọi block Mermaid trong thư mục này phải parse sạch. Script và hướng dẫn: [tools/README.md](tools/README.md), chạy bằng [tools/check-mermaid.mjs](tools/check-mermaid.mjs). Lần kiểm tra ngày 17/11/2026: **22 sơ đồ, 0 lỗi**.

Ba quy tắc viết sơ đồ đã rút ra từ lỗi thực tế:

1. **Không dùng dấu `;`** trong text của `sequenceDiagram` — mermaid hiểu là dấu kết thúc câu lệnh và báo lỗi parse.
2. **Luôn bọc nhãn trong dấu nháy kép**: `A["text"]` và `-->|"text"|`, để ký tự `(`, `[`, `·`, `/` không phá cú pháp.
3. **Xuống dòng bằng `<br/>`**, kiểu generic trong `classDiagram` viết `List~string~`.

## 4. Nguyên tắc mô hình hóa đã áp dụng

Bốn nguyên tắc dưới đây lấy từ mục 1.4 và mục 3 của báo cáo, và là lý do tách container như ở L2:

1. **Tách nơi lưu file khỏi nơi quản lý metadata.** Object Storage và Metadata Catalog là hai container độc lập; không container nào là nguồn sự thật duy nhất cho cả hai loại dữ liệu.
2. **Một đường ghi duy nhất cho dữ liệu kiểm soát.** File, `status`, `access_policy`, `current_version_id` và quan hệ chỉ được ghi qua Document Service. Catalog chỉ nhận ghi trực tiếp với metadata mô tả (mục 3.5 báo cáo).
3. **Không giả định giao dịch nguyên tử.** Object Storage và Catalog không có ACID chung, nên mô hình bắt buộc có `Durable Intent Store` và `Reconciliation Worker` như phần tử hạng nhất, không phải chi tiết hiện thực.
4. **Độc lập sản phẩm.** Mọi truy cập catalog đi qua một lớp adapter; mọi truy cập storage chỉ dùng API S3 chuẩn. Nhờ đó thay OpenMetadata ↔ DataHub hoặc thay sản phẩm storage không làm đổi các container còn lại.

## 5. Giới hạn của mô hình

- Phần tử `Metadata Catalog` được mô hình hóa theo **vai trò**, không theo sản phẩm. Ứng viên ưu tiên là OpenMetadata, đối chứng là DataHub; chốt sau PoC (mục 3.10 báo cáo).
- `Durable Intent Store` có hai phương án hiện thực (S3 manifest hoặc registry DB/queue) và được vẽ là **một phần tử với hai biến thể**, chốt sau POC-18, 21, 22.
- `Search/Query Gateway`, `Admin UI`, `MCP Server` là container **tùy chọn**: chỉ xuất hiện trong kiến trúc cuối nếu PoC cho thấy catalog không đáp ứng (POC-17, 19, 20).
- Chuẩn hóa nội dung sang Markdown, OCR, tìm kiếm toàn văn, chunking/embedding/RAG **ngoài phạm vi**; chỉ vẽ ở L1 để thể hiện ranh giới và điểm nối cho giai đoạn sau.
