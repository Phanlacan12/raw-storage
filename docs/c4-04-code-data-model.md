# C4 — MỨC 4: CODE — MÔ HÌNH DỮ LIỆU VÀ RÀNG BUỘC

> **Tài liệu đi kèm:** [c4-04b-code-structure.md](c4-04b-code-structure.md) mô tả cấu trúc mã nguồn, sơ đồ lớp và interface hiện thực các bất biến ở đây.

> **Câu hỏi tài liệu này trả lời:** Mô hình dữ liệu logic của kho gồm những thực thể nào, các bất biến phải được code thực thi là gì, và mô hình đó ánh xạ vào catalog như thế nào.
> **Lưu ý:** Mức 4 trong C4 là mức dễ lạc hậu nhất. Tài liệu này chỉ mô tả **mô hình logic độc lập sản phẩm** và các bất biến, không mô tả class hiện thực cụ thể.
> **Tham chiếu báo cáo:** mục 2.3, 2.4, 3.6.

## 4.1. Mô hình dữ liệu logic

```mermaid
classDiagram
    class Collection {
        +string collection_id
        +string name
        +string type
        +string parent_collection_id
        +string owner
        +string department
    }

    class Document {
        +string document_id
        +string title
        +string description
        +string document_type
        +List~string~ tags
        +string language
        +string owner
        +string department
        +string collection_id
        +string classification
        +string access_policy
        +string retention_policy
        +string current_version_id
        +datetime created_at
    }

    class DocumentVersion {
        +string document_version_id
        +string document_id
        +string version_label
        +string status
        +string original_file_name
        +string format
        +long size_bytes
        +string checksum
        +string storage_uri
        +datetime created_at
        +string created_by
        +datetime approved_at
        +string approved_by
    }

    class Relationship {
        +string relation_type
        +string source_version_id
        +string target_version_id
        +datetime created_at
        +string created_by
    }

    class ProcessingIntent {
        +string request_id
        +string idempotency_key
        +IntentKind kind
        +string document_id
        +string document_version_id
        +string expected_checksum
        +string state
        +int retry_count
        +datetime updated_at
    }

    class IntentKind {
        <<enumeration>>
        upload
        status_change
        command
    }

    class MetadataSource {
        <<enumeration>>
        manual
        synced
        extracted
    }

    class MetadataChange {
        +string change_id
        +string target_id
        +string field_name
        +string old_value
        +string new_value
        +MetadataSource source
        +string actor
        +datetime changed_at
    }

    class DocumentTypeSchema {
        +string document_type
        +List~string~ required_fields
        +List~string~ optional_fields
        +List~string~ filterable_fields
        +int schema_version
    }

    class AccessPolicy {
        +string policy_id
        +string classification
        +List~string~ allowed_groups
        +List~string~ allowed_principals
        +bool require_proxy_download
    }

    class AuditEvent {
        +string event_id
        +string actor
        +string action
        +string target_id
        +string result
        +datetime occurred_at
    }

    Collection "1" --> "0..*" Document : chứa
    Collection "1" --> "0..*" Collection : cấp trên
    Document "1" --> "0..*" DocumentVersion : có phiên bản
    Document "1" --> "0..1" DocumentVersion : current_version_id
    DocumentVersion "1" --> "0..*" Relationship : là nguồn
    DocumentVersion "1" --> "0..*" Relationship : là đích
    Document "1" --> "0..1" AccessPolicy : áp dụng
    DocumentVersion "1" --> "0..1" ProcessingIntent : được tạo bởi
    ProcessingIntent --> IntentKind
    Document "1" --> "0..*" MetadataChange : lịch sử metadata
    DocumentVersion "1" --> "0..*" MetadataChange : lịch sử metadata
    DocumentTypeSchema "1" --> "0..*" Document : ràng buộc metadata
    MetadataChange --> MetadataSource
    AuditEvent ..> Document : tham chiếu
    AuditEvent ..> DocumentVersion : tham chiếu
```

**Ba điểm đọc sơ đồ cho đúng:**

