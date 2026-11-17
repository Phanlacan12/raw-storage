# configs/ — cấu hình hệ thống dạng YAML

Mỗi khối cấu hình một file, để sửa một thứ không phải đọc cả file lớn.

| File | Khóa gốc | Nội dung | Đọc kèm |
|---|---|---|---|
| `app.yml` | `app` | profile adapter (`fake`/`openmetadata`), tên service, tiền tố API, deadline request | plan mục "Ràng buộc môi trường" |
| `logging.yml` | `logging` | mức log, chọn JSON hay terminal | `docs/c4-04b-code-structure.md` mục 2.1 |
| `catalog.yml` | `catalog` | OpenMetadata: URL, phiên bản cố định, drive service, custom property bắt buộc | `docs/c4-04b` mục 5, 8 |
| `storage.yml` | `storage` | Object Storage S3: endpoint, bucket, prefix object, TTL link tải | `docs/c4-04` mục 4.6 |
| `intent_store.yml` | `intent` | chọn `sqlite` hay `s3_manifest`, chu kỳ đối soát, ngưỡng retry | quyết định **Q2** |
| `relationship_store.yml` | `relationship` | chọn `lineage` hay `sqlite` cho quan hệ theo phiên bản | quyết định **Q4** |
| `security.yml` | `security` | IdP/OIDC, nhóm quản trị, bắt buộc Idempotency-Key, TTL cache policy | `docs/c4-04b` mục 13 |
| `resilience.yml` | `resilience` | timeout, retry, breaker, bulkhead cho **từng** phụ thuộc | `docs/c4-04b` mục 11.3 |
| `health.yml` | `health` | TTL cache health, timeout probe, ngưỡng backlog, hạn chót khởi động | `docs/c4-04b` mục 10 |

## Thứ tự ưu tiên

```
tham số khởi tạo  >  biến môi trường  >  .env  >  configs/*.yml  >  mặc định trong code
```

Biến môi trường dùng tiền tố `DS_` và dấu `__` cho khối lồng nhau:

```bash
DS_APP__PROFILE=openmetadata
DS_CATALOG__BASE_URL=https://openmetadata.internal
DS_RESILIENCE__CATALOG__MAX_ATTEMPTS=3
```

Đổi thư mục cấu hình bằng `DS_CONFIG_DIR=/etc/document-service`.

## Bí mật không nằm trong YAML

`configs/` được commit vào repo, nên **không** đặt token hay khóa ở đây. Ba giá trị sau chỉ truyền qua biến môi trường hoặc secret manager:

| Giá trị | Biến môi trường |
|---|---|
| Bot token của OpenMetadata | `DS_CATALOG__BOT_TOKEN` |
| Access key của Object Storage | `DS_STORAGE__ACCESS_KEY` |
| Secret key của Object Storage | `DS_STORAGE__SECRET_KEY` |

## Môi trường khác nhau

Giữ `configs/` là cấu hình mặc định cho phát triển, rồi trỏ `DS_CONFIG_DIR` sang thư mục của từng môi trường (`configs.staging/`, hoặc ConfigMap khi chạy trên Kubernetes). Không thêm nhánh `if env == "prod"` trong code.
