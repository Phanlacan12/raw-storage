# C4 — MỨC 3: COMPONENT — DOCUMENT SERVICE

> **Container được phân rã:** C1 — Document Service (container duy nhất phải tự phát triển hoàn toàn).
> **Câu hỏi sơ đồ này trả lời:** Trong Document Service có những thành phần nào, thành phần nào thực thi ràng buộc nghiệp vụ, và phần nào cách ly phụ thuộc sản phẩm.
> **Tham chiếu báo cáo:** mục 2.4, 2.6, 3.4, 3.5, 3.9, 6.4.

## 3.1. Sơ đồ thành phần

```mermaid
flowchart TB
    classDef builtin  fill:#E8F4FD,stroke:#2E7FB8,color:#0B3C5D
    classDef custom   fill:#FFF3E0,stroke:#E08A1E,color:#5C3A00
    classDef poc      fill:#FDECEC,stroke:#C0392B,color:#5C1A14
    classDef optional fill:#F3F0FB,stroke:#7A5FB8,color:#33265C

    EXT_USR["Người dùng / Ứng dụng khai thác<br/>[Person / External System]"]
    EXT_SRC["Connector nguồn hiện có<br/>[External System]"]
    EXT_IDP["IdP / SSO<br/>[External System]"]

    subgraph DS["C1 — Document Service — Container Boundary"]
        direction TB

        subgraph APIL["Lớp giao tiếp"]
            direction LR
            D1["D1 API Layer<br/>[Component]<br/>Upload, Version, Status,<br/>Relationship, Download, Search, Admin"]
            D2["D2 Authentication<br/>[Component]<br/>Xác thực token OIDC,<br/>service account"]
            D3["D3 Authorization / PDP<br/>[Component]<br/>Quyết định quyền theo<br/>vai trò và thuộc tính"]
        end

        subgraph CORE["Lõi nghiệp vụ — nơi thực thi ràng buộc"]
            direction LR
            D4["D4 Upload Handler<br/>[Component]<br/>Nhận stream, giới hạn kích thước,<br/>trích metadata kỹ thuật"]
            D5["D5 Checksum & Dedup<br/>[Component]<br/>Tính checksum, phát hiện trùng<br/>trong cùng document_id"]
            D6["D6 Version Manager<br/>[Component]<br/>Sinh ID, duy nhất version_label,<br/>kiểm soát đồng thời"]
            D7["D7 Lifecycle Manager<br/>[Component]<br/>Draft → Approved → Obsolete,<br/>tối đa một bản hiện hành"]
            D8["D8 Relationship Manager<br/>[Component]<br/>relation_type, hai đầu là version,<br/>truy vấn ngược"]
            D9["D9 Access Policy Manager<br/>[Component]<br/>classification, access_policy,<br/>ánh xạ quyền từ nguồn"]
            D18["D18 Search Query Service<br/>[Component]<br/>Dịch truy vấn, lọc quyền kết quả"]
            D17["D17 Sync Orchestrator<br/>[Component]<br/>Điều phối đồng bộ từ nguồn"]
        end

        subgraph REL["Cấp phát và phục hồi"]
            direction LR
            D10["D10 Download Issuer<br/>[Component]<br/>Presigned URL ngắn hạn<br/>hoặc proxy stream"]
            D11["D11 Intent & Idempotency Manager<br/>[Component]<br/>request_id, idempotency_key,<br/>trạng thái xử lý bền vững"]
            D15["D15 Reconciliation Worker<br/>[Component]<br/>Đối soát hai chiều, retry"]
            D16["D16 Audit Logger<br/>[Component]<br/>Actor, thời điểm, hành động, kết quả"]
            D14["D14 Event Publisher<br/>[Component]<br/>Ghi outbox, phát sự kiện"]
        end

        subgraph ADPT["Lớp cách ly phụ thuộc"]
            direction LR
            D12["D12 Catalog Adapter<br/>[Component]<br/>Anti-corruption layer;<br/>cố định phiên bản API catalog"]
            D13["D13 Storage Adapter<br/>[Component]<br/>Chỉ dùng API S3 chuẩn"]
        end
    end

    C2["C2 Catalog Application<br/>[Container]"]
    C6[("C6 Object Storage S3<br/>[Datastore]")]
    C7[("C7 Durable Intent Store<br/>[Datastore]")]
    C10X["C10 Event Publisher / Outbox<br/>[Container]"]
    X7["Monitoring / Log<br/>[External System]"]

    EXT_USR -->|"REST/HTTPS"| D1
    EXT_SRC -->|"REST/HTTPS"| D1
    D2 -.->|"xác thực token"| EXT_IDP
    D1 --> D2
    D1 --> D3
    D1 --> D4
    D1 --> D6
    D1 --> D7
    D1 --> D8
    D1 --> D9
    D1 --> D10
    D1 --> D18
    EXT_SRC -.->|"lịch/sự kiện đồng bộ"| D17
    D17 --> D4

    D4 --> D5
    D4 --> D11
    D5 --> D6
    D6 --> D11
    D6 --> D13
    D6 --> D12
    D7 --> D12
    D7 --> D14
    D8 --> D12
    D9 --> D12
    D3 -.->|"đọc policy hiệu lực"| D9
    D10 --> D3
    D10 --> D13
    D18 --> D12
    D18 --> D3

    D11 --> C7
    D15 --> C7
    D15 --> D12
    D15 --> D13
    D12 --> C2
    D13 --> C6
    D14 --> C10X

    D1 --> D16
    D7 --> D16
    D10 --> D16
    D9 --> D16
    D16 --> X7
    D15 -->|"cảnh báo vượt ngưỡng retry"| X7

    class D1,D2,D3,D4,D5,D6,D7,D8,D9,D10,D11,D14,D15,D16,D17 custom
    class D12,D13 custom
    class D18 optional
    class C2,C6,C10X builtin
    class C7 poc
    class X7 builtin
    class EXT_USR,EXT_SRC,EXT_IDP builtin
```

