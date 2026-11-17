# C4 — DEPLOYMENT VIEW

> **Câu hỏi tài liệu này trả lời:** Các container được triển khai ở đâu, với tài nguyên nào, ở hai mốc: môi trường PoC và triển khai ban đầu on-premise.
> **Trạng thái:** Mọi con số là **mức tham khảo từ tài liệu sản phẩm**, phải đối chiếu lại với phiên bản được chọn và số liệu khảo sát. Không dùng làm dự toán.
> **Tham chiếu báo cáo:** mục 3.8, 5.1, 5.2, 6.1, 6.2.

## 6.1. Môi trường PoC — một máy, Docker Compose

```mermaid
flowchart TB
    classDef node fill:#F7F9FB,stroke:#6B7A8F,color:#223
    classDef builtin  fill:#E8F4FD,stroke:#2E7FB8,color:#0B3C5D
    classDef custom   fill:#FFF3E0,stroke:#E08A1E,color:#5C3A00
    classDef poc      fill:#FDECEC,stroke:#C0392B,color:#5C1A14

    subgraph HOST["Máy thử nghiệm — Linux, Docker Compose<br/>[Deployment Node]<br/>Không dùng dữ liệu vượt mức phân loại cho phép [cần xác định]"]
        direction TB
        N1["Container: document-service<br/>[C1 · Tự phát triển]"]
        N2["Container: catalog-app<br/>[C2 · OpenMetadata hoặc DataHub]"]
        N3[("Container: catalog-db<br/>[C3 · MySQL/PostgreSQL]")]
        N4[("Container: search-index<br/>[C4 · Elasticsearch/OpenSearch]")]
        N5[("Container: object-storage<br/>[C6 · S3-compatible]")]
        N6[("Volume hoặc container: intent-store<br/>[C7 · manifest S3 hoặc registry DB]")]
        N7["Container: reconciler<br/>[C8 · job định kỳ]"]
        N8["Container: mock-downstream<br/>[Giả lập KB nhận sự kiện]"]
    end

    IDP["IdP / SSO thử nghiệm<br/>[Deployment Node bên ngoài]"]

    N1 --> N5
    N1 --> N2
    N1 --> N6
    N2 --> N3
    N2 --> N4
    N7 --> N6
    N7 --> N5
    N7 --> N2
    N1 --> N8
    N1 -.-> IDP
    N2 -.-> IDP

    class N1,N7 custom
    class N2,N3,N4,N5,N8 builtin
    class N6 poc
```

| Đặc điểm | Giá trị |
|---|---|
| Thời lượng sử dụng | Trong **2–4 tuần (đề xuất)** của giai đoạn 1 |
| Mục tiêu | Chạy được bộ test case ở Phụ lục B, đặc biệt POC-02, 06, 09, 17, 18, 19, 20, 21, 22, 23 |
| Giới hạn | Chỉ prototype; **không** phát triển đầy đủ registry/gateway cho production |
| Dữ liệu | Một dự án phần mềm thực có đủ URD–SRS–SAD nhiều phiên bản, cộng một bộ tài liệu thông thường từ ít nhất một nguồn hiện có |
| Hai biến thể | A: OpenMetadata. B: DataHub chạy tối thiểu cùng bộ test trọng yếu để so sánh công bằng |

## 6.2. Triển khai ban đầu on-premise

```mermaid
flowchart TB
    classDef node fill:#F7F9FB,stroke:#6B7A8F,color:#223
    classDef builtin  fill:#E8F4FD,stroke:#2E7FB8,color:#0B3C5D
    classDef custom   fill:#FFF3E0,stroke:#E08A1E,color:#5C3A00
    classDef optional fill:#F3F0FB,stroke:#7A5FB8,color:#33265C

    subgraph DC["Trung tâm dữ liệu tổ chức"]
        direction TB

        subgraph ZEDGE["Vùng tiếp nhận<br/>[Deployment Node]"]
            LB["Reverse proxy / API gateway hạ tầng<br/>TLS, rate limit"]
        end

        subgraph ZAPP["Vùng ứng dụng<br/>[Deployment Node · nhiều instance]"]
            direction LR
            A1["document-service<br/>[C1] · stateless phần xử lý,<br/>trạng thái nằm ở C7"]
            A2["reconciler + outbox publisher<br/>[C8 + C10]"]
            A3["search gateway<br/>[C9 · Tùy chọn]"]
            A4["admin UI<br/>[C11 · Tùy chọn]"]
        end

        subgraph ZCAT["Vùng nền tảng catalog<br/>[Deployment Node]"]
            direction LR
            B1["catalog-app [C2]"]
            B2[("catalog-db [C3]")]
            B3[("search-index [C4]")]
            B4["ingestion / Airflow [C5 · Tùy chọn]"]
        end

        subgraph ZSTO["Vùng lưu trữ<br/>[Deployment Node]"]
            direction LR
            S1[("Object Storage S3-compatible [C6]<br/>versioning · object lock · mã hóa khi lưu")]
            S2[("Intent / registry store [C7]")]
            S3B[("Backup / replica")]
        end

        subgraph ZOPS["Vùng vận hành<br/>[Deployment Node]"]
            O1["Monitoring, log tập trung, cảnh báo"]
        end
    end

    IDP["IdP / SSO tổ chức<br/>[Deployment Node]"]
    CONS["KB và ứng dụng khai thác<br/>[Deployment Node]"]
    SRC["Nguồn tài liệu hiện có<br/>[Deployment Node]"]

    CONS --> LB
    SRC --> LB
    LB --> A1
    LB -.-> A3
    LB -.-> A4
    A1 --> S1
    A1 --> S2
    A1 --> B1
    A2 --> S2
    A2 --> S1
    A2 --> B1
    A2 --> CONS
    A3 -.-> B1
    A4 -.-> A1
    B1 --> B2
    B1 --> B3
    B4 -.-> B1
    S1 --> S3B
    B2 --> S3B
    A1 -.-> IDP
    B1 -.-> IDP
    A1 --> O1
    A2 --> O1
    B1 --> O1

    class A1,A2 custom
    class A3,A4,B4 optional
    class B1,B2,B3,S1,S2,S3B,O1 builtin
    class LB builtin
```