1. **`Document` có thể có 0 phiên bản.** `POST /api/v1/documents` đăng ký tài liệu logic trước, phiên bản nội dung đến sau; tài liệu chưa có bản nào được duyệt thì `current_version_id` rỗng (mục 2.4 báo cáo). Vì vậy cardinality là `0..*`, không phải `1..*`.
2. **`Relationship` không có ID riêng.** Khoá tự nhiên là bộ ba `(relation_type, source_version_id, target_version_id)`; khai báo lại cùng bộ ba là thao tác idempotent. Không sinh ID thừa để tránh hai bản ghi cùng ngữ nghĩa mà khác ID.
3. **`MetadataChange` là nơi trả lời yêu cầu "phân biệt metadata nhập thủ công, đồng bộ từ nguồn và tự động trích xuất" (mục 2.3 báo cáo).** Nó khác `AuditEvent`: audit trả lời *ai đã làm gì*, `MetadataChange` trả lời *giá trị này từ đâu ra*. Lịch sử thay đổi metadata mô tả do catalog giữ (entity version của OpenMetadata); `MetadataChange` chỉ bắt buộc cho các trường trong `DocumentTypeSchema.required_fields` và các trường kiểm soát.

## 4.2. Bất biến phải được code thực thi

| # | Bất biến | Thành phần thực thi | Test case |
|---|---|---|---|
| I1 | `document_id` và `document_version_id` bất biến, không phụ thuộc `version_label`, tên file, collection hay đường dẫn | D6 | POC-03 |
| I2 | `version_label` duy nhất trong phạm vi một `document_id` | D6 | POC-03, 22 |
| I3 | Nội dung phiên bản cũ không bị ghi đè khi phát hành bản mới | D6, D13 | POC-03, 15 |
| I4 | Mỗi `document_id` có **tối đa một** `DocumentVersion` ở trạng thái `Approved`; chưa có bản duyệt thì `current_version_id` là rỗng | D7 | POC-10, 22 |
| I5 | Duyệt bản mới làm bản `Approved` trước đó chuyển `Obsolete` trong một thao tác logic có kiểm soát đồng thời | D7 | POC-10, 22 |
| I6 | `Relationship` luôn gắn vào `document_version_id` ở **cả hai đầu**, không trỏ vào `document_id` và không tự chuyển đích khi có phiên bản mới | D8 | POC-06, 09 |
| I7 | `Relationship` truy vấn được **hai chiều theo `relation_type`** | D8 (native catalog hoặc registry) | POC-06 |
| I8 | Upload lại cùng nội dung vào cùng `document_id` không tạo phiên bản nội dung mới; cập nhật metadata vẫn được phép và có audit | D5 | POC-13 |
| I9 | Hai `Document` khác nhau có thể cùng `checksum` nhưng giữ `document_id` riêng | D5 | POC-13 |
| I10 | `storage_uri` trỏ tới object bất biến ứng với đúng `document_version_id` | D13 | POC-01 |
| I11 | Tài liệu chưa xác định được quyền ở chế độ hạn chế; không tự động công khai | D9 | POC-04 |
| I12 | Mọi thay đổi `status`, `access_policy`, `current_version_id`, quan hệ đều có `AuditEvent` với actor và thời điểm | D16 | POC-10, 14 |
| I13 | Retry với cùng `idempotency_key` không sinh thêm `DocumentVersion` | D11 | POC-18, 21 |
| I14 | `latest` theo thứ tự phiên bản **khác** `current approved`; chỉ D7 được cập nhật trường bản hiện hành | D7 | POC-07, 10 |
| I15 | Mọi giá trị metadata bắt buộc đều ghi được `MetadataSource`; metadata tự động trích xuất **chỉ** từ thuộc tính kỹ thuật của file, không đọc nội dung | D4, D23 | POC-01, 24 |
| I16 | Truy vấn quan hệ hai chiều phải trả kèm `direction`; **không** được đảo `source_version_id`/`target_version_id` để biểu diễn chiều vào, vì như vậy là phát biểu sai một cạnh. Đã có test — xem B4. | D8 | POC-06 |
| I17 | Xóa tài liệu hoặc hết retention **không** xóa `AuditEvent` và lịch sử trạng thái; chỉ object và metadata khai thác bị thu hồi | D25, D16 | POC-11, 15, 25 |
| I18 | Tạo phiên bản bị từ chối nếu thiếu trường trong `DocumentTypeSchema.required_fields` của `document_type` tương ứng | D23 | POC-24 |