## 3.2. Danh mục thành phần

| ID | Thành phần | Trách nhiệm | Ràng buộc phải thực thi | Test case |
|---|---|---|---|---|
| D1 | API Layer | Phơi bày API nghiệp vụ: `POST /documents`, `POST /documents/{id}/versions`, `POST /versions/{id}/status`, `POST /relationships`, `GET /versions/{id}/download`, `GET /search`, API quản trị | Mọi API ghi đều yêu cầu `Idempotency-Key`; phân trang bắt buộc cho API danh sách | POC-01, 02, 03 |
| D2 | Authentication | Xác thực token người dùng và service account từ IdP | Không tạo hệ tài khoản nghiệp vụ riêng | POC-04 |
| D3 | Authorization / PDP | Quyết định quyền cho từng hành động: xem metadata, tìm kiếm, tải, sửa, chuyển trạng thái, chia sẻ | Tài liệu chưa xác định được quyền ở chế độ hạn chế, chỉ owner và quản trị viên được ủy quyền; không tự động công khai | POC-04, 17, 20 |
| D4 | Upload Handler | Nhận file dạng stream, kiểm tra định dạng/kích thước, trích xuất metadata kỹ thuật | **Không đọc nội dung tài liệu**; chỉ metadata kỹ thuật như định dạng, kích thước, checksum | POC-01 |
| D5 | Checksum & Dedup | Tính `checksum` và so với các phiên bản của cùng `document_id` | Upload lại cùng nội dung vào cùng tài liệu **không** tạo phiên bản mới; hai tài liệu khác nhau cùng checksum vẫn giữ `document_id` riêng | POC-13 |
| D6 | Version Manager | Sinh `document_version_id` bất biến, bảo đảm `version_label` duy nhất trong tài liệu, kiểm soát hai request đồng thời | Không ghi đè nội dung bản cũ; ID không phụ thuộc `version_label`, tên file hay collection | POC-03, 22 |
| D7 | Lifecycle Manager | Thực thi `Draft → Approved → Obsolete`; khi duyệt bản mới thì chuyển bản `Approved` trước đó sang `Obsolete` trong một thao tác logic có kiểm soát đồng thời | Tối đa một bản `Approved` hiện hành; ghi actor, thời điểm, trạng thái trước–sau | POC-10, 22 |
| D8 | Relationship Manager | Tạo và truy vấn `references`, `derived_from`, `supersedes` với `source_version_id`, `target_version_id` | Liên kết gắn đúng phiên bản ở cả hai đầu, **không tự chuyển sang phiên bản mới**; truy vấn được hai chiều theo loại quan hệ | POC-06, 09 |
| D9 | Access Policy Manager | Quản lý `classification`, `access_policy`, `retention_policy`; ánh xạ quyền từ nguồn sang kho | Quyền xem metadata **không** đồng nghĩa quyền tải file | POC-04, 11, 17 |
| D10 | Download Issuer | Cấp link tải có thời hạn cho tài liệu thông thường; proxy stream cho dữ liệu cần thu hồi ngay | Kiểm tra policy ngay trước khi cấp; ghi audit mỗi lần cấp; đo được cửa sổ hiệu lực của link đã phát hành | POC-04, 23 |
| D11 | Intent & Idempotency Manager | Tạo và cập nhật intent bền vững; bảo đảm retry không sinh phiên bản trùng | Intent phải bền vững **trước** khi ghi object; không giữ trạng thái trong RAM | POC-08, 18, 21 |
| D12 | **Catalog Adapter** | Toàn bộ giao tiếp với catalog đi qua đây: tạo/đọc entity, custom properties, quan hệ, search | Cố định phiên bản catalog; thay OpenMetadata ↔ DataHub chỉ đổi adapter | mục 6.4 |
| D13 | **Storage Adapter** | Ghi/đọc object, presign, kiểm tra object lock và versioning | Chỉ dùng API S3 chuẩn, không dùng tính năng mở rộng riêng của một sản phẩm | POC-01, 15 |
| D14 | Event Publisher | Ghi bản ghi outbox cho mọi thay đổi có ý nghĩa với downstream | Sự kiện phải có `document_version_id` và loại thay đổi; downstream phát hiện được sự kiện thất lạc | POC-11 |
| D15 | Reconciliation Worker | Đối soát hai chiều và retry; chuyển sang xử lý thủ công khi vượt ngưỡng | Có cảnh báo; không tự tạo phiên bản mới khi đối soát | POC-08, 18, 21 |
| D16 | Audit Logger | Ghi log tải, sửa mô tả, chuyển trạng thái, thay đổi quyền, lỗi | Audit đủ để trả lời POC-14 trên một tài liệu cụ thể | POC-14 |
| D17 | Sync Orchestrator | Điều phối đồng bộ từ nguồn hiện có qua đường ghi chính | Sửa file ở nguồn tạo **phiên bản nội dung mới**, không đổi bản đã đăng ký | POC-12 |
| D18 | Search Query Service | Dịch truy vấn nghiệp vụ sang search API của catalog và lọc quyền trên kết quả | Chỉ bắt buộc nếu catalog không phân quyền được kết quả; khi đó có thể tách thành container C9 | POC-02, 17, 19 |

