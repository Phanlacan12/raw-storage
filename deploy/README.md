# deploy/ — hạ tầng chạy thử

Toàn bộ file hạ tầng nằm trong thư mục này; thư mục gốc chỉ giữ mã nguồn và cấu hình.

> **Chỉ dùng cho phát triển và PoC.** Production theo [docs/c4-06-deployment.md](../docs/c4-06-deployment.md) mục 6.5 và 6.6: ưu tiên dịch vụ S3-compatible sẵn có của tổ chức, cố định phiên bản OpenMetadata, bucket đóng và service account quyền tối thiểu.

## Thành phần

| Service | Vai trò | Cổng |
|---|---|---|
| `mysql` | database của OpenMetadata | 3306 |
| `opensearch` | search index của OpenMetadata | 9200 |
| `openmetadata` | catalog (C2) | 8585 (API), 8586 (healthcheck) |
| `objectstore` | Object Storage tương thích S3 (C6), dùng SeaweedFS | 8333 (S3), 9333 |

Mỗi service có `healthcheck`, và `openmetadata` chờ `mysql` + `opensearch` khỏe mới khởi động.

## Thứ tự dựng

```bash
cp deploy/.env.example deploy/.env       # sửa mật khẩu và khóa trước khi chạy
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d
# chờ catalog khỏe
until curl -sf http://localhost:8586/healthcheck >/dev/null; do sleep 5; done
# tạo bucket trên object store
aws --endpoint-url http://localhost:8333 s3 mb s3://raw-documents
```

## Chạy Document Service trỏ vào hạ tầng này

```bash
conda activate rawstorage
set -a && source deploy/.env && set +a     # nạp biến môi trường, gồm cả bí mật
uv run uvicorn document_service.main:app --port 8080
curl -s localhost:8080/readyz
```

Lần khởi động đầu, service tự chạy `OmSchemaMigration`: tạo drive service, thư mục gốc và các custom property bắt buộc. Nếu thiếu quyền hoặc lệch phiên bản đã cố định thì **service không nhận việc** — xem `/startupz` và log, đây là hành vi có chủ ý (POC-19).

## Chạy test tích hợp

```bash
set -a && source deploy/.env && set +a
uv run pytest tests/integration
```

Thiếu biến `DS_CATALOG__BASE_URL` hoặc `DS_STORAGE__ENDPOINT` thì các test này tự bỏ qua.

## Dọn môi trường

```bash
docker compose -f deploy/docker-compose.yml down -v   # -v xoá cả volume dữ liệu
rm -f local_data/document_service.sqlite              # registry intent/audit cục bộ
```
