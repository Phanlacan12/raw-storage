"""Cấu hình service: YAML trong `configs/` + biến môi trường.

Thứ tự ưu tiên, cao đến thấp: tham số truyền trực tiếp khi khởi tạo → **biến môi
trường** → file `.env` → **các file YAML trong `configs/`** → giá trị mặc định trong
code. Nhờ vậy YAML giữ cấu hình đọc được của hệ thống, còn bí mật (token, secret
key) chỉ đi qua biến môi trường.

Tham số timeout/retry/TTL tương ứng bảng mục 11.3 của docs/c4-04b-code-structure.md.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from document_service.domain.metadata_fields import FILTERABLE_FIELDS
from document_service.utils.singleton import SingletonMeta

CONFIG_DIR_ENV = "DS_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "configs"
CONFIG_FILE_ORDER = (
    "app.yml",
    "logging.yml",
    "catalog.yml",
    "storage.yml",
    "intent_store.yml",
    "relationship_store.yml",
    "lock.yml",
    "security.yml",
    "resilience.yml",
    "health.yml",
    "sync.yml",
    "events.yml",
)


def config_files() -> list[Path]:
    """Danh sách file YAML được nạp, theo thứ tự cố định."""
    base = Path(os.environ.get(CONFIG_DIR_ENV, DEFAULT_CONFIG_DIR))
    return [base / name for name in CONFIG_FILE_ORDER if (base / name).is_file()]


class AdapterProfile(StrEnum):
    """Bộ adapter được bật khi khởi động."""

    FAKE = "fake"
    OPENMETADATA = "openmetadata"


class IntentStoreKind(StrEnum):
    """Hai hiện thực của intent store, ứng với quyết định Q2 còn mở."""

    SQLITE = "sqlite"
    S3_MANIFEST = "s3_manifest"


class RelationshipStoreKind(StrEnum):
    """Hai hiện thực của relationship store, ứng với quyết định Q4 còn mở."""

    SQLITE = "sqlite"
    LINEAGE = "lineage"


class LockKind(StrEnum):
    """Hai hiện thực của document lock, ứng với quyết định Q12 (C13)."""

    IN_MEMORY = "in_memory"
    REDIS = "redis"


class AppSettings(BaseModel):
    """Cấu hình chung của service (configs/app.yml)."""

    profile: AdapterProfile = AdapterProfile.FAKE
    api_prefix: str = "/api/v1"
    service_name: str = "document-service"
    request_budget_seconds: float = 10.0


class LoggingSettings(BaseModel):
    """Cấu hình log (configs/logging.yml)."""

    level: str = "INFO"
    json_format: bool = False


class CatalogSettings(BaseModel):
    """Cấu hình OpenMetadata (configs/catalog.yml)."""

    base_url: str = "http://localhost:8585"
    bot_token: str = ""
    pinned_version: str = ""
    drive_service_name: str = "raw-documents"
    root_directory: str = "documents"
    require_existing_collection: bool = False
    required_properties: list[str] = Field(default_factory=lambda: list(FILTERABLE_FIELDS))


class StorageSettings(BaseModel):
    """Cấu hình Object Storage tương thích S3 (configs/storage.yml)."""

    endpoint: str = "http://localhost:9000"
    bucket: str = "raw-documents"
    region: str = "us-east-1"
    access_key: str = ""
    secret_key: str = ""
    presign_ttl_seconds: int = 300
    multipart_threshold_bytes: int = 16 * 1024 * 1024
    multipart_part_bytes: int = 8 * 1024 * 1024
    max_upload_bytes: int = 512 * 1024 * 1024
    object_prefix: str = "objects"


class IntentStoreSettings(BaseModel):
    """Cấu hình intent store (configs/intent_store.yml)."""

    kind: IntentStoreKind = IntentStoreKind.SQLITE
    sqlite_path: str = "local_data/document_service.sqlite"
    manifest_prefix: str = "intents"
    reconcile_interval_seconds: float = 30.0
    stale_after_seconds: float = 60.0
    max_retry_before_failed: int = 5


class RelationshipStoreSettings(BaseModel):
    """Cấu hình relationship store (configs/relationship_store.yml)."""

    kind: RelationshipStoreKind = RelationshipStoreKind.SQLITE
    sqlite_path: str = "local_data/document_service.sqlite"


class LockSettings(BaseModel):
    """Cấu hình khóa tài liệu C13 (configs/lock.yml).

    Quyết định Q12: `in_memory` chỉ chạy được một instance C1; triển khai nhiều
    instance bắt buộc `redis`, không thì mất I4/I5 mà không có lỗi báo.
    """

    kind: LockKind = LockKind.IN_MEMORY
    redis_url: str = "redis://localhost:6379/0"
    key_prefix: str = "ds:lock"
    lease_seconds: float = 15.0
    renew_interval_seconds: float = 5.0
    acquire_timeout_seconds: float = 0.5
    acquire_retry_delay_seconds: float = 0.05
    cancel_on_lease_loss: bool = True


class SecuritySettings(BaseModel):
    """Cấu hình định danh và phân quyền (configs/security.yml)."""

    auth_disabled: bool = True
    oidc_jwks_url: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = "document-service"
    admin_groups: list[str] = Field(default_factory=lambda: ["document-admins"])
    writer_groups: list[str] = Field(default_factory=lambda: ["document-writers"])
    approver_groups: list[str] = Field(default_factory=lambda: ["document-approvers"])
    require_idempotency_key: bool = True
    policy_cache_ttl_seconds: int = 300


class DependencyResiliencePolicy(BaseModel):
    """Tham số timeout, retry và circuit breaker cho một phụ thuộc."""

    connect_timeout_seconds: float = 1.0
    read_timeout_seconds: float = 3.0
    total_timeout_seconds: float = 5.0
    max_attempts: int = 3
    base_delay_seconds: float = 0.1
    max_delay_seconds: float = 1.0
    failure_ratio_threshold: float = 0.5
    rolling_window_size: int = 20
    open_duration_seconds: float = 10.0
    max_concurrent_calls: int = 16
    queue_capacity: int = 32
    max_retry_ratio: float = 0.1


class ResilienceSettings(BaseModel):
    """Tham số resilience cho từng phụ thuộc (configs/resilience.yml)."""

    catalog: DependencyResiliencePolicy = Field(
        default_factory=lambda: DependencyResiliencePolicy(
            read_timeout_seconds=5.0, total_timeout_seconds=8.0, max_attempts=2
        )
    )
    storage: DependencyResiliencePolicy = Field(
        default_factory=lambda: DependencyResiliencePolicy(
            read_timeout_seconds=2.0, total_timeout_seconds=4.0
        )
    )
    intent: DependencyResiliencePolicy = Field(
        default_factory=lambda: DependencyResiliencePolicy(
            connect_timeout_seconds=0.5,
            read_timeout_seconds=1.0,
            total_timeout_seconds=2.0,
            base_delay_seconds=0.05,
            max_delay_seconds=0.5,
        )
    )
    relationship: DependencyResiliencePolicy = Field(default_factory=DependencyResiliencePolicy)
    lock: DependencyResiliencePolicy = Field(
        default_factory=lambda: DependencyResiliencePolicy(
            connect_timeout_seconds=0.3,
            read_timeout_seconds=1.0,
            total_timeout_seconds=1.0,
            max_attempts=1,
            open_duration_seconds=5.0,
        )
    )
    events: DependencyResiliencePolicy = Field(
        default_factory=lambda: DependencyResiliencePolicy(
            read_timeout_seconds=3.0, total_timeout_seconds=5.0, max_attempts=2
        )
    )


class EventSettings(BaseModel):
    """Phát sự kiện cho downstream (configs/events.yml)."""

    enabled: bool = False
    webhook_urls: list[str] = Field(default_factory=list)
    batch_size: int = 50
    interval_seconds: float = 15.0
    max_attempts: int = 5


class SourceSettings(BaseModel):
    """Một nguồn tài liệu hiện có cần đồng bộ (configs/sync.yml)."""

    source_id: str
    source_type: str = "filesystem"
    root_path: str = ""
    collection_id: str = ""
    document_type: str = ""
    allowed_groups: list[str] = Field(default_factory=list)
    classification: str = "restricted"
    file_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".docx", ".xlsx", ".pptx", ".md", ".txt"]
    )


class SyncSettings(BaseModel):
    """Cấu hình đồng bộ từ nguồn hiện có (configs/sync.yml)."""

    enabled: bool = False
    interval_seconds: float = 300.0
    batch_size: int = 50
    sources: list[SourceSettings] = Field(default_factory=list)


class HealthSettings(BaseModel):
    """Cấu hình health check (configs/health.yml)."""

    cache_ttl_seconds: float = 5.0
    probe_timeout_seconds: float = 2.0
    backlog_threshold: int = 20
    startup_deadline_seconds: float = 120.0
    expose_details: bool = True


class Settings(BaseSettings):
    """Toàn bộ cấu hình của Document Service."""

    model_config = SettingsConfigDict(
        env_prefix="DS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    catalog: CatalogSettings = Field(default_factory=CatalogSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    intent: IntentStoreSettings = Field(default_factory=IntentStoreSettings)
    relationship: RelationshipStoreSettings = Field(default_factory=RelationshipStoreSettings)
    lock: LockSettings = Field(default_factory=LockSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
    health: HealthSettings = Field(default_factory=HealthSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    events: EventSettings = Field(default_factory=EventSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Xếp thứ tự nguồn cấu hình: init → env → .env → YAML → secret file."""
        files = config_files()
        yaml_source = YamlConfigSettingsSource(
            settings_cls, yaml_file=files or None, deep_merge=True
        )
        return (init_settings, env_settings, dotenv_settings, yaml_source, file_secret_settings)


class SettingsProvider(metaclass=SingletonMeta):
    """Giữ một instance Settings duy nhất cho cả tiến trình."""

    def __init__(self) -> None:
        """Đọc cấu hình ngay khi khởi tạo."""
        self._settings: Settings | None = Settings()

    @property
    def settings(self) -> Settings:
        """Cấu hình đang hiệu lực; nạp lại từ nguồn nếu đã bị `reset()`."""
        if self._settings is None:
            self._settings = Settings()
        return self._settings

    def reload(self) -> Settings:
        """Đọc lại cấu hình từ YAML và biến môi trường."""
        self._settings = Settings()
        return self._settings

    def replace(self, settings: Settings) -> None:
        """Thay cấu hình, chỉ dùng trong test và script."""
        self._settings = settings

    def reset(self) -> None:
        """Đưa provider về trạng thái chưa nạp (quy tắc R2 cho singleton).

        Khác `reload()`: `reset()` **không** đọc cấu hình ngay, lần truy cập
        `settings` kế tiếp mới nạp lại từ nguồn.
        """
        self._settings = None


def get_settings() -> Settings:
    """Lối truy cập ngắn tới cấu hình dùng chung."""
    return SettingsProvider().settings
