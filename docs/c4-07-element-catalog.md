# DANH MỤC PHẦN TỬ, ÁNH XẠ YÊU CẦU VÀ QUYẾT ĐỊNH CÒN MỞ

> **Mục đích:** Một bảng tra duy nhất giữa phần tử kiến trúc, mục trong báo cáo đề xuất và test case PoC, để khi PoC kết thúc có thể cập nhật mô hình mà không đọc lại toàn bộ tài liệu.

## 1. Toàn bộ phần tử

### 1.1. Người dùng (L1)

| ID | Phần tử | Mức | Mục báo cáo |
|---|---|---|---|
| P1 | Người dùng nghiệp vụ / Owner tài liệu | L1 | 2.2, 2.3, 6.3 |
| P2 | Quản trị viên kho | L1 | 4.1, 6.3 |
| P3 | Nhà phát triển ứng dụng khai thác | L1 | 2.5 |
| P4 | Người phê duyệt tài liệu | L1 | 2.4 |

### 1.2. Hệ thống bên ngoài (L1)

| ID | Phần tử | Trạng thái | Mục báo cáo | Test case |
|---|---|---|---|---|
| X1 | IdP / SSO | Có sẵn, **[cần xác định hệ thống]** | 2.6 | POC-04 |
| X2 | Nguồn tài liệu hiện có | Có sẵn | 2.1, 3.10 | POC-12 |
| X3 | Knowledge Base | Có sẵn | 2.5, 7.1 | POC-07, 11 |
| X4 | Service / AI Agent | Có sẵn | 3.3 | POC-04 |
| X5 | Ứng dụng nghiệp vụ khác | Có sẵn | 2.5 | POC-02 |
| X6 | Nền tảng wiki | Tùy chọn, không phải kho gốc | 3.2.1 | — |
| X7 | Monitoring / Log | Có sẵn | 2.7 | POC-14 |
| X8 | Pipeline chuẩn hóa nội dung | Ngoài phạm vi | 2.1, 7.1 | — |

### 1.3. Container (L2)

| ID | Phần tử | Trạng thái | Mục báo cáo | Test case |
|---|---|---|---|---|
| C1 | Document Service | Tự phát triển | 3.1, 3.5, 3.9 | POC-01, 03, 04, 08, 10, 13, 20, 21, 22 |
| C2 | Catalog Application | Có sẵn + Cần PoC | 3.1, 3.6, 3.7 | POC-02, 06, 17, 19 |
| C3 | Catalog Metadata DB | Có sẵn | 5.2 | — |
| C4 | Catalog Search Index | Có sẵn + Cần PoC | 3.4, 5.2 | POC-02, 16, 19 |
| C5 | Catalog Ingestion | Tùy chọn | 3.4, 6.4 | POC-12 |
| C6 | Object Storage tương thích S3 | Có sẵn | 3.8 | POC-01, 15 |
| C7 | Durable Intent / Idempotency Store | Cần PoC — còn mở | 3.5, 3.10 | POC-08, 18, 21, 22 |
| C8 | Reconciliation & Recovery Worker | Tự phát triển | 3.5, 3.9 | POC-08, 18, 21 |
| C9 | Search / Query Gateway | Tùy chọn | 2.6, 3.10 | POC-17, 19, 20 |
| C10 | Event Publisher / Outbox | Tự phát triển | 2.5, 3.3 | POC-11 |
| C11 | Admin / Business UI | Tùy chọn | 3.10 | — |
| C12 | MCP Server adapter | Tùy chọn | 3.3 | POC-04 |

### 1.4. Thành phần của Document Service (L3)

| ID | Phần tử | Mục báo cáo | Test case |
|---|---|---|---|
| D1 | API Layer | 2.2, 2.5 | POC-01, 02, 03 |
| D2 | Authentication | 2.6 | POC-04 |
| D3 | Authorization / PDP | 2.6, 3.4 | POC-04, 17, 20 |
| D4 | Upload Handler | 2.2, 2.3 | POC-01 |
| D5 | Checksum & Dedup | 2.4 | POC-13 |
| D6 | Version Manager | 2.4, 3.5 | POC-03, 22 |
| D7 | Lifecycle Manager | 2.4, 3.5 | POC-10, 22 |
| D8 | Relationship Manager | 2.4, 3.6 | POC-06, 09 |
| D9 | Access Policy Manager | 2.6 | POC-04, 11, 17 |
| D10 | Download Issuer | 2.6, 2.7 | POC-04, 23 |
| D11 | Intent & Idempotency Manager | 3.5 | POC-08, 18, 21 |
| D12 | Catalog Adapter | 6.4 | — |
| D13 | Storage Adapter | 3.8 | POC-01, 15 |
| D14 | Event Publisher | 2.5 | POC-11 |
| D15 | Reconciliation Worker | 3.5, 3.9 | POC-08, 18, 21 |
| D16 | Audit Logger | 2.2, 2.7 | POC-14 |
| D17 | Sync Orchestrator | 2.1, 6.4 | POC-12 |
| D18 | Search Query Service | 2.2, 2.6 | POC-02, 17, 19 |