## 4.3. Máy trạng thái của Document Version

```mermaid
stateDiagram-v2
    [*] --> Draft: tạo phiên bản nội dung mới
    Draft --> Approved: duyệt — chỉ qua Document Service
    Draft --> Obsolete: loại bỏ bản nháp
    Approved --> Obsolete: có bản mới được duyệt, hoặc thu hồi phát hành
    Obsolete --> [*]
    Approved --> [*]

    note right of Approved
        Tối đa một bản Approved cho mỗi document_id.
        Cập nhật current_version_id trong cùng thao tác logic.
    end note

    note right of Obsolete
        Vẫn truy xuất được lịch sử nếu
        chưa hết retention và người dùng có quyền.
    end note
```

Chuyển `Obsolete` làm thay đổi điều kiện khai thác bản hiện hành, **không mặc nhiên xóa quyền xem lịch sử** (mục 2.6 báo cáo).

## 4.4. Nhóm metadata và vị trí gắn

| Nhóm | Trường ví dụ | Gắn với | Ai được ghi | `metadata_source` thường gặp |
|---|---|---|---|---|
| Technical | `file_name`, `format`, `size`, `checksum`, `storage_uri` | Document Version | Document Service (tự động trích xuất) | `extracted` |
| Descriptive | `title`, `description`, `document_type`, `tags`, `language` | Document | Owner qua Catalog UI/API hoặc Document Service | `manual` hoặc `synced` |
| Organizational | `owner`, `department`, `collection_id` | Document | Owner / Quản trị viên | `manual` hoặc `synced` |
| Lifecycle | `version_label`, `status`, `created_at`, `approved_at`, `approved_by` | Document Version | Document Service | `manual` (hành động có chủ thể) |
| Governance | `classification`, `access_policy`, `retention_policy` | Document | Document Service | `manual` hoặc `synced` |
| Relationship | `relation_type`, `source_version_id`, `target_version_id` | Document Version | Document Service | `manual` hoặc `synced` |
| Schema | `required_fields`, `optional_fields`, `filterable_fields` theo `document_type` | DocumentTypeSchema | Quản trị viên kho qua D23 | — |

`approved_at`/`approved_by` **chỉ** được ghi khi phiên bản thực sự đi qua trạng thái `Approved`. Loại bỏ một bản `Draft` (`Draft → Obsolete`) **không** được ghi hai trường này, vì khi đó chúng sẽ nói sai rằng bản nháp đã từng được duyệt.

Trường dùng để **lọc** bắt buộc phải có đường truy vấn đã kiểm chứng, không chỉ có khả năng lưu giá trị (POC-19).

## 4.5. Ánh xạ mô hình logic vào catalog

Bảng sau là **ứng viên ánh xạ**, không phải khẳng định sản phẩm hỗ trợ đầy đủ:

| Mô hình logic | OpenMetadata (ứng viên) | DataHub (ứng viên) |
|---|---|---|
| Kho/nguồn | Drive Service (Custom Drive) | Data platform/instance hoặc cách nhóm tương đương |
| Collection | Directory cấp trên | Container/Domain hoặc browse path — cần kiểm chứng |
| Document | Directory đại diện tài liệu | `Document` hoặc entity riêng; **không mặc định VersionSet hỗ trợ Document** |
| DocumentVersion | File entity riêng cho mỗi bản | Một entity riêng cho mỗi bản; kiểm chứng biểu diễn file gốc qua `storage_uri` |
| Metadata mở rộng | Custom properties trên File/Directory | Structured Properties, `documentInfo.customProperties` |
| `derived_from` | Lineage nếu File entity được API/UI hỗ trợ thực tế | Related Documents hoặc metadata/edge tùy kiểu entity |
| `references`, `supersedes` | Entity reference / custom properties hoặc registry relation | Related Documents / structured properties hoặc registry relation |
| `current_version_id` | Thuộc tính có kiểm soát trên Document/Directory | Thuộc tính có kiểm soát; **không đồng nhất với `latest` của VersionSet** |
| File gốc | S3 object nằm ngoài catalog | S3 object nằm ngoài catalog; `DataHubFile` là file đính kèm, không thay kho này |
| ProcessingIntent, AuditEvent, MetadataChange, outbox của Document Service | Nằm ngoài catalog, trong **C7 Service State Store**; audit đồng thời đẩy sang log tập trung. Chỉ log stream là **không đủ**: POC-14 cần truy vấn audit theo `document_id` | Tương tự: C7 + log |
| DocumentTypeSchema | Nguồn sự thật ở C7/cấu hình của D23; phần ánh xạ sang catalog là `OmCustomPropertyRegistrar.ensureProperties(...)` | Structured property definitions |