## 6.3. Tài nguyên tham khảo

| Thành phần | Tài nguyên cần xem xét | Mức tham khảo |
|---|---|---|
| C6 Object Storage | Disk, network, IOPS, backup | Theo công thức ở mục 6.4 |
| C2 Catalog app | CPU, RAM | Chốt sau PoC |
| C3 Catalog DB (MySQL/PostgreSQL) | CPU, RAM, disk | Khuyến nghị tối thiểu của OpenMetadata cho production: **4 vCPU, 16 GiB RAM, từ 100 GiB disk** |
| C4 Search index (Elasticsearch/OpenSearch) | CPU, RAM, dung lượng index | Khuyến nghị tối thiểu: **2 vCPU, 8 GiB RAM, 100 GiB mỗi node** |
| C5 Ingestion (Airflow), nếu dùng | CPU, RAM | Khuyến nghị tối thiểu: **4 vCPU, 16 GiB RAM** |
| C1 Document Service + C7 + C8 | CPU, RAM, concurrency; registry DB/queue hoặc S3 intent; job đối soát | Chốt sau PoC về lỗi và đồng thời |
| Monitoring / Audit | Dung lượng log, metric, thời gian lưu | Chốt sau khảo sát |

Nếu chọn DataHub, **cộng thêm Kafka và graph index** vào vùng nền tảng catalog.

## 6.4. Ước lượng dung lượng

```text
Dung lượng file ≈ Số tài liệu × Kích thước file trung bình × Số phiên bản lưu bình quân
```

Phải tính thêm: index tìm kiếm, metadata database, audit log, backup/replication và dự phòng tăng trưởng. Nếu dùng registry hoặc search gateway, cộng thêm chi phí triển khai và vận hành; **không mặc định Document Service là stateless hoàn toàn**.

Các thông số đầu vào đều **chưa khảo sát** tại thời điểm lập tài liệu:

| Thông số | Trạng thái |
|---|---|
| Số lượng tài liệu và tổng dung lượng | Chưa khảo sát |
| Kích thước file trung bình và lớn nhất | Chưa khảo sát |
| Số phiên bản lưu bình quân | Chưa khảo sát |
| Số file tăng theo tháng/năm | Chưa khảo sát |
| Số người dùng/ứng dụng truy cập đồng thời | Chưa khảo sát |
| Retention, RPO/RTO | Chưa xác định |

## 6.5. Yêu cầu vận hành theo vùng triển khai

| Vùng | Yêu cầu |
|---|---|
| Tiếp nhận | TLS bắt buộc; giới hạn tần suất; không phơi bày catalog UI ra ngoài phạm vi người dùng đã được ủy quyền |
| Ứng dụng | Nhiều instance C1; trạng thái xử lý nằm ở C7 chứ không ở RAM để restart không mất intent. Probe: `/livez` cho liveness (**không** phụ thuộc OpenMetadata/S3 để tránh restart lan truyền), `/startupz` cho migration custom property, `/readyz` cho load balancer — chi tiết ở [c4-04b mục 10](c4-04b-code-structure.md#10-health-check) |
| Nền tảng catalog | Cố định phiên bản; kiểm thử hồi quy bằng Phụ lục B trước mỗi lần nâng cấp |
| Lưu trữ | Bucket đóng, không public; service account chỉ có quyền S3 tối thiểu; object lock/versioning theo retention |
| Vận hành | Cảnh báo khi retry vượt ngưỡng, khi hàng đợi đối soát tăng, khi dung lượng vượt ngưỡng, khi circuit breaker mở kéo dài, khi service ở chế độ suy giảm — bộ chỉ số bắt buộc ở [c4-04b mục 11.7](c4-04b-code-structure.md#117-chỉ-số-và-cảnh-báo-bắt-buộc) |

## 6.6. Lưu ý chọn sản phẩm Object Storage

- Thứ tự ưu tiên: **dịch vụ S3-compatible sẵn có của tổ chức [cần xác định]**; nếu tự vận hành thì Ceph RGW, SeaweedFS hoặc Garage, chọn theo năng lực vận hành và kết quả PoC.
- **Không ưu tiên MinIO OSS bản cũ cho triển khai mới:** repository `minio/minio` được archive ngày 25/04/2026, bản OSS không còn được duy trì. Nếu cân nhắc AIStor phải đánh giá riêng điều kiện cấp phép, yêu cầu hạ tầng và mức độ phù hợp.
- Phải kiểm chứng tương thích S3, object lock, policy và lifecycle **theo phiên bản thực tế**; không đồng nhất "tương thích API S3" với đầy đủ chức năng mở rộng của AWS S3.