## 2. Ánh xạ yêu cầu chức năng sang phần tử

| Nhóm chức năng (mục 2.2 báo cáo) | Phần tử chịu trách nhiệm |
|---|---|
| Lưu trữ raw data | C6, D4, D13 |
| Tổ chức tài liệu | C2 (Collection/Directory), D1 |
| Metadata | C2, D4, D12 |
| Phiên bản và trạng thái | D6, D7, C7 |
| Liên kết | D8, C2 hoặc registry relation |
| Tìm kiếm | C2, C4, D18, C9 (nếu cần) |
| Phân quyền | X1, D2, D3, D9, D10 |
| Tích hợp | D1, C10, C12 |
| Audit | D16, C2, X7 |

| Yêu cầu phi chức năng (mục 2.7) | Phần tử chịu trách nhiệm |
|---|---|
| An toàn | D2, D3, D9, D10, C6 (mã hóa khi lưu), vùng tiếp nhận TLS |
| Độ tin cậy | C7, C8, D11, D15, backup ở vùng lưu trữ |
| Khả năng mở rộng | C1 nhiều instance, C4 theo node, C6 theo dung lượng |
| Khả năng vận hành | X7, C8, cảnh báo hàng đợi đối soát |
| Tính độc lập sản phẩm | D12, D13 |

## 3. Ánh xạ test case PoC sang phần tử cần kiểm chứng

| Mã | Tình huống | Phần tử bị kiểm chứng |
|---|---|---|
| POC-01 | Upload nhiều loại file và khai báo metadata | C1, C6, D4, D5, D13 |
| POC-02 | Tìm theo tên, loại, owner, collection, trạng thái | C2, C4, D18 |
| POC-03 | Upload phiên bản mới | D6, C6 |
| POC-04 | User không đủ quyền tìm/tải file | X1, D2, D3, D10 |
| POC-05 | Đăng ký URD, SRS, SAD của Project A | C2, D1 |
| POC-06 | `derived_from` truy vấn hai chiều | D8, C2 — **rủi ro cao** |
| POC-07 | KB yêu cầu tài liệu Approved | D7, D9, C10, X3 |
| POC-08 | Lỗi một phía trong luồng ghi | C7, D11, C8 |
| POC-09 | Tạo SRS v2.1 khi v2.0 đang có quan hệ | D8 — **rủi ro cao** |
| POC-10 | Chuyển một version thành Approved | D7, D16 |
| POC-11 | Thu hồi quyền/xóa tài liệu đã cấp cho KB | D9, C10, X3 |
| POC-12 | Đồng bộ nguồn rồi sửa file ở nguồn | D17, C5, D6 |
| POC-13 | Upload lại file có checksum giống | D5 |
| POC-14 | Xem audit một tài liệu | D16, C2, X7 |
| POC-15 | Xóa nhầm rồi khôi phục | C6, D13 |
| POC-16 | Dữ liệu đủ lớn để đo search/API | C4, C2, C1 |
| POC-17 | Tài khoản thiếu quyền tra cứu trực tiếp catalog | C2, C9 — **rủi ro cao** |
| POC-18 | Object ghi thành công, catalog lỗi | C7, C8, D11 |
| POC-19 | Custom properties lọc kết hợp và UI facets | C2, C4, C9 — **rủi ro cao** |
| POC-20 | Sửa trực tiếp trường kiểm soát qua Catalog UI/API | C2, D12, ranh giới mục 2.4 ở L2 |
| POC-21 | Kill/restart Document Service tại từng bước | C7, C8, D11, D15 |
| POC-22 | Hai request đồng thời tạo/duyệt phiên bản | D6, D7 — **rủi ro cao** |
| POC-23 | Thu hồi quyền sau khi đã cấp link tải | D10, C6 |

Năm test case `rủi ro cao` (POC-06, 09, 17, 19, 22) là những test case có thể **làm thay đổi quyết định công nghệ**, nên được ưu tiên trong giới hạn 2–4 tuần.

## 4. Quyết định kiến trúc còn mở

