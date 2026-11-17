# C4 — MỨC 1: SYSTEM CONTEXT

> **Hệ thống trong phạm vi:** Kho lưu trữ và quản lý raw data dùng chung.
> **Câu hỏi sơ đồ này trả lời:** Ai dùng kho, kho nhận dữ liệu từ đâu, hệ thống nào khai thác dữ liệu của kho, và cái gì nằm ngoài phạm vi.
> **Tham chiếu báo cáo:** mục 1.1, 1.3, 2.1, 2.5, 2.6, 3.3, 7.1.

## 1.1. Sơ đồ ngữ cảnh

```mermaid
flowchart TB
    classDef builtin  fill:#E8F4FD,stroke:#2E7FB8,color:#0B3C5D
    classDef custom   fill:#FFF3E0,stroke:#E08A1E,color:#5C3A00
    classDef optional fill:#F3F0FB,stroke:#7A5FB8,color:#33265C
    classDef outscope fill:#F2F2F2,stroke:#9E9E9E,color:#4A4A4A,stroke-dasharray:4 3
    classDef person   fill:#EAF7EE,stroke:#2E8B57,color:#14402A

    P1["Người dùng nghiệp vụ / Owner tài liệu<br/>[Person]<br/>Đăng tài liệu, khai báo metadata mô tả"]
    P2["Quản trị viên kho<br/>[Person]<br/>Schema metadata, policy, đối soát chất lượng"]
    P3["Nhà phát triển ứng dụng khai thác<br/>[Person]<br/>Tích hợp qua API/sự kiện"]
    P4["Người phê duyệt tài liệu<br/>[Person]<br/>Quyết định Approved/Obsolete"]

    subgraph SYS["Kho raw data dùng chung — System Boundary"]
        CORE["Kho lưu trữ và quản lý raw data<br/>[Software System]<br/>Lưu file nguyên bản, metadata, phiên bản,<br/>trạng thái, quan hệ theo phiên bản,<br/>phân quyền đầu-cuối và API khai thác"]
    end

    X1["IdP / SSO của tổ chức<br/>[External System]<br/>Định danh người dùng và service account"]
    X2["Nguồn tài liệu hiện có<br/>[External System]<br/>File share, SharePoint, Drive, Git, S3"]
    X3["Knowledge Base (KB)<br/>[External System]<br/>Tiêu thụ bản Approved + access_policy"]
    X4["Service / AI Agent khai thác<br/>[External System]<br/>Truy vấn metadata và dữ liệu qua API/MCP"]
    X5["Ứng dụng nghiệp vụ khác<br/>[External System]<br/>Lọc tài liệu theo metadata và phiên bản"]
    X6["Nền tảng wiki<br/>[External System]<br/>Biên soạn, đọc; tham chiếu document_version_id"]
    X7["Monitoring / Log tập trung<br/>[External System]<br/>Nhận metric, audit, cảnh báo"]
    X8["Pipeline chuẩn hóa nội dung<br/>[External System — Ngoài phạm vi]<br/>Markdown, OCR, chunking, embedding"]

    P1 -->|"upload file gốc, sửa metadata mô tả [HTTPS]"| CORE
    P2 -->|"quản trị schema, policy, retention [HTTPS]"| CORE
    P4 -->|"ghi nhận chuyển trạng thái phiên bản [HTTPS]"| CORE
    P1 -->|"tìm và tải tài liệu theo quyền [HTTPS]"| CORE
    P3 -.->|"đọc tài liệu tích hợp, thử API [HTTPS]"| CORE

    X2 -->|"đồng bộ file và metadata nguồn [connector/API]"| CORE
    X1 -.->|"xác thực, cấp token, nhóm quyền [OIDC/SAML]"| CORE

    CORE -->|"cấp bản Approved, metadata, access_policy [REST]"| X3
    CORE -->|"cấp metadata và file theo quyền [REST/MCP]"| X4
    CORE -->|"trả kết quả lọc theo metadata/phiên bản [REST]"| X5
    CORE -.->|"cấp định danh phiên bản để trích dẫn [REST]"| X6
    CORE -->|"gửi audit, metric, cảnh báo đối soát [log/metric]"| X7
    CORE -.->|"giai đoạn sau: cấp raw file + document_version_id"| X8
    X8 -.->|"giai đoạn sau: đăng ký kết quả chuẩn hóa, liên kết về bản gốc"| CORE

    class P1,P2,P3,P4 person
    class CORE custom
    class X1,X2,X3,X4,X5,X7 builtin
    class X6 optional
    class X8 outscope
```

## 1.2. Người dùng

