"""Kiểm tra quy tắc kiến trúc bằng AST, không bằng quy ước.

Nhóm `TestDependencyRules` giữ nguyên bốn luật phụ thuộc đã AST từ B1.
Nhóm `TestWritePathRules` được viết lại ở B20 theo
`docs/c4-09-lld.md` mục 15.5 — tự phát hiện `WriteUseCase`, kiểm bằng
tập đường dẫn chấm trên `ast.Call`, so thứ tự bằng `lineno`.
Luật thứ bảy ở mục 15.6 (`test_doc_class_names_exist_in_source`) chạy
chế độ warn cho tới khi B21 đồng bộ `c4-04b`/`c4-09`.
"""

from __future__ import annotations

import ast
import re
import warnings
from importlib.util import resolve_name
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "document_service"
DOCS = Path(__file__).resolve().parents[2] / "docs"
FORBIDDEN_IN_DOMAIN = ("httpx", "boto3", "botocore", "fastapi", "uvicorn", "sqlite3", "jwt")
FORBIDDEN_IN_UTILS = FORBIDDEN_IN_DOMAIN + ("pydantic_settings",)

USECASE_DIR = SRC / "application" / "usecase"
PORT_FILE = SRC / "domain" / "port.py"

EXPECTED_PORTS = frozenset(
    {
        "MetadataCatalogPort",
        "RelationshipStorePort",
        "ObjectStorePort",
        "IntentStorePort",
        "PolicyDecisionPort",
        "EventPublisherPort",
        "AuditPort",
        "DocumentLockPort",
    }
)

# Tên sản phẩm ngoài, viết tắt, hoặc tên lớp của thư viện khác —
# cổng luật 7 bỏ qua. Mở rộng có ý thức khi B21 phát hiện thêm.
ALLOWLIST_EXTERNAL = {
    "Directory",
    "File",
    "LineageDetails",
    "VersionSet",
    "DataHubFile",
    "SpooledTemporaryFile",
    "NamedTemporaryFile",
    "StrEnum",
    "BaseModel",
    "BaseSettings",
    "APIRouter",
    "FastAPI",
    "Request",
    "Response",
    "JSONResponse",
    "UploadFile",
    "Depends",
    "Header",
    "Query",
    "Form",
    "ABC",
    "Protocol",
    "Generic",
    "TypeVar",
    "Awaitable",
    "AsyncIterator",
    "Callable",
    "Clock",
    "SystemClock",
    "FixedClock",
    "ThreadOffloader",
    "ConcurrencyLimiter",
    "Checksum",
    "Path",
    "Session",
    "ConfigDict",
    "Field",
    "Docker",
    "OpenMetadata",
    "DataHub",
    "KB",
    "DMS",
    "ECM",
    "JSON",
    "ETag",
    "UUID",
    "ULID",
    "URL",
    "URI",
    "API",
    "REST",
    "MCP",
    "IdP",
    "SSO",
    "OIDC",
    "SAML",
    "OAuth",
    "JWT",
    "JWKS",
    "RBAC",
    "ABAC",
    "ACID",
    "RAM",
    "CPU",
    "IOPS",
    "RPO",
    "RTO",
    "TTL",
    "DNS",
    "TLS",
    "HTTP",
    "HTTPS",
    "PDF",
    "DOCX",
    "XLSX",
    "PPTX",
    "YAML",
    "SQL",
    "CI",
    "CD",
    "PR",
    "VC",
    "WHY",
    "WHAT",
    "HOW",
    "PATCH",
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "HEAD",
    "ES",
    "AWS",
    "CSV",
    "AI",
    "URD",
    "SRS",
    "SAD",
    "LLD",
    "HLD",
    "PoC",
    "PoCs",
    "POC",
    "FAQ",
    "KPI",
    "ML",
    "RAG",
    "NFR",
    "FR",
    "S3",
    "RGW",
    # Placeholder cho bước/vai trong giao thức mục 6 của c4-08, c4-09.
    "Bx",
    "Fx",
    "Gx",
    "Dx",
    "Ix",
    "Px",
    "Xn",
}

PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]+$")
BACKTICK_RE = re.compile(r"`([^`]+)`")


def _imports(path: Path) -> set[str]:
    """Tên gốc của mọi module được import trong một file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _imported_modules(path: Path) -> set[str]:
    """Đường dẫn module **đầy đủ** của mọi import trong một file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            package = ".".join(path.parent.relative_to(SRC.parent).parts)
            module = resolve_name("." * node.level + (node.module or ""), package)
            modules.add(module)
            modules.update(f"{module}.{alias.name}" for alias in node.names)
    return modules


def _depends_on(path: Path, package: str) -> set[str]:
    """Các module được import thuộc `package` (chính nó hoặc package con)."""
    return {
        module
        for module in _imported_modules(path)
        if module == package or module.startswith(f"{package}.")
    }


def _python_files(package: str) -> list[Path]:
    """Danh sách file python trong một package của service."""
    return sorted((SRC / package).rglob("*.py"))


def _base_name(node: ast.expr) -> str | None:
    """Tên base class từ `ast.ClassDef.bases` — xử lý cả `WriteUseCase[...]`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        return _base_name(node.value)
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _dotted_path(node: ast.expr) -> str | None:
    """Chuỗi đường dẫn chấm cho `ast.Attribute` chain: `self._policies.lifecycle.transition`."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _discover_write_use_cases() -> list[ast.ClassDef]:
    """Parse tất cả file use case, trả về `ClassDef` kế thừa `WriteUseCase`.

    Dò base qua `ast.Name` hoặc `ast.Subscript` (`WriteUseCase[Cmd, Res]`).
    """
    classes: list[ast.ClassDef] = []
    for path in sorted(USECASE_DIR.glob("*.py")):
        if path.name in {"__init__.py", "base.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                if _base_name(base) == "WriteUseCase":
                    # Dán file cha để báo lỗi nói được chỗ.
                    node._source_file = path  # type: ignore[attr-defined]
                    classes.append(node)
                    break
    return classes


def _calls_in(cls: ast.ClassDef) -> list[tuple[str, int]]:
    """Mọi `ast.Call` trong class: (đường dẫn chấm, lineno)."""
    calls: list[tuple[str, int]] = []
    for node in ast.walk(cls):
        if isinstance(node, ast.Call):
            dotted = _dotted_path(node.func)
            if dotted is not None:
                calls.append((dotted, node.lineno))
    return calls


WRITE_USE_CASES = _discover_write_use_cases()


class TestDependencyRules:
    """Quy tắc phụ thuộc giữa các lớp."""

    @pytest.mark.parametrize("path", _python_files("domain"), ids=lambda item: item.name)
    def test_domain_has_no_product_sdk(self, path: Path) -> None:
        """Lõi miền không biết tới SDK của sản phẩm hay framework web."""
        leaked = _imports(path) & set(FORBIDDEN_IN_DOMAIN)
        assert not leaked, f"{path.name} import {leaked}"

    @pytest.mark.parametrize("path", _python_files("utils"), ids=lambda item: item.name)
    def test_utils_only_stdlib(self, path: Path) -> None:
        """utils chỉ dùng stdlib và không import ngược vào service."""
        imports = _imports(path)
        assert not imports & set(FORBIDDEN_IN_UTILS)
        internal = {name for name in imports if name == "document_service"}
        assert not internal or path.name == "logging_setup.py"

    @pytest.mark.parametrize("path", _python_files("application"), ids=lambda item: item.name)
    def test_application_does_not_import_adapters(self, path: Path) -> None:
        """Lớp application chỉ biết port, không biết adapter cụ thể."""
        leaked = _depends_on(path, "document_service.adapter")
        assert not leaked, f"{path.name} import {leaked}"

    @pytest.mark.parametrize("path", _python_files("adapter"), ids=lambda item: item.name)
    def test_adapter_does_not_import_application(self, path: Path) -> None:
        """Adapter không phụ thuộc ngược lên application (luật 4 của c4-09 mục 2.3).

        Sơ đồ hướng phụ thuộc có đúng một cạnh `adapter.inbound → application`.
        """
        leaked = _depends_on(path, "document_service.application")
        driving_side = path.is_relative_to(SRC / "adapter" / "inbound")
        assert driving_side or not leaked, f"{path.name} import {leaked}"

    @pytest.mark.parametrize("path", _python_files("domain"), ids=lambda item: item.name)
    def test_domain_does_not_import_config(self, path: Path) -> None:
        """Lõi miền không phụ thuộc cấu hình."""
        leaked = _depends_on(path, "document_service.config")
        assert not leaked, f"{path.name} import {leaked}"


class TestWritePathRules:
    """Đường ghi phải đi qua policy và audit (c4-09 mục 15.5)."""

    def test_write_use_case_set_is_auto_discovered(self) -> None:
        """Tập `WriteUseCase` không rỗng — đổi tên base class làm test đỏ."""
        names = sorted(cls.name for cls in WRITE_USE_CASES)
        assert names, (
            "Không phát hiện được ClassDef nào kế thừa `WriteUseCase` dưới "
            f"{USECASE_DIR}. Có thể đổi tên base class?"
        )
        # Năm use case ghi theo c4-09 mục 4.1 — nếu thêm use case ghi mới,
        # cập nhật kỳ vọng ở dòng dưới và tài liệu.
        assert len(names) >= 5, f"Chờ ít nhất 5 WriteUseCase, có {names}"

    def test_write_use_cases_record_audit(self) -> None:
        """Mọi `WriteUseCase` gọi `_record` để ghi audit (bất biến I12)."""
        missing: list[str] = []
        for cls in WRITE_USE_CASES:
            dotted = {path for path, _ in _calls_in(cls)}
            if not any(path.endswith("._record") or path == "self._record" for path in dotted):
                source: Path = cls._source_file  # type: ignore[attr-defined]
                missing.append(f"{source.name}:{cls.name}")
        assert not missing, f"WriteUseCase thiếu `self._record`: {missing}"

    def test_approve_version_goes_through_lifecycle_policy(self) -> None:
        """`ApproveVersionUseCase` phải đi qua `LifecyclePolicy.transition`."""
        cls = next(c for c in WRITE_USE_CASES if c.name == "ApproveVersionUseCase")
        dotted = {path for path, _ in _calls_in(cls)}
        assert "self._policies.lifecycle.transition" in dotted, (
            f"`ApproveVersionUseCase` không gọi `self._policies.lifecycle.transition`; "
            f"các lời gọi thấy được: {sorted(dotted)}"
        )

    def test_declare_relationship_checks_rebind(self) -> None:
        """`DeclareRelationshipUseCase` phải kiểm `assert_target_not_rebound` (I6)."""
        cls = next(c for c in WRITE_USE_CASES if c.name == "DeclareRelationshipUseCase")
        dotted = {path for path, _ in _calls_in(cls)}
        assert any("assert_target_not_rebound" in path for path in dotted), (
            f"`DeclareRelationshipUseCase` không gọi `assert_target_not_rebound`; "
            f"các lời gọi thấy được: {sorted(dotted)}"
        )

    def test_write_use_cases_write_intent_before_external_calls(self) -> None:
        """`intents.create` phải chạy **trước** mọi lời gọi `objects.`/`_saga.`/`patch_`.

        Chỉ áp dụng cho `WriteUseCase` có `intents.create` — hiện là
        `CreateVersionUseCase` và `ApproveVersionUseCase`.
        """
        # `_saga` khớp cả `self._saga.resume` (approve_version) và
        # `self._run_saga(...)` helper trigger saga (create_version);
        # `objects.` cho `self.ports.objects.*`; `patch_` cho `catalog.patch_*`.
        external_markers = ("objects.", "_saga", "patch_")
        checked: list[str] = []
        for cls in WRITE_USE_CASES:
            calls = _calls_in(cls)
            intent_lines = [lineno for path, lineno in calls if path.endswith("intents.create")]
            if not intent_lines:
                continue
            first_intent = min(intent_lines)
            external = [
                (path, lineno)
                for path, lineno in calls
                if any(marker in path for marker in external_markers)
            ]
            earlier = [(p, ln) for p, ln in external if ln < first_intent]
            assert not earlier, (
                f"{cls.name}: `intents.create` ở dòng {first_intent} nhưng có lời "
                f"gọi phụ thuộc ngoài TRƯỚC nó: {earlier}"
            )
            checked.append(cls.name)
        # Đảm bảo luật thật sự chạm ít nhất một use case — nếu không,
        # đổi tên `intents.create` làm luật này trở nên vô dụng cần biết.
        assert checked, (
            "Không WriteUseCase nào gọi `intents.create`; luật thứ tự intent "
            "không có đối tượng để kiểm — có thể method đã bị đổi tên?"
        )

    def test_port_surface_is_eight_abstract_classes(self) -> None:
        """Bề mặt port đóng băng: đúng 8 `ClassDef` kế thừa `ABC` ở `domain/port.py`."""
        tree = ast.parse(PORT_FILE.read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                if _base_name(base) == "ABC":
                    found.add(node.name)
                    break
        assert found == EXPECTED_PORTS, (
            f"Bề mặt port lệch: thiếu {EXPECTED_PORTS - found}, thừa {found - EXPECTED_PORTS}. "
            "Thêm/xóa port là hành động có ý thức: cập nhật c4-04b mục 3 và c4-09 mục 3.7."
        )

    def test_doc_class_names_exist_in_source(self) -> None:
        """Mọi tên PascalCase trong backtick ở `c4-04b`/`c4-09` phải tồn tại trong `src/`.

        Chế độ warn tạm thời cho tới khi B21 đồng bộ hai tài liệu — hiện chỉ in
        cảnh báo để không block B20. Sau B21 chuyển sang `assert` (gate GT/G2).
        """
        source_classes = _collect_source_class_names()
        missing: dict[str, set[str]] = {}
        for doc in ("c4-04b-code-structure.md", "c4-09-lld.md"):
            doc_path = DOCS / doc
            if not doc_path.exists():
                continue
            names = _collect_doc_class_names(doc_path)
            miss = names - source_classes - ALLOWLIST_EXTERNAL
            if miss:
                missing[doc] = miss
        if missing:
            summary = "; ".join(f"{doc}: {sorted(names)}" for doc, names in sorted(missing.items()))
            warnings.warn(
                f"[B20 warn] Tên lớp trong docs không có trong src/: {summary}. "
                "B21 phải đồng bộ hoặc mở rộng ALLOWLIST_EXTERNAL.",
                stacklevel=1,
            )


def _collect_source_class_names() -> set[str]:
    """Mọi `ClassDef.name` dưới `src/`."""
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names.add(node.name)
    return names


def _collect_doc_class_names(doc_path: Path) -> set[str]:
    """Mọi chuỗi backtick trong tài liệu khớp PascalCase."""
    text = doc_path.read_text(encoding="utf-8")
    names: set[str] = set()
    for match in BACKTICK_RE.findall(text):
        # Lấy identifier đầu nếu có dấu `.` hay `(`, ví dụ `Foo.bar()` -> `Foo`.
        head = re.split(r"[.\[(\s,]", match, maxsplit=1)[0]
        if PASCAL_RE.match(head):
            names.add(head)
    return names
