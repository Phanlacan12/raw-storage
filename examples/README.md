# examples/ — ví dụ chạy thử

Sáu ví dụ đầu chạy với profile `fake`, **không cần hạ tầng**: không OpenMetadata, không Object Storage, không database. Ví dụ 07 cần hạ tầng thật và tự in hướng dẫn nếu thiếu biến môi trường.

## File PDF mẫu

[fixtures/](fixtures/) chứa năm PDF thật (mỗi file hơn 1 KB, mở được bằng trình đọc PDF bất kỳ) dùng cho ví dụ 08. Chúng được commit sẵn nên bình thường không phải sinh lại. Muốn đổi nội dung:

```bash
uv run python examples/fixtures/generate_pdfs.py
```

Script tự viết cấu trúc PDF 1.4, không kéo thêm dependency nào — ví dụ chỉ cần file PDF hợp lệ để chứng minh service xử lý đúng nội dung nhị phân, không cần trình bày đẹp.

Ví dụ 07 mặc định tự sinh nội dung upload. Muốn đẩy một file có sẵn trên máy lên S3 thật:

```bash
DS_EXAMPLE_FILE=/duong/dan/toi/file.pdf uv run python examples/07_openmetadata_real.py
```

## Chạy

```bash
conda activate rawstorage
uv sync --all-extras --dev

uv run python examples/run_all.py          # chạy tuần tự 01–06, dừng ở ví dụ đầu tiên lỗi
uv run python examples/01_quickstart.py    # hoặc chạy từng ví dụ
make examples                              # tương đương run_all.py
```

Mỗi bước in `[OK  ]` hoặc `[SAI ]`; gặp `[SAI ]` thì ví dụ dừng với mã lỗi khác 0, nên `run_all.py` dùng được như một bài kiểm tra khói sau khi sửa code.

## Danh sách

| Ví dụ | Nội dung | Kiểm chứng |
|---|---|---|
| [01_quickstart.py](01_quickstart.py) | Vòng đời một tài liệu qua API: đăng ký → 2 phiên bản → duyệt → tìm kiếm → tải → audit | I1, I2, I8, I13, POC-02, POC-13, POC-14 |
| [02_project_documents.py](02_project_documents.py) | Use case URD–SRS–SAD của Project A, quan hệ theo phiên bản, tạo SRS v2.1 | mục 2.8 báo cáo, POC-05, POC-06, POC-09 |
| [03_failure_recovery.py](03_failure_recovery.py) | Object đã ghi, catalog lỗi → `RetryPending` → job đối soát phục hồi | mục 3.5 báo cáo, POC-08, POC-18, POC-21 |
| [04_health_and_degraded.py](04_health_and_degraded.py) | `/livez` không đổi khi phụ thuộc sập, `/readyz` chuyển `ServiceMode`, API ghi trả `503` + `Retry-After` | `c4-04b` mục 10 |
| [05_source_sync.py](05_source_sync.py) | Đồng bộ từ thư mục giả làm file share; sửa file ở nguồn tạo phiên bản mới | D17, POC-12 |
| [06_outbox_events.py](06_outbox_events.py) | Outbox bền vững + webhook receiver thật: downstream lỗi thì sự kiện không mất | POC-11, `c4-04b` mục 11.7 |
| [07_openmetadata_real.py](07_openmetadata_real.py) | Chạy trên OpenMetadata + Object Storage **thật**: upload file thật → duyệt → tải lại qua presigned URL và đối chiếu checksum; đo được POC-19 | POC-19, POC-20, POC-22 |
| [08_project_documents_real.py](08_project_documents_real.py) | Ví dụ 02 chạy lại trên hạ tầng **thật** với **PDF thật** trong [fixtures/](fixtures/): URD–SRS–SAD, quan hệ theo phiên bản, tải PDF về đối chiếu checksum | POC-05, POC-06, POC-09 |

## Hai ví dụ đáng đọc trước

- **03** cho thấy vì sao kiến trúc có `UploadIntent` và job đối soát: ghi object và đăng ký metadata **không** nằm trong một giao dịch, nên lỗi một phía là chuyện bình thường, và cách xử lý là phục hồi được chứ không phải giả vờ nguyên tử.
- **04** cho thấy ranh giới `livez` ↔ `readyz`: trộn hai thứ này là lý do nhiều hệ thống bị orchestrator restart hàng loạt khi một phụ thuộc chậm.

## Ví dụ cũng là test

Các ví dụ dùng chính code trong `src/`, không có bản sao logic nào. Hai lỗi thiết kế thật đã bị ví dụ bắt được và đã sửa:

- ví dụ 06 cho thấy outbox store và downstream dùng chung `ResilientCallExecutor` sẽ làm circuit breaker của webhook báo health của outbox là `DOWN` — hai phụ thuộc khác nhau phải có executor riêng;
- ví dụ 03 xác nhận job phục hồi dùng lại đúng `document_version_id` trong intent, nên không nhân đôi phiên bản.

`mypy` và `pylint` chạy trên `src/`; đúng đắn của `examples/` được bảo đảm bằng cách **chạy thật** chúng (`make examples`), vì ví dụ sai thì dừng ngay với mã lỗi.
