"""Khởi tạo schema trên OpenMetadata: drive service, thư mục gốc, custom property.

Theo mục 5, điểm 3 của docs/c4-04b-code-structure.md: custom property **chỉ có nghĩa
khi đã đăng ký trước**. `OmSchemaMigration.run_on_startup()` vì vậy **fail fast** nếu
thiếu trường bắt buộc, thay vì để service âm thầm ghi `extension` không lọc được —
đúng rủi ro mà test case POC-19 kiểm chứng.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from document_service.adapter.outbound.openmetadata import endpoints
from document_service.adapter.outbound.openmetadata.client import OmHttpClient
from document_service.adapter.outbound.openmetadata.endpoints import OmFqnBuilder
from document_service.config import CatalogSettings
from document_service.domain.errors import DomainError
from document_service.utils.logging_setup import get_logger

_LOGGER = get_logger(__name__)
_STRING_PROPERTY = "string"


class SchemaNotReadyError(DomainError):
    """Schema của catalog chưa đủ điều kiện để service nhận việc."""


@dataclass(frozen=True, slots=True)
class PropertyDefinition:
    """Định nghĩa một custom property cần có trên entity type."""

    name: str
    property_type: str = _STRING_PROPERTY
    description: str = ""


class OmDriveServiceProvisioner:
    """Bảo đảm drive service và thư mục gốc của kho đã tồn tại."""

    def __init__(self, client: OmHttpClient, settings: CatalogSettings) -> None:
        """Nhận client HTTP và cấu hình catalog."""
        self._client = client
        self._settings = settings
        self._fqn = OmFqnBuilder(settings.drive_service_name, settings.root_directory)

    async def ensure_drive_service(self) -> str:
        """Tạo hoặc cập nhật drive service, trả về FQN."""
        payload = await self._client.put(
            endpoints.DRIVE_SERVICES,
            {
                "name": self._settings.drive_service_name,
                "serviceType": "CustomDrive",
                "description": "Kho raw data dung chung",
                "connection": {"config": {"type": "CustomDrive"}},
            },
        )
        return str(payload.get("fullyQualifiedName", self._fqn.service_fqn))

    async def ensure_root_directory(self) -> str:
        """Tạo hoặc cập nhật thư mục gốc, trả về FQN."""
        payload = await self._client.put(
            endpoints.DIRECTORIES,
            {
                "name": self._settings.root_directory,
                "service": self._settings.drive_service_name,
                "description": "Thu muc goc cua kho raw data",
            },
        )
        return str(payload.get("fullyQualifiedName", self._fqn.root_fqn))


class OmCustomPropertyRegistrar:
    """Đăng ký và kiểm tra custom property trên entity type."""

    def __init__(self, client: OmHttpClient) -> None:
        """Nhận client HTTP."""
        self._client = client

    async def existing_properties(self, entity_type: str) -> set[str]:
        """Tên các custom property đã có trên một entity type."""
        payload = await self._client.get(f"{endpoints.METADATA_TYPES}/name/{entity_type}")
        items = payload.get("customProperties", []) or []
        return {
            str(item.get("name")) for item in items if isinstance(item, dict) and item.get("name")
        }

    async def ensure_properties(
        self, entity_type: str, definitions: list[PropertyDefinition]
    ) -> list[str]:
        """Đăng ký các property còn thiếu, trả về danh sách vừa thêm."""
        payload = await self._client.get(f"{endpoints.METADATA_TYPES}/name/{entity_type}")
        type_id = str(payload.get("id", ""))
        if not type_id:
            raise SchemaNotReadyError(f"cannot read entity type {entity_type}")
        existing = await self.existing_properties(entity_type)
        added: list[str] = []
        for definition in definitions:
            if definition.name in existing:
                continue
            await self._client.patch(
                f"{endpoints.METADATA_TYPES}/{type_id}",
                [
                    {
                        "op": "add",
                        "path": "/customProperties/-",
                        "value": self._as_payload(definition),
                    }
                ],
            )
            added.append(definition.name)
        return added

    async def assert_filterable(self, entity_type: str, names: list[str]) -> None:
        """Báo lỗi nếu còn trường bắt buộc chưa đăng ký.

        Lưu ý giới hạn đã biết: đăng ký được **không** đồng nghĩa lọc được qua UI
        facet (issue #25217). Phần đó phải đo riêng ở POC-19.
        """
        existing = await self.existing_properties(entity_type)
        missing = [name for name in names if name not in existing]
        if missing:
            raise SchemaNotReadyError(
                f"custom property is not registered on {entity_type}: {', '.join(missing)}"
            )

    def _as_payload(self, definition: PropertyDefinition) -> dict[str, Any]:
        """Payload đăng ký một custom property."""
        return {
            "name": definition.name,
            "description": definition.description or definition.name,
            "propertyType": {"id": definition.property_type, "type": "type"},
        }


class OmSchemaMigration:
    """Chạy toàn bộ bước khởi tạo schema khi service start."""

    def __init__(self, client: OmHttpClient, settings: CatalogSettings) -> None:
        """Nhận client HTTP và cấu hình catalog."""
        self._client = client
        self._settings = settings
        self._provisioner = OmDriveServiceProvisioner(client, settings)
        self._registrar = OmCustomPropertyRegistrar(client)

    async def run_on_startup(self) -> None:
        """Dựng drive service, thư mục gốc và custom property bắt buộc."""
        version = await self._client.server_version()
        if not self._client.pin.matches(version):
            raise SchemaNotReadyError(
                f"server {version} differs from the pinned version "
                f"{self._client.pin.pinned_version}"
            )
        await self._provisioner.ensure_drive_service()
        await self._provisioner.ensure_root_directory()
        definitions = [PropertyDefinition(name=name) for name in self._settings.required_properties]
        for entity_type in ("file", "directory"):
            added = await self._registrar.ensure_properties(entity_type, definitions)
            if added:
                _LOGGER.info(
                    "registered custom property",
                    extra={"entity_type": entity_type, "added": ",".join(added)},
                )
            await self._registrar.assert_filterable(
                entity_type, list(self._settings.required_properties)
            )
