# C4 — DEPLOYMENT VIEW

> **Câu hỏi tài liệu này trả lời:** Các container được triển khai ở đâu, với tài nguyên nào, ở hai mốc: môi trường PoC và triển khai ban đầu on-premise.
> **Trạng thái:** Mọi con số là **mức tham khảo từ tài liệu sản phẩm**, phải đối chiếu lại với phiên bản được chọn và số liệu khảo sát. Không dùng làm dự toán.
> **Tham chiếu báo cáo:** mục 3.8, 5.1, 5.2, 6.1, 6.2.

## 6.1. Môi trường PoC — một máy: hạ tầng trong Compose, service chạy trên máy

```mermaid
flowchart TB
    classDef node fill:#F7F9FB,stroke:#6B7A8F,color:#223
    classDef builtin  fill:#E8F4FD,stroke:#2E7FB8,color:#0B3C5D
    classDef custom   fill:#FFF3E0,stroke:#E08A1E,color:#5C3A00
    classDef poc      fill:#FDECEC,stroke:#C0392B,color:#5C1A14
    classDef gap      fill:#F2F2F2,stroke:#9E9E9E,color:#4A4A4A,stroke-dasharray:4 3

    subgraph HOST["Máy thử nghiệm — Linux hoặc macOS<br/>[Deployment Node]<br/>Không dùng dữ liệu vượt mức phân loại cho phép [cần xác định]"]
        direction TB

        subgraph PROC["Tiến trình chạy trực tiếp trên máy — uv run"]
            direction LR
            N1["document-service<br/>[C1 · Tự phát triển]<br/>make run — uvicorn :8080"]
            N7["reconciler<br/>[C8 · Tự phát triển]<br/>make reconcile — một lượt hoặc run_forever"]
            N9["outbox-dispatcher<br/>[C10 · Tự phát triển]<br/>cần một tiến trình gọi run_once theo chu kỳ"]
        end

        subgraph COMPOSE["deploy/docker-compose.yml — 4 container hạ tầng"]
            direction LR
            N2["openmetadata<br/>[C2 · server 1.12.0]<br/>:8585 API · :8586 health"]
            N3[("mysql<br/>[C3 · 8.0.35] :3306")]
            N4[("opensearch<br/>[C4 · 2.19.0] :9200")]
            N5[("objectstore<br/>[C6 · SeaweedFS 3.68]<br/>:8333 S3 · :9333")]
        end

        N6[("local_data/document_service.sqlite<br/>[C7 · Service State Store]<br/>processing_intent · relationship<br/>audit_event · outbox_event")]
        N8["mock-downstream<br/>[Giả lập KB nhận sự kiện]<br/>Chưa dựng — cần cho POC-11"]
    end

    IDP["IdP / SSO thử nghiệm<br/>[Deployment Node bên ngoài]<br/>Chưa dựng — OpenMetadata PoC đang dùng<br/>AUTHENTICATION_PROVIDER=basic, POC-04 chưa chạy được"]

    N1 --> N5
    N1 --> N2
    N1 --> N6
    N2 --> N3
    N2 --> N4
    N7 --> N6
    N7 --> N5
    N7 --> N2
    N9 --> N6
    N9 -.-> N8
    N1 -.-> IDP
    N2 -.-> IDP

    class N1,N7,N9 custom
    class N2,N3,N4,N5 builtin
    class N6 poc
    class N8,IDP gap
```

**Hai điều sơ đồ này nói ra mà bản vẽ trước ngày 19/11/2026 không nói:**

1. **Chỉ hạ tầng nằm trong Docker Compose.** `document-service`, `reconciler` và `outbox-dispatcher` chạy như tiến trình trên máy, `make run` và `make reconcile`. Bản vẽ trước vẽ cả ba thành container compose, nên ai đọc cũng tưởng `docker compose up` là dựng được toàn bộ hệ thống.
2. **Hai node nét xám là khoảng trống đã biết, không phải thành phần đã có.** Chưa có IdP thử nghiệm — PoC đang chạy `AUTHENTICATION_PROVIDER=basic`, nên **POC-04 chưa thể chạy**. Chưa có mock downstream, nên **POC-11 chưa thể chạy đầu-cuối**. Vẽ ra để hai khoảng trống này nằm trong kế hoạch, không bị phát hiện vào tuần cuối.