## 4.6. Quy ước object key

```text
s3://raw-documents/objects/{document_id}/{document_version_id}/source
```

- `original_file_name`, `version_label`, `collection_id` là **metadata**, không nằm trong key.
- Đổi tên tài liệu hoặc chuyển collection **không** làm đổi object key.
- S3 Versioning và Object Lock là **lớp bảo vệ**, không thay mô hình phiên bản tài liệu.
- Manifest intent (nếu chọn biến thể A của C7) nằm ở prefix riêng, ví dụ `s3://raw-documents/intents/{request_id}.json`, tách khỏi prefix `objects/`.

## 4.7. Ví dụ bản ghi một phiên bản

```json
{
  "document_version_id": "DOC-002-VER-0002",
  "document_id": "DOC-002",
  "collection_id": "PROJECT-A",
  "original_file_name": "srs.pdf",
  "title": "Software Requirements Specification",
  "document_type": "SRS",
  "version_label": "2.0",
  "status": "Approved",
  "classification": "internal",
  "checksum": "sha256:...",
  "storage_uri": "s3://raw-documents/objects/DOC-002/DOC-002-VER-0002/source",
  "relationships": [
    {"type": "derived_from", "target_version_id": "DOC-001-VER-0003"}
  ]
}
```

ID trong ví dụ mang tính minh họa. Khi triển khai nên dùng UUID/ULID hoặc cơ chế sinh ID không trùng để tránh phụ thuộc cách đặt `version_label`.

## 4.8. Ví dụ đồ thị quan hệ theo phiên bản

```mermaid
flowchart LR
    classDef approved fill:#EAF7EE,stroke:#2E8B57,color:#14402A
    classDef obsolete fill:#F2F2F2,stroke:#9E9E9E,color:#4A4A4A

    subgraph PA["Collection PROJECT-A"]
        direction TB
        U10["URD v1.0<br/>Obsolete"]
        U12["URD v1.2<br/>Approved"]
        S10["SRS v1.0<br/>Obsolete"]
        S20["SRS v2.0<br/>Approved"]
        A11["SAD v1.1<br/>Approved"]
    end

    U12 -.->|"supersedes"| U10
    S20 -.->|"supersedes"| S10
    S20 -->|"derived_from"| U12
    A11 -->|"references"| S20

    class U12,S20,A11 approved
    class U10,S10 obsolete
```

**Chiều của cạnh là một phần ngữ nghĩa, không phải cách vẽ:** `supersedes` đi từ **bản mới sang bản cũ** (`v1.2 supersedes v1.0`), `derived_from` đi từ **bản dẫn xuất sang bản nguồn** (`SRS v2.0 derived_from URD v1.2`), `references` đi từ **bản tham chiếu sang bản được tham chiếu**. Khi trả kết quả truy vấn hai chiều, cạnh vào phải được trả kèm `direction=incoming` và **giữ nguyên** `source_version_id`/`target_version_id` — đảo hai đầu để biểu diễn chiều vào là phát biểu sai một quan hệ (bất biến I16).

Khi SRS lên v2.1, quan hệ `SRS v2.0 --derived_from--> URD v1.2` **phải giữ nguyên**, không tự chuyển sang v2.1 (bất biến I6, test case POC-09).
