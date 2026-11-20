"""Sinh bộ PDF mẫu cho ví dụ 08, không cần thư viện ngoài.

Chạy: uv run python examples/fixtures/generate_pdfs.py

Viết thẳng cấu trúc PDF 1.4 thay vì kéo reportlab về: ví dụ chỉ cần file PDF **thật,
mở được** để chứng minh service xử lý đúng nội dung nhị phân, chứ không cần trình bày
đẹp. Thêm một dependency chỉ để tạo bốn file vài KB là không đáng.

File sinh ra được commit vào repo, nên bình thường không phải chạy lại script này.
Chạy lại khi muốn đổi nội dung mẫu.

Nội dung để ASCII không dấu: font Helvetica chuẩn của PDF dùng bảng mã WinAnsi, chữ
tiếng Việt có dấu sẽ hiện sai khi mở bằng trình đọc PDF.
"""

from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent

# (ten file, tieu de, cac dong noi dung)
DOCUMENTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "URD-PROJECT-A-v1.0.pdf",
        "User Requirements Document - Project A - v1.0",
        (
            "1. Scope",
            "   First draft of the user requirements for Project A.",
            "2. Stakeholders",
            "   Business owner, operations team, end users.",
            "3. Requirements",
            "   UR-01  The system stores documents with their full version history.",
            "   UR-02  Every document version is immutable once approved.",
        ),
    ),
    (
        "URD-PROJECT-A-v1.2.pdf",
        "User Requirements Document - Project A - v1.2",
        (
            "1. Scope",
            "   Updated after the review meeting on 2026-03-14.",
            "2. Changes against v1.0",
            "   Added UR-03 on retention, clarified wording of UR-02.",
            "3. Requirements",
            "   UR-01  The system stores documents with their full version history.",
            "   UR-02  An approved document version can never be modified in place.",
            "   UR-03  Documents carry a retention policy inherited from the project.",
        ),
    ),
    (
        "SRS-PROJECT-A-v2.0.pdf",
        "Software Requirements Specification - Project A - v2.0",
        (
            "1. Purpose",
            "   Derived from URD v1.2. Supersedes SRS v1.0.",
            "2. Functional requirements",
            "   FR-01  Upload a document version and store its bytes in object storage.",
            "   FR-02  Register metadata of every version in the catalog.",
            "   FR-03  Approve a version and mark it as the current one.",
            "3. Non functional requirements",
            "   NFR-01 An upload must survive a catalog outage and be recoverable.",
        ),
    ),
    (
        "SRS-PROJECT-A-v2.1.pdf",
        "Software Requirements Specification - Project A - v2.1",
        (
            "1. Purpose",
            "   Minor update of v2.0. Relationships of v2.0 stay untouched.",
            "2. Changes against v2.0",
            "   Clarified FR-03, no change to the derived_from relationship.",
            "3. Functional requirements",
            "   FR-01  Upload a document version and store its bytes in object storage.",
            "   FR-02  Register metadata of every version in the catalog.",
            "   FR-03  Approving a version marks it current and obsoletes the previous one.",
        ),
    ),
    (
        "SAD-PROJECT-A-v1.1.pdf",
        "Software Architecture Document - Project A - v1.1",
        (
            "1. Context",
            "   References SRS v2.0.",
            "2. Containers",
            "   C2  Metadata catalog, OpenMetadata.",
            "   C6  Object storage, S3 compatible.",
            "   C10 Event publisher backed by a durable outbox.",
            "3. Key decision",
            "   Object bytes are written before catalog metadata; an upload intent makes",
            "   the gap recoverable without a distributed transaction.",
        ),
    ),
)


def _escape(text: str) -> str:
    """Thoát ký tự đặc biệt của chuỗi PDF."""
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(title: str, lines: tuple[str, ...]) -> bytes:
    """Dựng content stream: tiêu đề đậm rồi các dòng nội dung."""
    parts = ["BT", "/F2 14 Tf", "72 780 Td", f"({_escape(title)}) Tj", "ET"]
    parts += ["BT", "/F1 11 Tf", "72 740 Td", "16 TL"]
    for line in lines:
        parts.append(f"({_escape(line)}) Tj T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", errors="replace")


def _build_pdf(title: str, lines: tuple[str, ...]) -> bytes:
    """Dựng một file PDF 1.4 một trang, tự tính bảng xref."""
    stream = _content_stream(title, lines)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
    out += f"startxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def main() -> None:
    """Ghi toàn bộ PDF mẫu vào thư mục này."""
    for file_name, title, lines in DOCUMENTS:
        path = FIXTURES / file_name
        path.write_bytes(_build_pdf(title, lines))
        print(f"  {file_name:<28} {path.stat().st_size:>6} bytes")
    print(f"\nWrote {len(DOCUMENTS)} PDF files to {FIXTURES}")


if __name__ == "__main__":
    main()
