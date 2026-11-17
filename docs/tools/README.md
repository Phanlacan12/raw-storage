# Kiểm tra cú pháp sơ đồ Mermaid

`check-mermaid.mjs` trích mọi block ` ```mermaid ` trong các file `.md` của một thư mục và gọi `mermaid.parse()` trên từng block, in `OK`/`FAIL` kèm số dòng và thông báo lỗi.

## Cách chạy

```bash
mkdir -p /tmp/mmcheck && cd /tmp/mmcheck
npm init -y >/dev/null
npm i mermaid@11.12.0 jsdom@26.1.0
cp <đường dẫn>/docs/tools/check-mermaid.mjs .
node check-mermaid.mjs <đường dẫn>/docs
```

Kết thúc sẽ in `N diagram lỗi`. Yêu cầu: `0 diagram lỗi` trước khi commit tài liệu kiến trúc.

## Các lỗi đã gặp và quy tắc tránh

| Lỗi | Nguyên nhân | Quy tắc |
|---|---|---|
| `Expecting 'SOLID_ARROW'... got 'NEWLINE'` trong `sequenceDiagram` | Dấu `;` trong nội dung message hoặc `Note` bị hiểu là dấu kết thúc câu lệnh | **Không dùng `;` trong text của sequence diagram.** Thay bằng `—`, `·` hoặc `,` |
| Nhãn node flowchart bị cắt hoặc lỗi parse | Ký tự `(`, `[`, `#`, `;`, `"` trong nhãn không được bọc | **Luôn bọc nhãn trong dấu nháy kép:** `A["text"]`, nhãn mũi tên `-->|"text"|` |
| Kiểu generic trong `classDiagram` không render | Viết `string~~ tags` | Dùng `List~string~ tags` |
| Xuống dòng trong nhãn không có tác dụng | Dùng `\n` | Dùng `<br/>` |

Lưu ý: script chỉ kiểm tra **cú pháp**, không kiểm tra bố cục. Sơ đồ parse sạch vẫn có thể chật khi render; khi đó đổi `flowchart TB` ↔ `LR` hoặc tách sơ đồ.
