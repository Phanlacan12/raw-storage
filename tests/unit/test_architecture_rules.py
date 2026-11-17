"""Kiểm tra quy tắc kiến trúc bằng AST, không bằng quy ước.

Hai kiểm tra bắt buộc ở mục 15 của docs/c4-04b-code-structure.md:

1. `domain` và `utils` không import SDK sản phẩm hay framework web.
2. Mọi use case ghi đều đi qua `LifecyclePolicy`/`RelationshipPolicy` và `AuditPort`,
   tức không có đường ghi nào vòng qua ranh buộc nghiệp vụ (POC-20 kiểm từ bên ngoài).
"""

from __future__ import annotations

import ast
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
        source = path.read_text(encoding="utf-8")
        assert "document_service.adapter" not in source

    def test_domain_does_not_import_config(self) -> None:
        """Lõi miền không phụ thuộc cấu hình."""
        for path in _python_files("domain"):
            assert "document_service.config" not in path.read_text(encoding="utf-8")


class TestWritePathRules:
    """Đường ghi phải đi qua policy và audit."""

    def test_status_change_goes_through_lifecycle_policy(self) -> None:
        """Chỉ ApproveVersionUseCase ghi `status`, và phải qua LifecyclePolicy."""
        path = SRC / "application" / "usecase" / "approve_version.py"
        source = path.read_text(encoding="utf-8")
        assert "self._policies.lifecycle.transition" in source
        assert "patch_controlled_fields" in source

    def test_write_use_cases_record_audit(self) -> None:
        """Mọi use case ghi đều gọi `_record` để ghi audit (bất biến I12)."""
        write_use_cases = (
            "register_document.py",
            "create_version.py",
            "approve_version.py",
            "relationships.py",
            "search_documents.py",
        )
        for name in write_use_cases:
            source = (SRC / "application" / "usecase" / name).read_text(encoding="utf-8")
            assert "self._record(" in source, name

    def test_relationship_write_checks_rebind(self) -> None:
        """Khai báo quan hệ luôn kiểm tra ràng buộc không đổi đích (I6)."""
        source = (SRC / "application" / "usecase" / "relationships.py").read_text(
            encoding="utf-8"
        )
        assert "assert_target_not_rebound" in source

    def test_version_creation_uses_intent_before_object(self) -> None:
        """Intent được ghi trước khi ghi object (mục 3.5 báo cáo)."""
        source = (SRC / "application" / "usecase" / "create_version.py").read_text(
            encoding="utf-8"
        )
        intent_index = source.index("intents.create(intent)")
        saga_index = source.index("_run_saga(")
        assert intent_index < saga_index