| Đặc điểm | Giá trị |
|---|---|
| Thời lượng sử dụng | Trong **2–4 tuần (đề xuất)** của giai đoạn 1 |
| Mục tiêu | Chạy được bộ test case ở Phụ lục B, đặc biệt POC-02, 06, 09, 17, 18, 19, 20, 21, 22, 23 |
| Giới hạn | Chỉ prototype; **không** phát triển đầy đủ registry/gateway cho production |
| Dữ liệu | Một dự án phần mềm thực có đủ URD–SRS–SAD nhiều phiên bản, cộng một bộ tài liệu thông thường từ ít nhất một nguồn hiện có |
| Catalog | **OpenMetadata, phiên bản cố định 1.12.0** (quyết định Q1 đã chốt 17/11/2026). DataHub không còn là nhánh triển khai; nó chỉ là đối chứng tài liệu ở mục 3.7 báo cáo |
| Còn thiếu để chạy đủ Phụ lục B | IdP thử nghiệm (POC-04), mock downstream nhận webhook (POC-11), tiến trình chạy outbox dispatcher theo chu kỳ (POC-11) |

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

        subgraph ZAPP["Vùng ứng dụng<br/>[Deployment Node]<br/>Nhiều instance C1 CHỈ khi đã có C13"]
            direction LR
            A1["document-service<br/>[C1] · không giữ trạng thái trong RAM,<br/>trạng thái nằm ở C7"]
            A2["reconciler<br/>[C8] · tiến trình riêng, một instance"]
            A5["outbox-dispatcher<br/>[C10] · tiến trình riêng, một instance"]
            A3["search gateway<br/>[C9 · Tùy chọn]"]
            A4["admin UI<br/>[C11 · Tùy chọn]"]
            A6["distributed lock<br/>[C13 · bắt buộc khi nhiều instance C1]"]
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
            S2[("Service State Store [C7]<br/>PostgreSQL/MySQL<br/>intent · relationship · audit · outbox")]
            S3B[("Backup / replica<br/>cho C6, C3 và C7")]
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
    A5 --> S2
    A5 --> CONS
    A1 -.-> A6
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

    A5 --> O1
    class A1,A2,A5 custom
    class A3,A4,A6,B4 optional
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
| C1 Document Service | CPU, RAM, concurrency. **RAM tỷ lệ với kích thước file × số upload đồng thời nếu upload không đi theo stream** — đây là tham số phải đo, không phải hằng số | Chốt sau PoC về lỗi và đồng thời |
| C7 Service State Store | CPU, RAM, disk, IOPS; **vào phạm vi backup và RPO/RTO** vì chứa audit và outbox. Dung lượng tăng theo số thao tác, không theo số tài liệu | Chốt sau khảo sát khối lượng thao tác |
| C8 reconciler + C10 outbox dispatcher | CPU, RAM nhỏ; chu kỳ chạy; hàng đợi tồn | Chốt sau PoC |
| C13 Distributed Lock, nếu nhiều instance C1 | CPU, RAM nhỏ; độ sẵn sàng phải cao hơn C1 vì mất khóa là chặn mọi ghi | Chốt khi quyết định số instance |
| Monitoring / Audit | Dung lượng log, metric, thời gian lưu | Chốt sau khảo sát |

Nếu chọn DataHub, **cộng thêm Kafka và graph index** vào vùng nền tảng catalog.

## 6.4. Ước lượng dung lượng

```text
Dung lượng file ≈ Số tài liệu × Kích thước file trung bình × Số phiên bản lưu bình quân
```

Phải tính thêm: index tìm kiếm, metadata database, **C7 Service State Store** (intent, quan hệ, audit, outbox), audit log tập trung, backup/replication và dự phòng tăng trưởng. Nếu dùng search gateway hoặc khóa phân tán, cộng thêm chi phí triển khai và vận hành. **Document Service không stateless:** phần xử lý không giữ trạng thái trong RAM, nhưng hệ thống vẫn có một datastore riêng ngoài catalog và object storage, và datastore đó phải có kế hoạch backup.

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
| Ứng dụng | Trạng thái xử lý nằm ở C7 chứ không ở RAM để restart không mất intent. **Chỉ bật nhiều instance C1 sau khi có C13 Distributed Lock** — khóa trong tiến trình không tuần tự hoá được giữa các instance, nên bất biến I4/I5 sẽ vỡ. C8 và C10 mỗi loại chạy **một** instance, hoặc phải có khóa chọn leader. Probe: `/livez` cho liveness (**không** phụ thuộc OpenMetadata/S3 để tránh restart lan truyền), `/startupz` cho migration custom property, `/readyz` cho load balancer — chi tiết ở [c4-04b mục 10](c4-04b-code-structure.md#10-health-check) |
| Nền tảng catalog | Cố định phiên bản; kiểm thử hồi quy bằng Phụ lục B trước mỗi lần nâng cấp |
| Lưu trữ | Bucket đóng, không public; service account chỉ có quyền S3 tối thiểu; object lock/versioning theo retention. C7 nằm trong cùng kế hoạch backup và kiểm tra restore như C3 và C6; mất C7 là mất audit và outbox, không chỉ mất intent |
| Vận hành | Cảnh báo khi retry vượt ngưỡng, khi hàng đợi đối soát tăng, khi dung lượng vượt ngưỡng, khi circuit breaker mở kéo dài, khi service ở chế độ suy giảm — bộ chỉ số bắt buộc ở [c4-04b mục 11.7](c4-04b-code-structure.md#117-chỉ-số-và-cảnh-báo-bắt-buộc) |

## 6.6. Lưu ý chọn sản phẩm Object Storage

- Thứ tự ưu tiên: **dịch vụ S3-compatible sẵn có của tổ chức [cần xác định]**; nếu tự vận hành thì Ceph RGW, SeaweedFS hoặc Garage, chọn theo năng lực vận hành và kết quả PoC.
- **Không ưu tiên MinIO OSS bản cũ cho triển khai mới:** repository `minio/minio` được archive ngày 25/04/2026, bản OSS không còn được duy trì. Nếu cân nhắc AIStor phải đánh giá riêng điều kiện cấp phép, yêu cầu hạ tầng và mức độ phù hợp.
- Phải kiểm chứng tương thích S3, object lock, policy và lifecycle **theo phiên bản thực tế**; không đồng nhất "tương thích API S3" với đầy đủ chức năng mở rộng của AWS S3.