## 3.3. Vì sao cần Document Service — ánh xạ sang thành phần

| Khoảng trống của catalog (mục 3.2 báo cáo) | Thành phần lấp khoảng trống |
|---|---|
| Catalog không lưu file | D13 + C6 Object Storage; catalog chỉ giữ `storage_uri`, `checksum` |
| Version của catalog là lịch sử metadata, không phải version nội dung | D6 tạo entity riêng cho mỗi phiên bản nội dung |
| Quyền xem metadata khác quyền tải file | D3 + D9 + D10 |
| Không có luồng upload file | D1 + D4 + D5 |
| Search và UI của catalog có giới hạn theo custom field | D18, có thể nâng thành C9 Gateway |
| Không có giao dịch nguyên tử giữa storage và catalog | D11 + D15 + C7 |

## 3.4. Ranh giới cập nhật metadata

```mermaid
flowchart LR
    classDef custom   fill:#FFF3E0,stroke:#E08A1E,color:#5C3A00
    classDef builtin  fill:#E8F4FD,stroke:#2E7FB8,color:#0B3C5D
    classDef poc      fill:#FDECEC,stroke:#C0392B,color:#5C1A14

    OWNER["Owner tài liệu"]
    ADMIN["Quản trị viên kho"]
    DSX["Document Service<br/>D6 D7 D8 D9"]
    CATX["Catalog UI / API"]
    FIELDS_A["Trường mô tả<br/>title · description · tags · language<br/>department · owner"]
    FIELDS_B["Trường kiểm soát<br/>document_id · document_version_id<br/>storage_uri · checksum · status<br/>current_version_id · access_policy · relationship"]

    OWNER -->|"được phép, có audit"| CATX
    CATX -->|"ghi trực tiếp"| FIELDS_A
    OWNER -->|"yêu cầu thay đổi"| DSX
    ADMIN -->|"yêu cầu thay đổi"| DSX
    DSX -->|"ghi có kiểm soát"| FIELDS_B
    CATX -. "phải bị chặn — POC-20" .-> FIELDS_B

    class DSX custom
    class CATX builtin
    class FIELDS_B poc
```

Service account của catalog và connector **không** được bypass ràng buộc này. Nếu cấu hình quyền của catalog không chặn được, phải thu hẹp quyền ghi của catalog xuống mức chỉ-mô-tả hoặc đặt catalog ở chế độ chỉ nhận ghi từ Document Service.

## 3.5. Xử lý lỗi giữa Object Storage và Catalog

Không mô tả việc ghi file và đăng ký metadata là một giao dịch nguyên tử. Chuỗi trạng thái của một upload:

```mermaid
stateDiagram-v2
    [*] --> Received: D11 ghi intent bền vững
    Received --> ObjectStored: D13 ghi object thành công
    ObjectStored --> CatalogRegistered: D12 đăng ký entity thành công
    CatalogRegistered --> Completed: xác nhận checksum và cập nhật intent
    Received --> RetryPending: lỗi ghi object
    ObjectStored --> RetryPending: lỗi đăng ký catalog
    RetryPending --> ObjectStored: D15 retry idempotent
    RetryPending --> CatalogRegistered: D15 retry idempotent
    RetryPending --> Failed: vượt ngưỡng retry, cảnh báo và xử lý thủ công
    Completed --> [*]
    Failed --> [*]
```

Nguyên tắc bắt buộc:

- Intent được ghi **trước** khi ghi object, gồm `request_id`, `document_version_id`, checksum dự kiến và trạng thái.
- Dùng key bất biến, `idempotency_key` và kiểm tra điều kiện khi tạo object/entity để retry không sinh phiên bản trùng.
- Job đối soát chạy cả hai chiều: object chưa đăng ký; entity trỏ tới object mất hoặc hỏng; intent bị gián đoạn.
- Nếu chỉ dùng manifest trên S3, PoC phải kiểm chứng race condition, khả năng liệt kê/đối soát và phục hồi sau khi Document Service restart. Không đạt thì **bổ sung registry database**, không cố giữ tiêu chí “service không có database” (mục 3.5 báo cáo).
