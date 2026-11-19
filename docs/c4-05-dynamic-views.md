# C4 — DYNAMIC VIEWS: CÁC LUỒNG NGHIỆP VỤ CHÍNH

> **Câu hỏi tài liệu này trả lời:** Các container và thành phần phối hợp theo thứ tự nào trong từng tình huống, và ở bước nào xuất hiện rủi ro cần PoC.
> **Tham chiếu báo cáo:** mục 2.4, 2.6, 3.3, 3.9, Phụ lục B.

Danh sách luồng:

| # | Luồng | Test case liên quan |
|---|---|---|
| [1](#1-upload-và-đăng-ký-phiên-bản) | Upload và đăng ký phiên bản | POC-01, 08, 13, 18, 21 |
| [2](#2-duyệt-phiên-bản-có-cạnh-tranh-đồng-thời) | Duyệt phiên bản, có cạnh tranh đồng thời | POC-10, 22 |
| [3](#3-tra-cứu-và-tải-file-theo-quyền) | Tra cứu và tải file theo quyền | POC-02, 04, 17, 19 |
| [4](#4-kb-tiêu-thụ-bản-approved) | KB tiêu thụ bản Approved | POC-05, 06, 07 |
| [5](#5-thu-hồi-quyền-và-xóa-tài-liệu-đã-cấp) | Thu hồi quyền và xóa tài liệu đã cấp | POC-11, 23 |
| [6](#6-đồng-bộ-từ-nguồn-hiện-có) | Đồng bộ từ nguồn hiện có | POC-12 |
| [7](#7-phục-hồi-sau-lỗi-một-phía) | Phục hồi sau lỗi một phía | POC-08, 18, 21 |
| [8](#8-hết-retention-và-xóa-vật-lý) | Hết retention và xóa vật lý | POC-15, 25 |

---

## 1. Upload và đăng ký phiên bản

```mermaid
sequenceDiagram
    autonumber
    actor U as Owner tài liệu
    participant DS as C1 Document Service
    participant IN as C7 State Store
    participant S3 as C6 Object Storage
    participant CAT as C2 Catalog
    participant OB as C10 Outbox

    U->>DS: POST /documents/{id}/versions + file + metadata<br/>Idempotency-Key
    DS->>DS: D2 xác thực, D3 kiểm tra quyền ghi
    DS->>DS: D5 tính checksum, so với các bản của cùng document_id
    alt Checksum trùng trong cùng document
        DS-->>U: 200 không tạo phiên bản mới, cho cập nhật metadata (POC-13)
    else Nội dung mới
        DS->>DS: D6 sinh document_version_id, kiểm tra version_label duy nhất
        DS->>IN: ghi intent Received: request_id, version_id, checksum dự kiến
        IN-->>DS: xác nhận bền vững
        DS->>S3: PUT objects/{document_id}/{document_version_id}/source (stream, multipart)
        S3-->>DS: ETag + checksum thực tế
        DS->>DS: đối chiếu checksum thực tế với checksum dự kiến
        DS->>IN: cập nhật trạng thái ObjectStored
        DS->>CAT: tạo entity phiên bản + metadata kiểm soát (D12 adapter)
        CAT-->>DS: entity id
        DS->>IN: cập nhật trạng thái CatalogRegistered
        DS->>IN: cập nhật Completed
        DS->>OB: ghi sự kiện version.created
        DS->>DS: D16 ghi audit
        DS-->>U: 201 document_version_id, status Draft
    end
```

**Ba điều kiện của luồng này, không phải tùy chọn hiện thực:**

- Bước ghi object và bước đăng ký catalog **không nguyên tử**. Mọi lỗi sau bước ghi intent đều phải phục hồi được từ intent, xem [luồng 7](#7-phục-hồi-sau-lỗi-một-phía).
- **Checksum phải được đối chiếu với giá trị đọc lại từ storage** trước khi chốt `Completed`. Lấy lại chính con số mà client khai báo rồi coi là đã xác nhận thì bất biến I10 không được kiểm tra ở đâu cả.
- **File đi qua service dưới dạng stream**, cả ở lớp nhận HTTP và lớp ghi S3. Đọc hết body vào bộ nhớ rồi mới ghi làm bộ nhớ service tỷ lệ với kích thước file nhân số request đồng thời, và mâu thuẫn với yêu cầu multipart ở [c4-04b mục 11.6](c4-04b-code-structure.md#116-kết-nối-và-cấu-hình-pool).
- Metadata bắt buộc theo `document_type` được D23 kiểm tra **trước** khi sinh phiên bản, để không tạo object cho một phiên bản sẽ bị từ chối (bất biến I18).

---

## 2. Duyệt phiên bản, có cạnh tranh đồng thời

```mermaid
sequenceDiagram
    autonumber
    actor A as Người phê duyệt
    actor B as Người phê duyệt thứ hai
    participant DS as C1 Document Service
    participant CAT as C2 Catalog
    participant OB as C10 Outbox

    A->>DS: POST /versions/{v2.0}/status = Approved
    B->>DS: POST /versions/{v2.1}/status = Approved (đồng thời)
    DS->>DS: D3 kiểm tra quyền chuyển trạng thái
    DS->>DS: D7 nhận lock theo document_id
    Note over DS: Chỉ một request vào được vùng tuần tự
    DS->>CAT: đọc current_version_id và trạng thái hiện tại
    CAT-->>DS: current = v1.2 Approved
    DS->>DS: D11 ghi intent StatusChangePending
    DS->>CAT: v2.0 = Approved, v1.2 = Obsolete, current_version_id = v2.0
    CAT-->>DS: ok
    DS->>DS: D11 chốt intent Completed
    DS->>DS: D16 ghi audit actor, time, from Draft to Approved
    DS->>OB: ghi sự kiện version.approved + version.obsoleted
    DS-->>A: 200 v2.0 là bản hiện hành
    DS->>DS: request của B được xử lý sau khi nhả lock
    DS-->>B: 200 v2.1 Approved, v2.0 chuyển Obsolete<br/>hoặc 409 nếu điều kiện tiền đề đã đổi
```

**Kết quả bắt buộc (POC-22):** không trùng `version_label`/ID, **tối đa một** bản `Approved`, và không mất thay đổi nào.

Hai chi tiết quyết định tính đúng của luồng này:

- Ba lệnh ghi xuống catalog (`v2.0 = Approved`, `v1.2 = Obsolete`, `current_version_id`) **không** nằm trong một giao dịch. Vì vậy phải có intent `StatusChangePending`: lỗi ở lệnh thứ hai mà không có intent sẽ để lại **hai** bản `Approved` cho tới lượt đối soát kế tiếp.
- Bản ghi audit phải có **cả trạng thái trước và trạng thái sau**. Chỉ ghi trạng thái đích thì không trả lời được câu hỏi của POC-14 về lịch sử phát hành.
- Vùng tuần tự ở đây chỉ đúng khi **một instance** C1. Chạy từ hai instance mà vẫn dùng khóa trong tiến trình là mất I4, I5 — cần C13 Distributed Lock.

---

## 3. Tra cứu và tải file theo quyền

```mermaid
sequenceDiagram
    autonumber
    actor U as Người dùng / Ứng dụng
    participant DS as C1 Document Service
    participant GW as C9 Gateway (tùy chọn)
    participant CAT as C2 Catalog
    participant S3 as C6 Object Storage

    U->>DS: GET /search?document_type=SRS&status=Approved&collection_id=PROJECT-A
    DS->>DS: D2 xác thực, D3 lấy phạm vi quyền
    alt Catalog phân quyền được kết quả tra cứu
        DS->>CAT: search API với filter tổ hợp + ngữ cảnh quyền
        CAT-->>DS: tập kết quả đã lọc
    else Catalog không lọc được quyền hoặc không lọc được custom fields
        DS->>GW: chuyển truy vấn
        GW->>CAT: search API
        CAT-->>GW: tập kết quả thô
        GW->>GW: lọc theo access_policy từng tài liệu
        GW-->>DS: tập kết quả đã lọc
    end
    DS-->>U: danh sách document_version_id + metadata cho phép xem

    U->>DS: GET /versions/{id}/download
    DS->>DS: D3 + D9 kiểm tra policy hiệu lực tại thời điểm gọi
    alt Tài liệu thông thường
        DS->>S3: tạo presigned URL TTL ngắn
        S3-->>DS: URL
        DS-->>U: 302 / URL có thời hạn
    else Tài liệu cần thu hồi ngay
        DS->>S3: GET object
        S3-->>DS: stream
        DS-->>U: proxy stream qua dịch vụ
    end
    DS->>DS: D16 ghi audit truy cập hoặc từ chối
```

**Rủi ro lớn nhất của cả đề xuất nằm ở nhánh `else` đầu tiên:** nếu catalog không lọc được tổ hợp custom fields hoặc không phân quyền kết quả (POC-17, 19), C9 Gateway trở thành bắt buộc và công tự phát triển tăng.

---

## 4. KB tiêu thụ bản Approved

```mermaid
sequenceDiagram
    autonumber
    participant KB as X3 Knowledge Base
    participant DS as C1 Document Service
    participant CAT as C2 Catalog
    participant S3 as C6 Object Storage

    KB->>DS: GET /search?collection_id=PROJECT-A&status=Approved
    DS->>CAT: truy vấn metadata + access_policy
    CAT-->>DS: danh sách phiên bản Approved
    DS-->>KB: document_version_id, metadata, access_policy
    KB->>DS: GET /versions/{id}/relationships?direction=both
    DS->>CAT: đọc quan hệ theo relation_type, cả hai chiều
    CAT-->>DS: outgoing derived_from → URD v1.2 · incoming references ← SAD v1.1
    DS-->>KB: mỗi quan hệ kèm relation_type và direction,<br/>source và target giữ nguyên
    KB->>DS: GET /versions/{id}/download
    DS->>S3: cấp file theo quyền
    S3-->>DS: object
    DS-->>KB: file gốc, định dạng không đổi
    KB->>KB: lưu document_version_id và access_policy làm tham chiếu nguồn
```

KB **không** quyết định cấu trúc lưu trữ gốc và **phải** tuân thủ `access_policy` do kho cấp (mục 7.1 báo cáo). POC-07 kiểm chứng đúng điều này.

**Cách trả quan hệ chiều vào là một quyết định ngữ nghĩa, không phải cách trình bày.** Cạnh `SAD v1.1 --references--> SRS v2.0` khi truy vấn từ SRS v2.0 phải trả về với `direction=incoming` và **nguyên hai đầu** (`source=SAD v1.1`, `target=SRS v2.0`). Nếu đảo hai đầu để "hướng ra ngoài" thì kết quả phát biểu rằng *SRS v2.0 references SAD v1.1* — một quan hệ chưa từng được khai báo, và KB sẽ lưu nó làm nguồn (bất biến I16).

---

## 5. Thu hồi quyền và xóa tài liệu đã cấp

```mermaid
sequenceDiagram
    autonumber
    actor AD as Quản trị viên kho
    participant DS as C1 Document Service
    participant CAT as C2 Catalog
    participant S3 as C6 Object Storage
    participant OB as C10 Outbox
    participant KB as X3 Downstream

    AD->>DS: PATCH /documents/{id}/access-policy<br/>hoặc DELETE /documents/{id}
    DS->>CAT: cập nhật access_policy / đánh dấu xóa logic
    DS->>DS: ngừng cấp link và API mới ngay khi thay đổi có hiệu lực
    DS->>OB: ghi sự kiện access.changed / document.deleted
    OB->>KB: webhook sự kiện
    KB->>KB: xóa bản sao, index, cache trong thời hạn cam kết [cần xác định]
    KB-->>DS: xác nhận đã đồng bộ (nếu có cơ chế xác nhận)
    Note over DS,S3: Link presigned đã phát hành vẫn hiệu lực đến khi hết TTL
    DS->>DS: với tài liệu yêu cầu thu hồi ngay, chuyển sang chế độ proxy
    DS->>DS: D16 ghi audit thay đổi quyền
```

Ba điểm phải phân biệt rõ khi nghiệm thu:

- **Ngừng cấp mới** có hiệu lực tức thì — kiểm chứng ở POC-11.
- **Link đã phát hành** chỉ hết hiệu lực khi hết TTL; cửa sổ này phải được đo và chấp nhận theo mức phân loại dữ liệu — kiểm chứng ở POC-23.
- **Xóa logic không xóa audit.** `AuditEvent` và lịch sử trạng thái của tài liệu vẫn truy vấn được sau khi xóa, nếu không thì không trả lời được ai đã xóa cái gì (bất biến I17). Xóa vật lý object là việc của [luồng 8](#8-hết-retention-và-xóa-vật-lý).

---

## 6. Đồng bộ từ nguồn hiện có

```mermaid
sequenceDiagram
    autonumber
    participant SRC as X2 Nguồn hiện có
    participant CN as D17 Sync Orchestrator
    participant DS as C1 Document Service
    participant S3 as C6 Object Storage
    participant CAT as C2 Catalog

    CN->>SRC: quét thay đổi theo lịch hoặc sự kiện
    SRC-->>CN: danh sách file, metadata nguồn, quyền ở nguồn
    CN->>CN: ánh xạ quyền nguồn sang nhóm — không ánh xạ được thì chế độ hạn chế
    CN->>DS: đăng ký tài liệu hoặc phiên bản mới qua đường ghi chính
    DS->>S3: ghi object bất biến
    DS->>CAT: đăng ký entity + metadata
    DS-->>CN: document_version_id
    Note over SRC,DS: File ở nguồn bị sửa về sau
    SRC-->>CN: phát hiện checksum thay đổi
    CN->>DS: tạo phiên bản nội dung mới
    DS-->>CN: version mới — bản đã đăng ký trước đó không đổi (POC-12)
```

Connector của catalog **không** được dùng làm đường ghi chính: connector catalog thường thu thập metadata, chưa chắc sao chép file (mục 3.4, 6.4 báo cáo). C5 Ingestion chỉ dùng để khảo sát nguồn.

---

## 7. Phục hồi sau lỗi một phía

```mermaid
sequenceDiagram
    autonumber
    participant DS as C1 Document Service
    participant IN as C7 State Store
    participant S3 as C6 Object Storage
    participant CAT as C2 Catalog
    participant RC as C8 Reconciliation Worker
    participant MON as X7 Monitoring

    DS->>IN: intent Received
    DS->>S3: PUT object — thành công
    DS->>IN: ObjectStored
    DS->>CAT: đăng ký entity — LỖI hoặc service bị kill
    Note over DS: Document Service restart — không còn trạng thái trong RAM
    RC->>IN: quét intent ở trạng thái ObjectStored / RetryPending
    IN-->>RC: danh sách intent chưa hoàn tất
    RC->>S3: HEAD object kiểm tra tồn tại và checksum
    S3-->>RC: ok
    RC->>CAT: đăng ký lại với cùng document_version_id và idempotency_key
    alt Đăng ký thành công
        CAT-->>RC: entity id
        RC->>IN: Completed
    else Vẫn lỗi, vượt ngưỡng retry
        RC->>IN: Failed
        RC->>MON: cảnh báo, chuyển xử lý thủ công
    end
    RC->>S3: liệt kê object không có entity tương ứng
    RC->>CAT: tìm entity trỏ tới object mất hoặc hỏng
    RC->>MON: báo cáo kết quả đối soát hai chiều
```

**Kết quả bắt buộc (POC-21):** sau kill/restart tại **từng bước**, hệ thống không mất và không nhân đôi phiên bản. Nếu biến thể manifest trên S3 không đạt, bổ sung registry database theo mục 3.10 báo cáo.

**Giới hạn của việc phục hồi:** job chỉ phục hồi được intent mà object **đã** nằm trên storage, vì nó không còn bytes gốc trong tay. Intent chết ở trạng thái `Received` (chưa ghi object xong) phải được đánh `Failed` và báo lên vận hành, **không** được đăng ký một entity phiên bản trỏ tới object không tồn tại.
---

## 8. Hết retention và xóa vật lý

```mermaid
sequenceDiagram
    autonumber
    participant RT as D25 Retention Manager
    participant CAT as C2 Catalog
    participant IN as C7 State Store
    participant S3 as C6 Object Storage
    participant OB as C10 Outbox Dispatcher
    participant MON as X7 Monitoring

    RT->>CAT: tìm tài liệu/phiên bản hết retention hoặc đã xóa logic
    CAT-->>RT: danh sách ứng viên kèm classification và status
    RT->>RT: kiểm tra điều kiện: không còn là bản hiện hành,<br/>không bị object lock giữ, đã quá thời hạn cam kết
    alt Đủ điều kiện xóa vật lý
        RT->>S3: xóa object theo storage_uri
        RT->>CAT: xóa entity phiên bản hoặc đánh dấu purged
        RT->>IN: ghi audit purge, giữ nguyên audit cũ
        RT->>OB: ghi sự kiện version.purged
    else Bị object lock hoặc chưa đủ thời hạn
        RT->>MON: báo danh sách chờ, không tự ghi đè object lock
    end
    RT->>MON: báo cáo số lượng đã xóa, đang chờ, lỗi
```

Ba ràng buộc của luồng này:

- **Xóa vật lý là không hồi phục được**, nên nó tách khỏi xóa logic ở [luồng 5](#5-thu-hồi-quyền-và-xóa-tài-liệu-đã-cấp) và chỉ chạy khi quá thời hạn cam kết. POC-15 kiểm chứng kịch bản xóa nhầm rồi khôi phục — tức là trong cửa sổ trước khi xóa vật lý, S3 Versioning phải khôi phục được.
- **Object lock thắng retention policy của kho.** Nếu object còn bị lock, D25 không được cố xóa; nó báo lên hàng đợi chờ. Lớp bảo vệ ở storage không được phép bị kho vượt qua.
- **Audit sống lâu hơn dữ liệu.** `AuditEvent` của một tài liệu đã purge vẫn phải truy vấn được, với thời hạn lưu riêng theo chính sách audit (bất biến I17).