| # | Quyết định | Định hướng hiện tại | Phần tử bị ảnh hưởng | Chốt sau |
|---|---|---|---|---|
| Q1 | OpenMetadata hay DataHub | **Đã chốt 17/11/2026: OpenMetadata.** Mã nguồn chỉ còn một adapter (xem [c4-04b](c4-04b-code-structure.md)); DataHub giữ làm đối chứng tài liệu. PoC chuyển từ so sánh A/B sang kiểm chứng giới hạn của OpenMetadata | C2, C3, C4, C5, D12 | Đã chốt |
| Q2 | Có cần registry database/queue | Thử durable intent trên S3 + reconciliation | C7, C8, D11 | POC-18, 21, 22 |
| Q3 | Tìm kiếm metadata | Ưu tiên native API; nếu thiếu thì tính chi phí index/gateway | C2, C4, C9, D18 | POC-02, 19 |
| Q4 | Quan hệ hai chiều | Native edge nếu đủ; nếu không thì registry relation | D8, C2, C7 | POC-06, 09 |
| Q5 | Trường nào được sửa qua catalog | Chỉ metadata mô tả | Ranh giới ghi ở L2 mục 2.4, D12 | Trước POC-20 |
| Q6 | Ai thấy metadata | Áp policy theo asset; nếu không được thì chỉ dùng nội bộ + gateway | C2, C9, D3 | POC-17, 20 |
| Q7 | Cách thu hồi link tải | TTL ngắn cho tài liệu thường; proxy cho dữ liệu cần thu hồi ngay | D10, C6 | POC-23 |
| Q8 | Ánh xạ quyền từ nguồn | Theo nhóm; chưa ánh xạ thì chỉ owner và quản trị viên | D9, D17, X1, X2 | Sau khảo sát IdP và nguồn |
| Q9 | Object Storage | Ưu tiên dịch vụ S3-compatible hiện có | C6, D13 | Sau khảo sát hạ tầng |
| Q10 | Nguồn hiện có sau khi đưa vào kho | **[cần xác định]**: chỉ đọc / song song / ngừng | X2, D17 | Sau khảo sát |
| Q11 | UI người dùng nghiệp vụ | Thử UI catalog trước | C11 | Sau giai đoạn 3 |

## 5. Phần tử bị loại khỏi kiến trúc và lý do

| Phương án | Vì sao không nằm trong mô hình C4 này | Điều kiện xem xét lại |
|---|---|---|
| Hệ quản lý tài liệu chuyên dụng (DMS/ECM) làm lõi | Khác trọng tâm sử dụng; mô hình file và metadata thường gắn với sản phẩm; kiến trúc cần tách hai lớp ngay từ đầu | Nếu phần phải tự phát triển vượt ngưỡng chấp nhận (mục 6.2) |
| Nền tảng wiki làm kho raw data | Đơn vị quản lý chính là page/knowledge document; khó chuẩn hóa lineage ở mức phiên bản file; version history của page không đồng nghĩa trạng thái nghiệp vụ | Nếu khảo sát cho thấy nhu cầu chính chuyển sang biên soạn/cộng tác |
| Catalog connector làm đường ghi chính | Connector catalog thường thu thập metadata, chưa chắc sao chép file; connector Drive còn ở mức beta | Không áp dụng; connector chỉ dùng khảo sát nguồn |
| `DataHubFile` làm kho file | Là tính năng file đính kèm, không đồng nghĩa kho raw data | Nếu PoC chứng minh đáp ứng versioning và quyền ở mức yêu cầu |
| Coi presigned URL là cơ chế thu hồi quyền | Link đã cấp không tự mất hiệu lực khi quyền đổi | Không áp dụng; dùng proxy khi cần thu hồi ngay |

## 6. Cách cập nhật mô hình sau PoC

1. Với mỗi test case ở bảng mục 3, ghi kết quả `Đạt native / Đạt có bổ sung / Không đạt / Chưa kiểm chứng`.
2. Nếu một quyết định ở bảng mục 4 được chốt, cập nhật trạng thái phần tử tương ứng trong [c4-02-container.md](c4-02-container.md) từ `Tùy chọn`/`Cần PoC` sang `Có sẵn` hoặc `Tự phát triển`, và xóa nhánh nét đứt tương ứng khỏi sơ đồ.
3. Nếu một container tùy chọn bị bật, bổ sung công phát triển và vận hành vào dự toán ở mục 5.3 báo cáo trước khi trình phê duyệt.
4. Test case chưa thực hiện phải ghi **chưa kiểm chứng**, **không được tính là đạt**.
