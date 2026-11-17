## Thay đổi gì

<!-- Mô tả ngắn: thay đổi này giải quyết vấn đề nào -->

## Checklist

- [ ] Đã chạy `make test` (mypy → pytest → pylint 10.00/10) và xanh
- [ ] Đã cập nhật `docs/c4-0*` nếu kiến trúc, port, bất biến hay luồng thay đổi
- [ ] Đã ghi kết quả test case PoC liên quan vào `docs/c4-08-tra-soat-code-vs-thiet-ke.md`
- [ ] Không thêm bí mật vào `configs/*.yml` (token và khóa chỉ qua biến môi trường)
- [ ] Nếu thêm phụ thuộc ngoài: adapter đã hiện thực `_probe_dependency()` và được đăng ký health
- [ ] Nếu thêm singleton: đã có `reset()` và được `conftest.py` dọn giữa các test

## Ảnh hưởng tới quyết định còn mở

<!-- Q2 intent store, Q4 relationship store, hoặc quyết định khác ở docs/c4-07 -->