| ID | Vai trò | Mục đích sử dụng kho | Yêu cầu liên quan |
|---|---|---|---|
| P1 | Người dùng nghiệp vụ / Owner tài liệu | Đăng tài liệu, khai báo và duy trì metadata mô tả, tìm và tải tài liệu trong phạm vi quyền | 2.2, 2.3, 2.5, 6.3 |
| P2 | Quản trị viên kho | Định nghĩa schema metadata tối thiểu, chính sách truy cập, retention; kiểm tra chất lượng metadata theo mục 4.1; xử lý hàng đợi đối soát lỗi | 4.1, 6.3 |
| P3 | Nhà phát triển ứng dụng khai thác | Tích hợp ứng dụng với API/sự kiện của kho; không được ghi object trực tiếp | 2.5, 3.3 |
| P4 | Người phê duyệt tài liệu | Quyết định phát hành phiên bản. **Workflow xét duyệt nhiều bước nằm ngoài kho**; kho chỉ ghi nhận kết quả chuyển trạng thái và actor/time | 2.1, 2.4 |

## 1.3. Hệ thống bên ngoài

| ID | Hệ thống | Quan hệ với kho | Điểm cần làm rõ |
|---|---|---|---|
| X1 | IdP / SSO | Nguồn định danh duy nhất cho người dùng và service account; kho **không** tạo hệ tài khoản nghiệp vụ riêng | **[cần xác định hệ thống hiện có]** (mục 2.6) |
| X2 | Nguồn tài liệu hiện có | Nguồn tiếp nhận file và metadata; quyền ở nguồn phải ánh xạ được sang kho | Sau khi đưa vào kho, nguồn cũ chỉ đọc / song song / ngừng — **[cần xác định]** (mục 3.10) |
| X3 | Knowledge Base | Hệ thống khai thác đầu tiên; chỉ nhận bản `Approved` kèm `access_policy`, lưu `document_version_id` ổn định | POC-07, POC-11 |
| X4 | Service / AI Agent | Khai thác metadata và dữ liệu qua REST hoặc MCP với phạm vi quyền đã cấp | POC-04, POC-17 |
| X5 | Ứng dụng nghiệp vụ khác | Lọc tài liệu theo metadata, trạng thái, phiên bản, nhóm quản lý | POC-02, POC-19 |
| X6 | Nền tảng wiki (Nimbalyst, Wiki.js, BookStack, Outline, Confluence) | **Không** là kho dữ liệu gốc. Có thể dùng để biên soạn/xuất bản và trích dẫn `document_version_id` | mục 3.2.1 |
| X7 | Monitoring / Log tập trung | Nhận audit log, metric lưu trữ, lỗi đồng bộ, cảnh báo khi retry vượt ngưỡng | 2.7, 3.5 |
| X8 | Pipeline chuẩn hóa nội dung | **Ngoài phạm vi giai đoạn này.** Vẽ để xác định điểm nối: pipeline đọc raw file theo `document_version_id` và đăng ký kết quả về cùng catalog | 2.1, 3.2, 7.1 |

## 1.4. Ranh giới phạm vi

**Trong phạm vi**

- Tiếp nhận và lưu file đúng định dạng gốc: PDF, DOCX, XLSX, PPTX, Markdown, TXT và các định dạng tài liệu thông dụng.
- Quản lý metadata chuẩn và mở rộng, phiên bản nội dung, trạng thái `Draft/Approved/Obsolete`.
- Quan hệ theo phiên bản ở mức tối thiểu: `references`, `derived_from`, `supersedes`.
- Tìm kiếm theo metadata qua API, phân quyền đầu-cuối, audit, sự kiện thay đổi.

**Ngoài phạm vi (không thuộc tiêu chí nghiệm thu)**

- Chuẩn hóa nội dung về Markdown; OCR và parsing nội dung; **tìm kiếm toàn văn trong tài liệu**.
- Chunking, embedding, vector indexing, RAG, suy luận bằng AI.
- Workflow phê duyệt nhiều bước; kho chỉ ghi nhận trạng thái.
- Soạn thảo và cộng tác nội dung tài liệu (thuộc nền tảng wiki, X6).

## 1.5. Những nhu cầu buộc kho tồn tại

Sáu vấn đề ở mục 1.2 báo cáo là **giả thuyết cần khảo sát**, và cũng là các lực kiến trúc đã định hình L1:

| Vấn đề giả thuyết | Hệ quả trên sơ đồ ngữ cảnh |
|---|---|
| Tài liệu nằm ở nhiều nguồn | X2 là nhiều nguồn, nối vào một đầu mối duy nhất |
| Thiếu quy tắc mô tả tài liệu | Kho nắm schema metadata, không để từng ứng dụng tự định nghĩa |
| Thiếu quản lý phiên bản | `document_version_id` là định danh mà X3/X4/X5 phải lưu lại |
| Thiếu liên kết giữa tài liệu | Quan hệ theo phiên bản do kho quản lý, không phải hyperlink ở X6 |
| Quyền truy cập chưa thống nhất | X1 là nguồn định danh duy nhất; kho quyết định quyền trước khi cấp file |
| Mỗi ứng dụng tự kết nối nguồn | X3, X4, X5 chỉ nối tới kho, không nối trực tiếp vào X2 |
