"""Kiểm tra quy tắc kiến trúc bằng AST, không bằng quy ước.

Hai kiểm tra bắt buộc ở mục 15 của docs/c4-04b-code-structure.md:

1. `domain` và `utils` không import SDK sản phẩm hay framework web.
2. Mọi use case ghi đều đi qua `LifecyclePolicy`/`RelationshipPolicy` và `AuditPort`,
   tức không có đường ghi nào vòng qua ranh buộc nghiệp vụ (POC-20 kiểm từ bên ngoài).
"""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "document_service"
FORBIDDEN_IN_DOMAIN = ("httpx", "boto3", "botocore", "fastapi", "uvicorn", "sqlite3", "jwt")
FORBIDDEN_IN_UTILS = FORBIDDEN_IN_DOMAIN + ("pydantic_settings",)


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
    """Đường dẫn module **đầy đủ** của mọi import trong một file.

    Khác `_imports`: giữ nguyên `document_service.application.metadata_builder` thay vì
    cắt về `document_service`, nên kiểm được phụ thuộc tới một package con cụ thể.
    """
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

        Sơ đồ hướng phụ thuộc có đúng một cạnh `adapter.inbound → application`: inbound
        dựng command và gọi use case. Mọi file adapter khác — toàn bộ `adapter.outbound`,
        nơi X24 từng vi phạm — không được biết tới tầng application.
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
    """Đường ghi phải đi qua policy và audit."""

    def test_status_change_goes_through_lifecycle_policy(self) -> None:
        """Chỉ ApproveVersionUseCase ghi `status`, và phải qua LifecyclePolicy."""
        path = SRC / "application" / "usecase" / "approve_version.py"
        source = path.read_text(encoding="utf-8")
        assert "self._policies.lifecycle.transition" in source
        assert source.index("intents.create(intent)") < source.index("self._saga.resume(intent)")
        saga = SRC / "application" / "orchestration" / "status_change_saga.py"
        assert "patch_controlled_fields" in saga.read_text(encoding="utf-8")

    def test_write_use_cases_record_audit(self) -> None:
        """Mọi use case ghi đều gọi `_record` để ghi audit (bất biến I12)."""
        write_use_cases = (
            "register_document.py",
            "create_version.py",
            "approve_version.py",
            "relationships.py",
            "access_policy.py",
        )
        for name in write_use_cases:
            source = (SRC / "application" / "usecase" / name).read_text(encoding="utf-8")
            assert "self._record(" in source, name

    def test_relationship_write_checks_rebind(self) -> None:
        """Khai báo quan hệ luôn kiểm tra ràng buộc không đổi đích (I6)."""
        source = (SRC / "application" / "usecase" / "relationships.py").read_text(encoding="utf-8")
        assert "assert_target_not_rebound" in source

    def test_version_creation_uses_intent_before_object(self) -> None:
        """Intent được ghi trước khi ghi object (mục 3.5 báo cáo)."""
        source = (SRC / "application" / "usecase" / "create_version.py").read_text(encoding="utf-8")
        intent_index = source.index("intents.create(intent)")
        saga_index = source.index("_run_saga(")
        assert intent_index < saga_index
