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

## Yêu cầu trước khi dựng

Cần một container runtime. Trên macOS, cách ít bước nhất là
[Docker Desktop](https://www.docker.com/products/docker-desktop/) (chọn đúng bản
Apple Silicon hoặc Intel). Toàn bộ stack ăn khoảng **4–5 GB RAM**, nên vào
Docker Desktop → Settings → Resources đặt Memory tối thiểu 6 GB.

> **Apple Silicon:** không cần Rosetta. Đã kiểm bằng `docker manifest inspect`:
> cả bốn image (`openmetadata/server:1.12.0`, `mysql:8.0.35`,
> `opensearch:2.19.0`, `seaweedfs:3.68`) đều có bản `linux/arm64` native.
> Khi nâng phiên bản image thì kiểm lại, vì không phải tag nào cũng multi-arch.

## Thứ tự dựng

```bash
cp deploy/.env.example deploy/.env       # sửa mật khẩu và khóa trước khi chạy
make compose-up                          # dựng 4 container
make compose-ready                       # chờ OpenMetadata khỏe rồi tạo bucket
```

`make compose-ready` thay cho hai bước thủ công trước đây. Nó chờ healthcheck tối đa
20 phút — lần đầu OpenMetadata phải migrate database nên lâu — rồi gọi
[create_bucket.py](create_bucket.py).

Bucket được tạo bằng **boto3 trong `.venv`**, không dùng AWS CLI, vì AWS CLI là một
thứ phải cài riêng và dễ bị cấu hình trỏ sang endpoint khác. Script đọc đúng
`configs/storage.yml` + biến `DS_STORAGE__*` mà service đọc, nên không có chuyện bucket
nằm ở một nơi còn service tìm ở nơi khác. Chạy lại nhiều lần an toàn.

## Lấy bot token cho OpenMetadata

`DS_CATALOG__BOT_TOKEN` trong `.env.example` để **rỗng**. Không có token thì mọi lời gọi
API đều bị từ chối và `OmSchemaMigration` sẽ fail ngay bước đầu.

1. Mở http://localhost:8585, đăng nhập `admin@open-metadata.org` / `admin`.
2. Settings → Bots → `ingestion-bot`.
3. Copy JWT token, dán vào `DS_CATALOG__BOT_TOKEN=` trong `deploy/.env`.

Token có hạn sử dụng. Hết hạn thì sinh lại ở đúng màn hình đó.

## Chạy Document Service trỏ vào hạ tầng này

```bash
conda activate rawstorage
set -a && source deploy/.env && set +a     # nạp biến môi trường, gồm cả bí mật
uv run uvicorn document_service.main:app --port 8080
curl -s localhost:8080/readyz
```

Lần khởi động đầu, service tự chạy `OmSchemaMigration`: tạo drive service, thư mục gốc và các custom property bắt buộc. Nếu thiếu quyền hoặc lệch phiên bản đã cố định thì **service không nhận việc** — xem `/startupz` và log, đây là hành vi có chủ ý (POC-19).

## Chạy ví dụ 07 trên hạ tầng này

```bash
set -a && source deploy/.env && set +a
uv run python examples/07_openmetadata_real.py

# hoặc đẩy một file có sẵn trên máy lên S3 thật
DS_EXAMPLE_FILE=/duong/dan/toi/file.pdf uv run python examples/07_openmetadata_real.py
```

Ví dụ đi hết vòng đời: migration schema → health → upload → duyệt → tìm kiếm → tải về
đối chiếu checksum. Thiếu biến môi trường thì nó in hướng dẫn rồi dừng chứ **không** tự
chuyển sang profile fake.

## Hai cấu hình sai của OpenMetadata 1.12.0, đã sửa trong `compose-ready`

OpenMetadata 1.12.0 cấu hình loại `file` sai ở hai chỗ (loại `directory` thì đúng):

| | `file` (gốc) | `directory` | Hệ quả nếu không sửa |
|---|---|---|---|
| Mapping `extension` | `keyword` | `flat_object` | File không vào được search index → search rỗng, tab Lineage lỗi |
| Aggregation search | có trên field gốc `extension` | không | mọi `/search/query` trên file trả 500 |

`make compose-ready` chạy [patch_openmetadata.py](patch_openmetadata.py) để sửa cả hai.
Sau đó Search API lọc được theo custom property (POC-19 đạt) **và** quan hệ hiện trên
tab Lineage. Chỉ sửa một trong hai thì luôn hỏng một thứ — trước khi tìm ra chỗ thứ hai,
điều này từng trông như phải chọn giữa search và lineage.

Chạy lại riêng bản vá bằng `make compose-patch` khi: xoá `deploy/data`, chạy Reindex
trong Settings → Applications (nó tạo lại index theo mapping gốc), hoặc nâng phiên bản
OpenMetadata. Script idempotent.

Bước sửa search settings cần quyền admin. Script đăng nhập bằng `OM_ADMIN_EMAIL` /
`OM_ADMIN_PASSWORD`, mặc định là tài khoản `admin@open-metadata.org` / `admin` của
docker-compose dev.

## Xem quan hệ trên giao diện OpenMetadata

Mặc định `configs/relationship_store.yml` để `kind: sqlite`: quan hệ nằm trong
`local_data/document_service.sqlite` và OpenMetadata không biết gì về chúng. Muốn chúng
hiện trên giao diện thì dùng `kind: lineage`:

```bash
set -a && source deploy/.env && set +a
DS_RELATIONSHIP__KIND=lineage uv run python examples/08_project_documents_real.py
```

Rồi mở http://localhost:8585 → Explore → chọn một phiên bản (File entity) → tab
**Lineage**.

## Chạy test tích hợp

```bash
set -a && source deploy/.env && set +a
uv run pytest tests/integration
```

Thiếu biến `DS_CATALOG__BASE_URL` hoặc `DS_STORAGE__ENDPOINT` thì các test này tự bỏ qua.

## Dữ liệu nằm ở đâu

Stack dùng **bind mount** chứ không dùng named volume của Docker, nên dữ liệu nằm ngay
trong thư mục này và nhìn thấy được bằng Finder:

```
deploy/data/mysql/        database của OpenMetadata
deploy/data/opensearch/   search index
deploy/data/objectstore/  object thật của SeaweedFS
```

`deploy/data/` đã nằm trong `.gitignore`. Vì không còn named volume, `down -v` **không**
xoá dữ liệu nữa — muốn xoá thì xoá thư mục.

## Dọn môi trường

```bash
make compose-down                        # dừng và xoá container
rm -rf deploy/data                       # xoá dữ liệu hạ tầng (mysql, index, object)
rm -f local_data/document_service.sqlite # registry intent/audit cục bộ
```
